# -*- coding: utf-8 -*-
"""毛利率计算 — analyze/margin"""

from datetime import datetime


def get_unified_margin(conn, category_level, category_name, start_date, end_date, store_id="沈阳超级仓"):
    """
    阶段 A1：基于 t_htma_sale 聚合毛利率 = sum(gross_profit)/sum(sale_amount)×100。
    category_level: category | large | mid | small
    """
    level = (category_level or "category").strip().lower()
    expr_map = {
        "category": "COALESCE(NULLIF(TRIM(category), ''), '未分类')",
        "large": "COALESCE(NULLIF(TRIM(category_large), ''), '未分类')",
        "mid": "COALESCE(NULLIF(TRIM(category_mid), ''), '未分类')",
        "small": "COALESCE(NULLIF(TRIM(category_small), ''), '未分类')",
    }
    expr = expr_map.get(level, expr_map["category"])
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT COALESCE(SUM(gross_profit), 0) / NULLIF(COALESCE(SUM(sale_amount), 0), 0) * 100 AS margin_pct
            FROM t_htma_sale
            WHERE store_id = %s AND data_date BETWEEN %s AND %s AND ({expr}) = %s
            """,
            (store_id, start_date, end_date, category_name),
        )
        row = cur.fetchone() or {}
        return float(row.get("margin_pct") or 0)
    except Exception:
        return 0.0
    finally:
        try:
            cur.close()
        except Exception:
            pass
