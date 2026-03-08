#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能上线后通知余为军：企业外飞书用户审批功能已就绪。供 OpenClaw 自动化执行。"""
import os
import sys

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _root)
os.chdir(_root)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))
except Exception:
    pass

def main():
    htma = os.path.join(_root, "htma_dashboard")
    if htma not in sys.path:
        sys.path.insert(0, htma)
    from notify_util import send_feishu
    from auth import _super_admin_open_id

    base = (os.environ.get("HTMA_PUBLIC_URL") or "https://htma.greatagain.com.cn").strip().rstrip("/")
    text = (
        "【好特卖看板】企业外用户访问审批功能已上线\n\n"
        "• 企业内飞书用户：直接访问 htma.greatagain.com.cn\n"
        "• 企业外飞书用户：扫码后进入「等待审批」页，您审批通过后即可访问\n"
        "• 审批入口：%s/approval（仅超级管理员余为军可访问）\n"
        "• 新申请时会收到本群 @ 通知，点击链接即可审批"
    ) % base
    ok, err = send_feishu(
        text,
        at_user_id=_super_admin_open_id(),
        at_user_name="余为军",
        title="企业外用户访问审批已就绪",
    )
    if ok:
        print("已通知余为军")
    else:
        print("通知失败:", err)
        sys.exit(1)

if __name__ == "__main__":
    main()
