#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能上线通知：企业外飞书用户访问审批已启用，飞书 @ 余为军。
供 OpenClaw 部署/验收完成后执行。
用法: .venv/bin/python scripts/notify_feishu_external_approval_feature_done.py
"""
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
    sys.path.insert(0, os.path.join(_root, "htma_dashboard"))
    from notify_util import send_feishu

    base = (os.environ.get("HTMA_PUBLIC_URL") or "https://htma.greatagain.com.cn").strip().rstrip("/")
    text = (
        "【好特卖看板】企业外用户访问审批功能已上线\n\n"
        "• 企业内飞书用户：直接访问 htma.greatagain.com.cn\n"
        "• 企业外飞书用户：扫码后进入「等待审批」，由您审批通过后可访问\n"
        "• 审批入口（仅您可见）：%s/approval\n\n"
        "新申请时您会收到 @ 通知，请及时处理。"
    ) % base
    if not (os.environ.get("FEISHU_WEBHOOK_URL") or "").strip():
        print("未配置 FEISHU_WEBHOOK_URL，跳过飞书通知。配置后重新执行本脚本可 @ 余为军。")
        return
    ok, err = send_feishu(
        text,
        at_user_id=os.environ.get("HTMA_SUPER_ADMIN_OPEN_ID") or "8db735f2",
        at_user_name="余为军",
        title="企业外用户审批功能已启用",
    )
    if ok:
        print("已通知余为军")
    else:
        print("通知失败:", err)
        sys.exit(1)


if __name__ == "__main__":
    main()
