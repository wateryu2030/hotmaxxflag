#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书推送工具：支持 @ 指定人，供营销报告脚本与 API 共用"""
import os
import json
import ssl
import urllib.request
import urllib.error

_DEFAULT_FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/1b21bad3-22cb-4d9d-8f38-32526bd69d49"
FEISHU_WEBHOOK = (os.environ.get("FEISHU_WEBHOOK_URL") or "").strip() or _DEFAULT_FEISHU_WEBHOOK
# 余为军 open_id，支持 8db735f2 或 ou_8db735f2
FEISHU_AT_USER_ID = (os.environ.get("FEISHU_AT_USER_ID", "ou_8db735f2") or "ou_8db735f2").strip()
FEISHU_AT_USER_NAME = os.environ.get("FEISHU_AT_USER_NAME", "余为军")


def _normalize_open_id(uid):
    """将 8db735f2 转为 ou_8db735f2"""
    if not uid:
        return ""
    uid = uid.strip()
    if uid and not uid.startswith("ou_"):
        return f"ou_{uid}"
    return uid


# 飞书 webhook 单条消息长度上限（字节，留余量）
_FEISHU_TEXT_MAX = 3800


def send_feishu(text, at_user_id=None, at_user_name=None, title=None):
    """发送飞书消息。优先使用纯文本（msg_type=text）以保证自定义机器人兼容性；失败时返回飞书返回的错误信息。"""
    if not FEISHU_WEBHOOK or not text:
        return False, "未配置 FEISHU_WEBHOOK_URL 或内容为空，请在项目根 .env 中配置 FEISHU_WEBHOOK_URL"
    name = (at_user_name or FEISHU_AT_USER_NAME or "余为军").strip()
    post_title = (title or "好特卖进销存营销分析").strip()
    prefix = f"【发送给 {name}】{post_title}\n\n"
    raw = prefix + (text if isinstance(text, str) else "\n".join(text))
    if len(raw.encode("utf-8")) > _FEISHU_TEXT_MAX:
        raw = raw[: _FEISHU_TEXT_MAX // 2] + "\n\n…（内容已截断）"
    body = {"msg_type": "text", "content": {"text": raw}}
    req = urllib.request.Request(
        FEISHU_WEBHOOK,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            if resp.status in (200, 204):
                return True, None
            err_body = resp.read().decode("utf-8", errors="ignore")
            try:
                j = json.loads(err_body)
                msg = j.get("msg", "") or j.get("error", "") or err_body[:200]
            except Exception:
                msg = err_body[:200] if err_body else f"HTTP {resp.status}"
            return False, msg or f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore") if e.fp else ""
        try:
            j = json.loads(err_body)
            msg = j.get("msg", "") or j.get("error", "") or err_body[:200]
        except Exception:
            msg = err_body[:200] if err_body else str(e)
        return False, msg or str(e)
    except Exception as e:
        return False, str(e)
