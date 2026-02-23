#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""走势与环比日期范围逻辑测试（不加载 Flask/DB，避免卡住）"""
from datetime import date, timedelta, datetime

DEFAULT_DAYS = 30


def _period_over_period_ranges(period, start_date_str=None, end_date_str=None, today=None):
    if today is None:
        today = date.today()
    if start_date_str and end_date_str:
        try:
            curr_end = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            curr_start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except Exception:
            curr_start = curr_end = today
        length = (curr_end - curr_start).days + 1
        prev_end = curr_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=length - 1)
        return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"
    if period == "day":
        return today, today, today - timedelta(days=1), today - timedelta(days=1), str(today), str(today - timedelta(days=1))
    if period == "week":
        weekday = today.weekday()
        curr_start = today - timedelta(days=weekday)
        curr_end = curr_start + timedelta(days=6)
        prev_end = curr_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=6)
        return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"
    if period == "month":
        curr_start = today.replace(day=1)
        curr_end = today
        prev_end = curr_start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"
    days = DEFAULT_DAYS
    curr_end = today
    curr_start = today - timedelta(days=days - 1)
    prev_end = curr_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"


if __name__ == "__main__":
    today = date(2026, 2, 23)
    print("=== 走势与环比日期范围测试（模拟 today=2026-02-23）===\n")
    for period in ("recent30", "day", "week", "month"):
        r = _period_over_period_ranges(period, None, None, today=today)
        print(f"{period}: 本期 {r[4]}  上期 {r[5]}")
    print("\n自定义 2026-01-01~2026-01-31:")
    r = _period_over_period_ranges("custom", "2026-01-01", "2026-01-31", today=today)
    print(f"  本期 {r[4]}  上期 {r[5]}")
    print("\n完成。")
