# -*- coding: utf-8 -*-
"""
飞书自建应用机器人：事件订阅回调，群内 @ 机器人或私聊时自动回复。
依赖 FEISHU_APP_ID / FEISHU_APP_SECRET；可选 FEISHU_VERIFICATION_TOKEN、FEISHU_ENCRYPT_KEY（与开放平台事件订阅配置一致）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import threading
from typing import Any, Dict, Optional, Tuple

import requests

from auth import _tenant_access_token

logger = logging.getLogger(__name__)

FEISHU_API = "https://open.feishu.cn/open-apis"
_BOT_OPEN_ID_CACHE: Optional[str] = None


def _decrypt_feishu_body(cipher_b64: str, encrypt_key: str) -> Optional[Dict[str, Any]]:
    """事件体加密时解密（AES-256-CBC，与飞书文档一致）。"""
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
    except ImportError:
        logger.error("收到加密事件但未安装 pycryptodome，请: pip install pycryptodome")
        return None
    try:
        key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
        raw = base64.b64decode(cipher_b64)
        iv, body = raw[:16], raw[16:]
        plain = unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(body), AES.block_size)
        return json.loads(plain.decode("utf-8"))
    except Exception as e:
        logger.exception("飞书事件解密失败: %s", e)
        return None


def _verify_signature(timestamp: str, nonce: str, body: bytes, encrypt_key: str, signature: str) -> bool:
    """X-Lark-Signature：对 timestamp\\nnonce\\nencrypt_key\\nbody 原文字符串做 HMAC-SHA256(key=encrypt_key)，Base64。"""
    if not (timestamp and nonce and encrypt_key and signature):
        return False
    try:
        body_str = body.decode("utf-8")
        to_sign = f"{timestamp}\n{nonce}\n{encrypt_key}\n{body_str}"
        mac = hmac.new(
            encrypt_key.encode("utf-8"),
            to_sign.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expect = base64.b64encode(mac).decode("utf-8")
        sig = signature.strip()
        if sig.startswith("v1="):
            sig = sig[3:]
        return hmac.compare_digest(expect, sig)
    except Exception:
        return False


def _get_bot_open_id(tenant_token: str) -> Optional[str]:
    global _BOT_OPEN_ID_CACHE
    if _BOT_OPEN_ID_CACHE:
        return _BOT_OPEN_ID_CACHE
    try:
        r = requests.get(
            f"{FEISHU_API}/bot/v3/info",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=10,
        )
        data = r.json()
        if data.get("code") != 0:
            logger.warning("bot/v3/info: %s", data.get("msg"))
            return None
        bot = (data.get("bot") or {})
        oid = (bot.get("open_id") or "").strip()
        if oid:
            _BOT_OPEN_ID_CACHE = oid
        return oid or None
    except Exception as e:
        logger.warning("获取机器人 open_id 失败: %s", e)
        return None


def _parse_text_content(content_json: str) -> str:
    try:
        obj = json.loads(content_json or "{}")
        return (obj.get("text") or "").strip()
    except Exception:
        return ""


def _mentions_include_bot(mentions: Any, bot_open_id: str) -> bool:
    if not mentions or not bot_open_id:
        return False
    for m in mentions:
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        if isinstance(mid, dict):
            oid = (mid.get("open_id") or "").strip()
            if oid == bot_open_id:
                return True
    return False


def _strip_at_markup(text: str) -> str:
    return re.sub(r"<at[^>]*></at>", "", text).replace("\u200b", "").strip()


def _send_text_to_chat(tenant_token: str, chat_id: str, text: str) -> Tuple[bool, str]:
    url = f"{FEISHU_API}/im/v1/messages?receive_id_type=chat_id"
    body = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text[:4000]}, ensure_ascii=False),
    }
    try:
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {tenant_token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=15,
        )
        data = r.json()
        if data.get("code") == 0:
            return True, ""
        return False, str(data.get("msg") or data)
    except Exception as e:
        return False, str(e)


def _handle_message_event(event: Dict[str, Any], app_id: str, app_secret: str) -> None:
    message = event.get("message") or {}
    sender = event.get("sender") or {}
    if (sender.get("sender_type") or "").lower() == "app":
        return

    chat_type = (message.get("chat_type") or "").lower()
    chat_id = (message.get("chat_id") or "").strip()
    if not chat_id:
        return

    if (message.get("message_type") or "").lower() != "text":
        return

    text = _strip_at_markup(_parse_text_content(message.get("content") or ""))
    if not text:
        return

    mode = (os.environ.get("FEISHU_BOT_REPLY_MODE") or "mention").strip().lower()
    tenant_token, err = _tenant_access_token(app_id=app_id, app_secret=app_secret)
    if err or not tenant_token:
        logger.warning("tenant_token 失败: %s", err)
        return

    bot_oid = (os.environ.get("FEISHU_BOT_OPEN_ID") or "").strip() or _get_bot_open_id(tenant_token)
    mentions = message.get("mentions") or event.get("mentions")

    if chat_type != "p2p":
        if mode == "p2p_only":
            return
        if mode == "mention":
            if not _mentions_include_bot(mentions, bot_oid or ""):
                return

    sender_id = (sender.get("sender_id") or {})
    user_open_id = (sender_id.get("open_id") or "").strip()
    try:
        from feishu_bot_brain import build_reply

        reply = build_reply(text, user_open_id)
    except Exception:
        logger.exception("feishu_bot_brain 处理失败，回退为原文回显")
        reply = text
    prefix = (os.environ.get("FEISHU_BOT_REPLY_PREFIX") or "【好特卖】").strip()
    if prefix:
        reply = f"{prefix}\n{reply}"
    ok, emsg = _send_text_to_chat(tenant_token, chat_id, reply)
    if not ok:
        logger.warning("飞书发消息失败: %s", emsg)


def process_feishu_bot_http_request(
    raw_body: bytes,
    headers: Any,
    app_id: str,
    app_secret: str,
) -> Tuple[Dict[str, Any], int]:
    """
    处理飞书事件 HTTP 回调。返回 (json_dict, http_status)。
    """
    encrypt_key = (os.environ.get("FEISHU_ENCRYPT_KEY") or "").strip()
    verify_token = (os.environ.get("FEISHU_VERIFICATION_TOKEN") or "").strip()

    ts = (headers.get("X-Lark-Request-Timestamp") or headers.get("X-Lark-Request-Timestamp".lower()) or "").strip()
    nonce = (headers.get("X-Lark-Request-Nonce") or "").strip()
    signature = (headers.get("X-Lark-Signature") or "").strip()

    if encrypt_key and ts and nonce and signature:
        if not _verify_signature(ts, nonce, raw_body, encrypt_key, signature):
            logger.warning("飞书签名校验失败")
            return {"msg": "invalid signature"}, 403

    try:
        data = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        return {"msg": "invalid json"}, 400

    if data.get("encrypt") and encrypt_key:
        decrypted = _decrypt_feishu_body(data["encrypt"], encrypt_key)
        if not decrypted:
            return {"msg": "decrypt failed"}, 400
        data = decrypted

    # 仅当 body 含 header.token 时校验（2.0 订阅）；旧版 url_verification 无 header，避免误拒
    if verify_token:
        hdr = data.get("header") or {}
        if isinstance(hdr, dict) and "token" in hdr and hdr.get("token") != verify_token:
            logger.warning("飞书 Verification Token 不匹配")
            return {"msg": "forbidden"}, 403

    # 2.0 订阅：URL 验证
    schema = data.get("schema")
    header = data.get("header") or {}
    event_type = (header.get("event_type") or "").strip()

    if schema == "2.0" and event_type == "event_callback_url_verification":
        ch = (data.get("event") or {}).get("challenge")
        if ch is not None:
            return {"challenge": ch}, 200

    if schema == "2.0" and event_type == "im.message.receive_v1":
        ev = data.get("event") or {}

        def _run():
            try:
                _handle_message_event(ev, app_id, app_secret)
            except Exception:
                logger.exception("处理 im.message.receive_v1 异常")

        threading.Thread(target=_run, daemon=True).start()
        return {}, 200

    # 旧版 url_verification：顶层 type + challenge（与常见教程一致，jsonify 仅含 challenge）
    if data.get("type") == "url_verification" and "challenge" in data:
        return {"challenge": data["challenge"]}, 200

    # 旧版 event_callback：顶层 type，event 内含 event_type / message / sender
    if data.get("type") == "event_callback":
        ev = data.get("event") or {}
        if ev.get("event_type") == "im.message.receive_v1":

            def _run_legacy():
                try:
                    _handle_message_event(ev, app_id, app_secret)
                except Exception:
                    logger.exception("处理旧版 im.message.receive_v1 异常")

            threading.Thread(target=_run_legacy, daemon=True).start()
            return {"status": "success"}, 200
        return {}, 200

    # 其他事件：快速 200，避免飞书重试风暴
    return {}, 200
