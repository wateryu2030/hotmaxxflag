#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
好特卖每日自动比价 - 按当日（或昨日）销售 TOP 商品比价并推送飞书
供 Cursor / OpenClaw / cron 无人值守执行。
接收人默认余为军（ou_8db735f2），可通过环境变量 FEISHU_AT_USER_ID / FEISHU_AT_USER_NAME 修改。
"""
import os
import sys

# 项目根目录，保证 .env 与 MySQL 配置可用
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)
# 使 htma_dashboard 内模块可被 import
sys.path.insert(0, os.path.join(ROOT, "htma_dashboard"))

from price_compare import run_daily_top_compare, format_report
from feishu_util import send_feishu, FEISHU_AT_USER_ID, FEISHU_AT_USER_NAME


def main():
    limit = int(os.environ.get("PRICE_COMPARE_DAILY_LIMIT", "50"))
    fetch_limit = os.environ.get("PRICE_COMPARE_FETCH_LIMIT")
    if fetch_limit is not None:
        fetch_limit = int(fetch_limit)
    at_user_id = os.environ.get("FEISHU_AT_USER_ID", "ou_8db735f2")
    at_user_name = os.environ.get("FEISHU_AT_USER_NAME", "余为军")

    from app import get_conn, STORE_ID
    conn = get_conn()
    try:
        result = run_daily_top_compare(
            conn,
            store_id=STORE_ID,
            data_date=None,
            limit=limit,
            use_mock_fetcher=False,
            save_to_db=True,
            fetch_limit=fetch_limit or limit,
        )
        report = format_report(result)
        items = result.get("items", [])
        if not items:
            print("当日无销售数据或无可比价商品，未发送飞书。", file=sys.stderr)
            return 0
        send_ok, err = send_feishu(
            report,
            at_user_id=at_user_id,
            at_user_name=at_user_name,
            title="好特卖商品比价报告",
        )
        if send_ok:
            print(f"已发送比价报告至飞书 @{at_user_name}（共 {len(items)} 条）", file=sys.stderr)
        else:
            print(f"飞书发送失败: {err}", file=sys.stderr)
            return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
