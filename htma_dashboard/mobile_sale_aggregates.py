# -*- coding: utf-8 -*-
"""
小程序经营数字与 Web 看板对齐：在存在 t_htma_sale 时，大类/日/月等聚合优先走明细表，
避免 daily_category_stats 未及时刷新导致销售额、趋势与看板 KPI 不一致。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _table_exists(cur, name: str) -> bool:
    try:
        cur.execute(
            "SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s LIMIT 1",
            (name,),
        )
        return bool(cur.fetchone())
    except Exception:
        return False


def _sale_has_column(cur, col: str) -> bool:
    try:
        cur.execute(
            "SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 't_htma_sale' AND COLUMN_NAME = %s LIMIT 1",
            (col,),
        )
        return bool(cur.fetchone())
    except Exception:
        return False


def use_sale_aggregates(cur, *, large_filter: Optional[str] = None) -> bool:
    """是否用 t_htma_sale 做区间聚合（与看板 KPI 同源）。"""
    if not _table_exists(cur, "t_htma_sale"):
        return False
    if large_filter and not _sale_has_column(cur, "category_large_code"):
        return False
    return True


def sale_max_data_date(cur, sq: str, sp: List[Any]) -> str:
    try:
        cur.execute("SELECT MAX(data_date) AS mx FROM t_htma_sale WHERE 1=1 " + sq, tuple(sp))
        mx = (cur.fetchone() or {}).get("mx")
        if mx is None:
            return ""
        return mx.isoformat()[:10] if hasattr(mx, "isoformat") else str(mx)[:10]
    except Exception:
        return ""


def fetch_category_large_rows(
    cur, s: str, e: str, sq: str, sp: List[Any]
) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT COALESCE(NULLIF(TRIM(category_large_code), ''), '') AS category_large_code,
               COALESCE(MAX(NULLIF(TRIM(category_large), '')), '') AS category_large,
               COALESCE(SUM(sale_amount), 0) AS sale_amount,
               COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS gross_profit,
               COALESCE(SUM(sale_qty), 0) AS sale_qty
        FROM t_htma_sale
        WHERE data_date BETWEEN %s AND %s
        """
        + sq
        + """
        GROUP BY COALESCE(NULLIF(TRIM(category_large_code), ''), '')
        ORDER BY sale_amount DESC
        """,
        (s, e) + tuple(sp),
    )
    return list(cur.fetchall() or [])


def fetch_category_mid_rows(
    cur, s: str, e: str, sq: str, sp: List[Any], large_code: str
) -> Optional[List[Dict[str, Any]]]:
    if not _sale_has_column(cur, "category_mid_code"):
        return None
    cur.execute(
        """
        SELECT COALESCE(NULLIF(TRIM(category_mid_code), ''), '') AS category_mid_code,
               COALESCE(MAX(NULLIF(TRIM(category_mid), '')), '') AS category_mid,
               COALESCE(SUM(sale_amount), 0) AS sale_amount,
               COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS gross_profit,
               COALESCE(SUM(sale_qty), 0) AS sale_qty
        FROM t_htma_sale
        WHERE data_date BETWEEN %s AND %s
          AND COALESCE(NULLIF(TRIM(category_large_code), ''), '') = %s
        """
        + sq
        + """
        GROUP BY COALESCE(NULLIF(TRIM(category_mid_code), ''), '')
        ORDER BY sale_amount DESC
        """,
        (s, e, large_code) + tuple(sp),
    )
    return list(cur.fetchall() or [])


def fetch_day_series_sa_gp(
    cur, s: str, e: str, sq: str, sp: List[Any]
) -> List[Dict[str, Any]]:
    """按日汇总 sa/gp，与 /api/kpi 趋势同源。"""
    cur.execute(
        """
        SELECT data_date,
               COALESCE(SUM(sale_amount), 0) AS sa,
               COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS gp
        FROM t_htma_sale
        WHERE data_date BETWEEN %s AND %s
        """
        + sq
        + " GROUP BY data_date ORDER BY data_date",
        (s, e) + tuple(sp),
    )
    return list(cur.fetchall() or [])


def fetch_insights_daily_large_rows(
    cur, start: str, end: str, sq: str, sp: List[Any]
) -> List[Dict[str, Any]]:
    """供 compute_large_category_insights：日×大类，字段 sa/gp 与 daily 路径一致。"""
    cur.execute(
        """
        SELECT data_date,
               COALESCE(NULLIF(TRIM(category_large_code), ''), '') AS category_large_code,
               COALESCE(MAX(NULLIF(TRIM(category_large), '')), '') AS category_large,
               COALESCE(SUM(sale_amount), 0) AS sa,
               COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS gp
        FROM t_htma_sale
        WHERE data_date BETWEEN %s AND %s
        """
        + sq
        + """
        GROUP BY data_date, COALESCE(NULLIF(TRIM(category_large_code), ''), '')
        ORDER BY data_date, category_large_code
        """,
        (start, end) + tuple(sp),
    )
    return list(cur.fetchall() or [])


