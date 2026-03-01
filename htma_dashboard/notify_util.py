#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多通道通知：飞书 + 企业微信 + 钉钉，一次发送可同时推送到已配置的通道。
供报告、比价、导入完成等脚本与 API 复用；其他项目可复制本文件与 .env 配置直接使用。
"""
import os
import json
import time
import hmac
import hashlib
import base64
import urllib.parse
import urllib.request
import ssl

# 飞书（现有逻辑，与 feishu_util 保持一致）
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
FEISHU_AT_USER_ID = (os.environ.get("FEISHU_AT_USER_ID", "ou_8db735f2") or "").strip()
FEISHU_AT_USER_NAME = os.environ.get("FEISHU_AT_USER_NAME", "余为军") or ""

# 企业微信群机器人 webhook（格式: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx）
WECOM_WEBHOOK = os.environ.get("WECOM_WEBHOOK_URL", "").strip()

# 钉钉自定义机器人（access_token 在 URL 中；加签时填 DINGTALK_SECRET）
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK_URL", "").strip()
DINGTALK_SECRET = os.environ.get("DINGTALK_SECRET", "").strip()


def _http_post(url, body, headers=None):
    if not url:
        return False, "URL 为空"
    h = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=h, method="POST")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            if resp.status in (200, 204):
                return True, None
            return False, f"HTTP {resp.status}"
    except Exception as e:
        return False, str(e)


def send_feishu(text, at_user_id=None, at_user_name=None, title=None):
    """发送飞书（富文本 @ 人）。与 feishu_util.send_feishu 行为一致。"""
    if not FEISHU_WEBHOOK or not text:
        return False, "未配置 FEISHU_WEBHOOK_URL 或内容为空"
    try:
        from .feishu_util import send_feishu as _send
        return _send(text, at_user_id=at_user_id or FEISHU_AT_USER_ID, at_user_name=at_user_name or FEISHU_AT_USER_NAME, title=title)
    except Exception as e:
        return False, str(e)


def send_wecom(text, mentioned_list=None):
    """
    发送企业微信群机器人消息。
    mentioned_list: 如 ["@all"] 或 ["userid"]，不传则仅发文本。
    """
    if not WECOM_WEBHOOK or not text:
        return False, "未配置 WECOM_WEBHOOK_URL 或内容为空"
    body = {"msgtype": "text", "text": {"content": text[:4090]}}
    if mentioned_list:
        body["text"]["mentioned_list"] = mentioned_list
    return _http_post(WECOM_WEBHOOK, body)


def send_dingtalk(text, at_all=False, at_mobiles=None, at_user_ids=None):
    """
    发送钉钉自定义机器人消息。
    若配置了 DINGTALK_SECRET，会自动对 URL 加签（钉钉安全设置选「加签」时必填）。
    """
    if not DINGTALK_WEBHOOK or not text:
        return False, "未配置 DINGTALK_WEBHOOK_URL 或内容为空"
    url = DINGTALK_WEBHOOK
    if DINGTALK_SECRET:
        ts = str(round(time.time() * 1000))
        sign = _dingtalk_sign(ts, DINGTALK_SECRET)
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}timestamp={ts}&sign={urllib.parse.quote(sign)}"
    body = {"msgtype": "text", "text": {"content": text[:19900]}}
    if at_all or at_mobiles or at_user_ids:
        body["at"] = {"isAtAll": bool(at_all), "atMobiles": at_mobiles or [], "atUserIds": at_user_ids or []}
    return _http_post(url, body)


def _dingtalk_sign(timestamp, secret):
    s = f"{timestamp}\n{secret}"
    h = hmac.new(secret.encode("utf-8"), s.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(h).decode("utf-8")


def notify_all(text, title=None, feishu_at_user_id=None, feishu_at_user_name=None):
    """
    一次发送到所有已配置的通道：飞书、企业微信、钉钉。
    返回: (results_dict, all_ok)
    results_dict 形如 {"feishu": (ok, err), "wecom": (ok, err), "dingtalk": (ok, err)}
    """
    results = {}
    if FEISHU_WEBHOOK:
        results["feishu"] = send_feishu(text, at_user_id=feishu_at_user_id, at_user_name=feishu_at_user_name, title=title)
    else:
        results["feishu"] = (False, "未配置 FEISHU_WEBHOOK_URL")
    if WECOM_WEBHOOK:
        results["wecom"] = send_wecom(text)
    else:
        results["wecom"] = (False, "未配置 WECOM_WEBHOOK_URL")
    if DINGTALK_WEBHOOK:
        results["dingtalk"] = send_dingtalk(text)
    else:
        results["dingtalk"] = (False, "未配置 DINGTALK_WEBHOOK_URL")
    all_ok = all(r[0] for r in results.values())
    return results, all_ok
