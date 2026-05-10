#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每晚经营闭环（建议 23:00 跑）：刷新分类日表 → 规则预警 → AI 经营快报。
保证小程序「今日」KPI、归因 Tab 等依赖的 daily_category_stats 尽量新。

环境变量：
  HTMA_STORE_ID — 默认门店（单店时用于预警与快报）
  HTMA_NIGHTLY_STORE_IDS — 可选，逗号分隔多店；刷新 daily_category_stats 时每店执行一遍；
                            预警/快报仍按 HTMA_STORE_ID 各跑一次（多店需自行扩展或多次定时）
  HTMA_NIGHTLY_REFRESH_LOOKBACK_DAYS — 刷新区间天数，默认 90（上限 400）
  HTMA_CRON_WEBHOOK_URL / FEISHU_WEBHOOK_URL / HTMA_CRON_NOTIFY_SUCCESS — 同 daily_cron_job

Linux crontab（服务器时区）:
  0 23 * * * cd /path/to/repo && .venv/bin/python3 scripts/nightly_business_job.py >>logs/nightly_business.out 2>>logs/nightly_business.err
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HTMA = os.path.join(_ROOT, "htma_dashboard")
if _HTMA not in sys.path:
    sys.path.insert(0, _HTMA)
_SCRIPTS = os.path.abspath(os.path.dirname(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from htma_cron_util import cron_notify, cron_run_step  # noqa: E402


def _store_ids_refresh() -> list:
    raw = (os.environ.get("HTMA_NIGHTLY_STORE_IDS") or os.environ.get("HTMA_STORE_ID") or "沈阳超级仓").strip()
    return [x.strip() for x in raw.split(",") if x.strip()]


def _refresh_daily_stats() -> dict:
    from db_config import get_conn
    from daily_stats_service import refresh_daily_category_stats

    try:
        days = int((os.environ.get("HTMA_NIGHTLY_REFRESH_LOOKBACK_DAYS") or "90").strip())
    except ValueError:
        days = 90
    days = max(7, min(days, 400))
    end = date.today()
    start = end - timedelta(days=days - 1)
    s, e = start.isoformat(), end.isoformat()
    conn = get_conn()
    per: list = []
    try:
        for sid in _store_ids_refresh():
            n = refresh_daily_category_stats(conn, sid, s, e)
            per.append({"store_id": sid, "rows": n})
    finally:
        conn.close()
    return {"ok": True, "range": {"start_date": s, "end_date": e}, "stores": per}


def _alerts_one() -> dict:
    from alert_engine import check_all_rules

    return check_all_rules()


def _ai_one() -> dict:
    from ai_advisor import generate_daily_summary

    return generate_daily_summary()


def main() -> int:
    os.environ.setdefault("HTMA_SKIP_MOBILE_JWT", "1")
    cron_run_step("refresh_daily_category_stats", _refresh_daily_stats)
    cron_run_step("check_all_rules", _alerts_one)
    cron_run_step("generate_daily_summary", _ai_one)
    print("nightly_business_job 完成（分类日表+预警+AI快报）；单步成功通知见 HTMA_CRON_NOTIFY_SUCCESS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("nightly_business_job fatal:", e, file=sys.stderr)
        raise SystemExit(1)