def fetch_heatmap_month_rows(cur, s: str, e: str, sq: str, sp: List[Any]) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT DATE_FORMAT(data_date, '%%Y-%%m') AS ym,
               COALESCE(NULLIF(TRIM(category_large_code), ''), '') AS category_large_code,
               COALESCE(MAX(NULLIF(TRIM(category_large), '')), '') AS nm,
               COALESCE(SUM(sale_amount), 0) AS sa,
               COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS gp
        FROM t_htma_sale
        WHERE data_date BETWEEN %s AND %s
        """
        + sq
        + " GROUP BY DATE_FORMAT(data_date, '%%Y-%%m'), COALESCE(NULLIF(TRIM(category_large_code), ''), '')",
        (s, e) + tuple(sp),
    )
    return list(cur.fetchall() or [])


def fetch_category_share_rows(
    cur, s: str, e: str, sq: str, sp: List[Any]
) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT COALESCE(NULLIF(TRIM(category_large_code), ''), '') AS category_large_code,
               COALESCE(MAX(NULLIF(TRIM(category_large), '')), '') AS nm,
               COALESCE(SUM(sale_amount), 0) AS sa
        FROM t_htma_sale
        WHERE data_date BETWEEN %s AND %s
        """
        + sq
        + " GROUP BY COALESCE(NULLIF(TRIM(category_large_code), ''), '') ORDER BY sa DESC",
        (s, e) + tuple(sp),
    )
    return list(cur.fetchall() or [])


def fetch_contribution_rows(
    cur, s: str, e: str, sq: str, sp: List[Any]
) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT COALESCE(NULLIF(TRIM(category_large_code), ''), '') AS category_large_code,
               COALESCE(MAX(NULLIF(TRIM(category_large), '')), '') AS nm,
               COALESCE(SUM(sale_amount), 0) AS sa,
               COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS gp
        FROM t_htma_sale
        WHERE data_date BETWEEN %s AND %s
        """
        + sq
        + " GROUP BY COALESCE(NULLIF(TRIM(category_large_code), ''), '') ORDER BY sa DESC",
        (s, e) + tuple(sp),
    )
    return list(cur.fetchall() or [])


def fetch_week_series(cur, s: str, e: str, sq: str, sp: List[Any]) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT YEARWEEK(data_date, 1) AS yw,
               COALESCE(SUM(sale_amount), 0) AS sa,
               COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS gp
        FROM t_htma_sale
        WHERE data_date BETWEEN %s AND %s
        """
        + sq
        + " GROUP BY YEARWEEK(data_date, 1) ORDER BY YEARWEEK(data_date, 1) DESC LIMIT 120",
        (s, e) + tuple(sp),
    )
    return list(cur.fetchall() or [])


def fetch_month_series(cur, s: str, e: str, sq: str, sp: List[Any]) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT DATE_FORMAT(data_date, '%%Y-%%m') AS ym,
               COALESCE(SUM(sale_amount), 0) AS sa,
               COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS gp
        FROM t_htma_sale
        WHERE data_date BETWEEN %s AND %s
        """
        + sq
        + " GROUP BY DATE_FORMAT(data_date, '%%Y-%%m') ORDER BY ym DESC LIMIT 60",
        (s, e) + tuple(sp),
    )
    return list(cur.fetchall() or [])


def fetch_day_series_limited(
    cur, s: str, e: str, sq: str, sp: List[Any], limit: int = 400
) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit), 800))
    cur.execute(
        """
        SELECT data_date,
               COALESCE(SUM(sale_amount), 0) AS sa,
               COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS gp
        FROM t_htma_sale
        WHERE data_date BETWEEN %s AND %s
        """
        + sq
        + f" GROUP BY data_date ORDER BY data_date DESC LIMIT {lim}",
        (s, e) + tuple(sp),
    )
    rows = list(cur.fetchall() or [])
    return list(reversed(rows))


def alerts_total_sale_and_large_rows(
    cur, s: str, e: str, sq: str, sp: List[Any]
) -> Tuple[float, List[Dict[str, Any]]]:
    """低毛利大类预警：总销额 + 按大类聚合行（与 use_sale 时 alerts 逻辑一致）。"""
    cur.execute(
        "SELECT COALESCE(SUM(sale_amount), 0) AS t FROM t_htma_sale WHERE data_date BETWEEN %s AND %s " + sq,
        (s, e) + tuple(sp),
    )
    tot_sa = float((cur.fetchone() or {}).get("t") or 0.0) or 0.0
    cur.execute(
        """
        SELECT COALESCE(NULLIF(TRIM(category_large_code), ''), '') AS category_large_code,
               COALESCE(MAX(NULLIF(TRIM(category_large), '')), '') AS category_large,
               COALESCE(SUM(sale_amount), 0) AS sa,
               COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS gp
        FROM t_htma_sale
        WHERE data_date BETWEEN %s AND %s
        """
        + sq
        + " GROUP BY COALESCE(NULLIF(TRIM(category_large_code), ''), '') HAVING sa > 0.01",
        (s, e) + tuple(sp),
    )
    return tot_sa, list(cur.fetchall() or [])
