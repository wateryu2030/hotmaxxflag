#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 t_htma_sale 刷新 daily_category_stats。

用法（与历史兼容）:
  python3 scripts/refresh_daily_category_stats.py [store_id] [YYYY-MM-DD] [YYYY-MM-DD]
  默认: 单店为环境变量 HTMA_STORE_ID 或「沈阳超级仓」、日期为近 60 天。

全量刷新（与明细表日期区间一致，按块提交）:
  python3 scripts/refresh_daily_category_stats.py --full
  python3 scripts/refresh_daily_category_stats.py --full  某门店ID
  python3 scripts/refresh_daily_category_stats.py --full --all-stores

可选环境变量:
  HTMA_REFRESH_CHUNK_DAYS — 全量/长区间时每段天数，默认 120（上限 400）
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HTMA = os.path.join(_ROOT, "htma_dashboard")
if _HTMA not in sys.path:
    sys.path.insert(0, _HTMA)

from db_config import get_conn  # noqa: E402
from daily_stats_service import (  # noqa: E402
    refresh_daily_category_stats,
    refresh_daily_category_stats_chunked,
)


def _chunk_days() -> int:
    try:
        n = int((os.environ.get("HTMA_REFRESH_CHUNK_DAYS") or "120").strip())
    except ValueError:
        n = 120
    return max(7, min(n, 400))


def _sale_bounds_for_store(cur, store_id: str) -> tuple[str, str] | None:
    cur.execute(
        "SELECT MIN(data_date) AS mn, MAX(data_date) AS mx FROM t_htma_sale WHERE store_id = %s",
        (store_id,),
    )
    r = cur.fetchone() or {}
    mn, mx = r.get("mn"), r.get("mx")
    if mn is None or mx is None:
        return None
    s = mn.isoformat()[:10] if hasattr(mn, "isoformat") else str(mn)[:10]
    e = mx.isoformat()[:10] if hasattr(mx, "isoformat") else str(mx)[:10]
    return s, e


def _distinct_sale_store_ids(cur) -> list[str]:
    cur.execute(
        "SELECT DISTINCT store_id FROM t_htma_sale WHERE COALESCE(TRIM(store_id),'') != '' ORDER BY store_id"
    )
    out: list[str] = []
    for row in cur.fetchall() or []:
        sid = str((row or {}).get("store_id") or "").strip()
        if sid:
            out.append(sid)
    return out


def _table_exists(cur, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s LIMIT 1",
        (name,),
    )
    return cur.fetchone() is not None


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    full = "--full" in argv
    all_stores = "--all-stores" in argv
    argv = [a for a in argv if a not in ("--full", "--all-stores")]

    conn = get_conn()
    try:
        cur = conn.cursor()
        if not _table_exists(cur, "daily_category_stats"):
            print("错误: 表 daily_category_stats 不存在，请先执行 scripts/27_daily_category_stats.sql", file=sys.stderr)
            return 1
        if not _table_exists(cur, "t_htma_sale"):
            print("错误: 表 t_htma_sale 不存在", file=sys.stderr)
            return 1

        chunk = _chunk_days()

        if full:
            if all_stores:
                store_ids = _distinct_sale_store_ids(cur)
                if not store_ids:
                    print("全量: t_htma_sale 中无 store_id，退出")
                    return 0
                grand = 0
                for sid in store_ids:
                    bounds = _sale_bounds_for_store(cur, sid)
                    if not bounds:
                        print("skip store (无明细):", sid)
                        continue
                    s, e = bounds
                    print("全量刷新 store=%s 区间 %s .. %s (chunk=%s 天)" % (sid, s, e, chunk))
                    n = refresh_daily_category_stats_chunked(conn, sid, s, e, chunk_days=chunk)
                    print("  -> 插入行数(合计, 近似):", n)
                    grand += n
                print("全部门店完成, 行数合计(近似):", grand)
                return 0

            store = (argv[0] if argv else os.environ.get("HTMA_STORE_ID") or "沈阳超级仓").strip()
            bounds = _sale_bounds_for_store(cur, store)
            if not bounds:
                print("全量: 门店 %s 在 t_htma_sale 无数据" % store)
                return 0
            s, e = bounds
            print("全量刷新 store=%s 区间 %s .. %s (chunk=%s 天)" % (store, s, e, chunk))
            n = refresh_daily_category_stats_chunked(conn, store, s, e, chunk_days=chunk)
            print("refresh_daily_category_stats rows(合计, 近似):", n, "store:", store, "range:", s, "..", e)
            return 0

        # 兼容: store [start] [end]
        store = (argv[0] if argv else os.environ.get("HTMA_STORE_ID") or "沈阳超级仓").strip()
        if len(argv) >= 3:
            start_d, end_d = argv[1][:10], argv[2][:10]
        else:
            end = date.today()
            start = end - timedelta(days=59)
            start_d, end_d = start.isoformat(), end.isoformat()

        span = (date.fromisoformat(end_d) - date.fromisoformat(start_d)).days + 1
        if span > chunk:
            print("区间 %s 天 > chunk=%s，自动分块刷新" % (span, chunk))
            n = refresh_daily_category_stats_chunked(conn, store, start_d, end_d, chunk_days=chunk)
        else:
            n = refresh_daily_category_stats(conn, store, start_d, end_d)
        print("refresh_daily_category_stats rows:", n, "store:", store, "range:", start_d, "..", end_d)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
