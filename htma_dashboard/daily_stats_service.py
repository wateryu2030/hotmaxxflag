# -*- coding: utf-8 -*-
"""
日×店×大类×中类预聚合表 daily_category_stats：减轻 t_htma_sale 大表扫描。
- 建表：scripts/27_daily_category_stats.sql
- 刷新：refresh_daily_category_stats(conn, store_id, start_date, end_date)
- KPI 快路径：try_totals_from_daily_stats(...)
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Tuple


def _table_exists(cur) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'daily_category_stats' LIMIT 1
        """
    )
    return cur.fetchone() is not None


def resolve_date_bounds(period: str, start_d: str, end_d: str) -> Optional[Tuple[str, str]]:
    """返回 (start_iso, end_iso) 或 None。"""
    today = date.today()
    if start_d and end_d and len(start_d) >= 10 and len(end_d) >= 10:
        return start_d[:10], end_d[:10]
    if period == "day":
        s = today.isoformat()
        return s, s
    if period == "week":
        return (today - timedelta(days=6)).isoformat(), today.isoformat()
    if period == "month":
        first = today.replace(day=1)
        return first.isoformat(), today.isoformat()
    if period == "recent30":
        return (today - timedelta(days=29)).isoformat(), today.isoformat()
    return None


def try_totals_from_daily_stats(conn, store_id: str, period: str, start_d: str, end_d: str) -> Optional[Tuple[float, float]]:
    """若预聚合表有数据则返回 (sale_sum, profit_sum)，否则 None。单独 cursor，避免与外层查询嵌套。"""
    bounds = resolve_date_bounds(period, start_d, end_d)
    if not bounds:
        return None
    s, e = bounds
    cur = conn.cursor()
    try:
        if not _table_exists(cur):
            return None
        cur.execute(
            """
            SELECT COALESCE(SUM(sale_amount), 0) AS sa, COALESCE(SUM(gross_profit), 0) AS gp
            FROM daily_category_stats
            WHERE store_id = %s AND data_date BETWEEN %s AND %s
            """,
            (store_id, s, e),
        )
        row = cur.fetchone() or {}
        sa = float(row.get("sa") or 0)
        gp = float(row.get("gp") or 0)
        cur.execute(
            "SELECT COUNT(*) AS c FROM daily_category_stats WHERE store_id = %s AND data_date BETWEEN %s AND %s",
            (store_id, s, e),
        )
        cnt = int((cur.fetchone() or {}).get("c") or 0)
    finally:
        cur.close()
    if cnt == 0 and sa == 0 and gp == 0:
        return None
    return sa, gp


def refresh_daily_category_stats(conn, store_id: str, start_date: str, end_date: str) -> int:
    """删除区间内旧数据后从 t_htma_sale 重算插入；返回插入行数（近似）。"""
    cur = conn.cursor()
    try:
        if not _table_exists(cur):
            return 0
        cur.execute(
            "DELETE FROM daily_category_stats WHERE store_id = %s AND data_date BETWEEN %s AND %s",
            (store_id, start_date, end_date),
        )
        cur.execute(
            """
            INSERT INTO daily_category_stats
            (store_id, data_date, category_large_code, category_large, category_mid_code, category_mid,
             sale_qty, sale_amount, sale_cost, gross_profit)
            SELECT store_id, data_date,
                   COALESCE(NULLIF(TRIM(category_large_code), ''), ''),
                   COALESCE(MAX(NULLIF(TRIM(category_large), '')), ''),
                   COALESCE(NULLIF(TRIM(category_mid_code), ''), ''),
                   COALESCE(MAX(NULLIF(TRIM(category_mid), '')), ''),
                   COALESCE(SUM(sale_qty), 0),
                   COALESCE(SUM(sale_amount), 0),
                   COALESCE(SUM(COALESCE(sale_cost, 0)), 0),
                   COALESCE(SUM(COALESCE(gross_profit, 0)), 0)
            FROM t_htma_sale
            WHERE store_id = %s AND data_date BETWEEN %s AND %s
            GROUP BY store_id, data_date,
                     COALESCE(NULLIF(TRIM(category_large_code), ''), ''),
                     COALESCE(NULLIF(TRIM(category_mid_code), ''), '')
            """,
            (store_id, start_date, end_date),
        )
        cur.execute(
            "SELECT COUNT(*) AS c FROM daily_category_stats WHERE store_id = %s AND data_date BETWEEN %s AND %s",
            (store_id, start_date, end_date),
        )
        n = int((cur.fetchone() or {}).get("c") or 0)
    finally:
        cur.close()
    conn.commit()
    return n


def refresh_daily_category_stats_chunked(
    conn,
    store_id: str,
    start_date: str,
    end_date: str,
    *,
    chunk_days: int = 120,
) -> int:
    """
    将 [start_date, end_date] 按 chunk_days 切段多次刷新，降低长区间单次 DELETE+INSERT 的锁与内存压力。
    返回各段插入行数之和（近似）。
    """
    d0 = date.fromisoformat(str(start_date)[:10])
    d1 = date.fromisoformat(str(end_date)[:10])
    if d0 > d1:
        d0, d1 = d1, d0
    chunk = max(1, min(int(chunk_days), 400))
    total = 0
    cur = d0
    while cur <= d1:
        end_chunk = min(cur + timedelta(days=chunk - 1), d1)
        total += refresh_daily_category_stats(conn, store_id, cur.isoformat(), end_chunk.isoformat())
        cur = end_chunk + timedelta(days=1)
    return total
