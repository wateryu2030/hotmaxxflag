#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书推送工具：支持 @ 指定人，供营销报告脚本与 API 共用"""
import os
import json
import urllib.request
import ssl

FEISHU_WEBHOOK = os.environ.get(
    "FEISHU_WEBHOOK_URL",
    "https://open.feishu.cn/open-apis/bot/v2/hook/1b21bad3-22cb-4d9d-8f38-32526bd69d49",
)
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


def send_feishu(text, at_user_id=None, at_user_name=None, title=None):
    """发送飞书消息。at_user_id 时使用富文本 @ 指定人。
    at_user_id 支持 8db735f2 或 ou_8db735f2 格式。
    title: 富文本标题，默认「好特卖进销存营销分析」；比价报告可传「好特卖商品比价报告」。"""
    if not FEISHU_WEBHOOK or not text:
        return False, None
    uid = _normalize_open_id(at_user_id or FEISHU_AT_USER_ID)
    name = at_user_name or FEISHU_AT_USER_NAME
    post_title = title or "好特卖进销存营销分析"
    try:
        if uid:
            lines = text.split("\n")
            prompt = "请查看进销存营销报告：" if "比价" not in (title or "") else "请查看商品比价报告："
            content = [[{"tag": "at", "user_id": uid}, {"tag": "text", "text": f" {name}，{prompt}\n"}]]
            for line in lines:
                content.append([{"tag": "text", "text": line + "\n"}])
            body = {
                "msg_type": "post",
                "content": {
                    "post": {
                        "zh_cn": {
                            "title": post_title,
                            "content": content,
                        }
                    }
                }
            }
        else:
            body = {"msg_type": "text", "content": {"text": f"【@余为军】\n\n{text}"}}
        req = urllib.request.Request(
            FEISHU_WEBHOOK,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        ctx = ssl.create_default_context()
        last_err = None
        for _ in range(2):
            try:
                with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                    if resp.status in (200, 204):
                        return True, None
            except (ssl.SSLError, OSError) as e:
                last_err = e
                continue
        if last_err:
            return False, str(last_err)
        return True, None
    except Exception as e:
        return False, str(e)
