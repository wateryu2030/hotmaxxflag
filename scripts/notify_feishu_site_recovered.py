#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看板恢复后飞书通知 余为军。从项目根或 htma_dashboard 运行，会加载 .env。"""
import os
import sys

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(_project_root)
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "htma_dashboard"))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_project_root, ".env"))
except Exception:
    pass

def main():
    url = os.environ.get("HTMA_PUBLIC_URL", "https://htma.greatagain.com.cn")
    text = f"好特卖看板已恢复运行。\n\n请验证：\n• 网址：{url}\n• 飞书扫码登录可用。"
    try:
        from htma_dashboard.feishu_util import send_feishu
        ok, err = send_feishu(
            text,
            at_user_id=os.environ.get("FEISHU_AT_USER_ID", "ou_8db735f2"),
            at_user_name=os.environ.get("FEISHU_AT_USER_NAME", "余为军"),
            title="看板恢复通知",
        )
        if ok:
            print("已飞书通知余为军。")
        else:
            print("飞书发送失败:", err or "未知")
    except Exception as e:
        print("飞书通知异常:", e)

if __name__ == "__main__":
    main()
