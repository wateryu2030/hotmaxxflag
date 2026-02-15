#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
好特卖进销存营销分析报告 - 自动生成并发送飞书
分析动销好、毛利高的产品，给出营销建议。
供 OpenClaw 定时任务或 cron 调用。
单独发送给 @余为军 (open_id: ou_8db735f2)，报告存入 MySQL 供后续分析。
"""
import os
import sys
from datetime import date, datetime

# 添加 htma_dashboard 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "htma_dashboard"))
import pymysql

from analytics import build_marketing_report
from feishu_util import send_feishu, FEISHU_AT_USER_ID, FEISHU_AT_USER_NAME

STORE_ID = "沈阳超级仓"
DAYS = 30  # 分析近 N 天
# 指定接收人：余为军 open_id 支持 8db735f2 或 ou_8db735f2
AT_USER_ID = os.environ.get("FEISHU_AT_USER_ID", "ou_8db735f2")
AT_USER_NAME = os.environ.get("FEISHU_AT_USER_NAME", "余为军")

DB_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", "62102218"),
    "database": "htma_dashboard",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}


def save_report_to_db(conn, report, send_ok, send_err=None):
    """将报告保存到 t_htma_report_log"""
    try:
        uid = AT_USER_ID.strip()
        if uid and not uid.startswith("ou_"):
            uid = f"ou_{uid}"
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO t_htma_report_log
               (report_date, report_time, store_id, report_content, feishu_at_user_id, feishu_at_user_name, send_status, send_error)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                date.today(),
                datetime.now(),
                STORE_ID,
                report,
                uid or None,
                AT_USER_NAME,
                1 if send_ok else 0,
                send_err[:512] if send_err else None,
            ),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"保存报告到数据库失败: {e}", file=sys.stderr)


def main():
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    conn = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        report = build_marketing_report(conn, STORE_ID, DAYS)
        print(report)
        send_ok = False
        send_err = None
        if not dry_run:
            send_ok, send_err = send_feishu(report, at_user_id=AT_USER_ID, at_user_name=AT_USER_NAME)
            if send_ok:
                print("\n✓ 已发送至飞书 @余为军", file=sys.stderr)
            else:
                print(f"\n✗ 飞书发送失败: {send_err}", file=sys.stderr)
        # 无论是否发送，都保存到 MySQL 供后续分析
        save_report_to_db(conn, report, send_ok, send_err)
        if not dry_run and not send_ok:
            sys.exit(1)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
