# -*- coding: utf-8 -*-
# 阶段 A3 / D1：人力分析日期拆解、映射匹配、未映射大类检测（与 app._labor_analysis_* 口径一致）
from datetime import datetime
from calendar import monthrange


def labor_analysis_month_weights(start_date, end_date):
    """给定日期区间，返回涉及的月份及每个月的权重（该月在区间内天数/该月总天数）。"""
    if not start_date or not end_date:
        return []
    try:
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
    except Exception:
        return []
    if start_date > end_date:
        return []
    out = []
    cur = start_date
    while cur <= end_date:
        ym = cur.strftime("%Y-%m")
        month_start = cur.replace(day=1)
        _, last_day = monthrange(cur.year, cur.month)
        month_end = cur.replace(day=last_day)
        days_in_month = last_day
        range_start = max(month_start, start_date)
        range_end = min(month_end, end_date)
        days_in_range = (range_end - range_start).days + 1
        weight = days_in_range / days_in_month if days_in_month else 0
        if weight > 0:
            out.append((ym, round(weight, 6)))
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1, day=1)
        else:
            cur = cur.replace(month=cur.month + 1, day=1)
    return out


def labor_analysis_mapping_effective_for_month(conn, report_month):
    """返回在 report_month 当月生效的映射行。report_month='YYYY-MM'。"""
    try:
        y, m = report_month.split("-")[0], report_month.split("-")[1]
        month_start = "%s-%s-01" % (y, m)
        last = monthrange(int(y), int(m))[1]
        month_end = "%s-%s-%02d" % (y, m, last)
    except Exception:
        return []
    cur = conn.cursor()
    try:
        try:
            cur.execute("""
                SELECT id, sales_category, sales_category_mid, sales_category_large_code, sales_category_mid_code,
                       cost_type, labor_position_name, match_type, sort_order
                FROM t_htma_labor_category_mapping
                WHERE (effective_from IS NULL OR effective_from <= %s)
                  AND (effective_to IS NULL OR effective_to >= %s)
                ORDER BY cost_type, sort_order, id
            """, (month_end, month_start))
        except Exception:
            try:
                cur.execute("""
                    SELECT id, sales_category, sales_category_mid, cost_type, labor_position_name, match_type, sort_order
                    FROM t_htma_labor_category_mapping
                    WHERE (effective_from IS NULL OR effective_from <= %s)
                      AND (effective_to IS NULL OR effective_to >= %s)
                    ORDER BY cost_type, sort_order, id
                """, (month_end, month_start))
            except Exception:
                cur.execute("""
                    SELECT id, sales_category, cost_type, labor_position_name, match_type, sort_order
                    FROM t_htma_labor_category_mapping
                    WHERE (effective_from IS NULL OR effective_from <= %s)
                      AND (effective_to IS NULL OR effective_to >= %s)
                    ORDER BY cost_type, sort_order, id
                """, (month_end, month_start))
        rows = cur.fetchall()
        for r in rows:
            if r is None:
                continue
            if "sales_category_mid" not in r:
                r["sales_category_mid"] = ""
            if "sales_category_large_code" not in r:
                r["sales_category_large_code"] = ""
            if "sales_category_mid_code" not in r:
                r["sales_category_mid_code"] = ""
        return rows
    except Exception:
        return []
    finally:
        cur.close()


def labor_analysis_position_matches_mapping(position_name, labor_position_name, match_type):
    """判断 t_htma_labor_cost.position_name 是否匹配映射行的 labor_position_name。"""
    if not position_name:
        return False
    pos = (position_name or "").strip()
    lab = (labor_position_name or "").strip()
    if not lab:
        return False
    if (match_type or "").strip().lower() == "exact":
        return pos == lab
    return pos == lab or pos.startswith(lab) or lab in pos


def get_unmapped_categories(conn, start_date, end_date, store_id="沈阳超级仓"):
    """
    有大类销售但无任何「经营」映射且带岗位名的大类（与 _labor_analysis_by_category 中 cat_positions 为空一致）。
    返回 list of dict: category_large_code, category_large, total_sales
    """
    weights = labor_analysis_month_weights(start_date, end_date)
    if not weights:
        return []
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT COALESCE(NULLIF(TRIM(category_large_code), ''), TRIM(category_large)) AS code,
                   COALESCE(MAX(TRIM(category_large)), '') AS cat,
                   COALESCE(SUM(sale_amount), 0) AS s
            FROM t_htma_sale
            WHERE store_id = %s AND data_date BETWEEN %s AND %s
              AND (COALESCE(TRIM(category_large_code), '') != ''
                   OR (category_large IS NOT NULL AND TRIM(category_large) != ''))
            GROUP BY COALESCE(NULLIF(TRIM(category_large_code), ''), TRIM(category_large))
            ORDER BY s DESC
        """, (store_id, start_date, end_date))
        sales_rows = cur.fetchall() or []
    except Exception:
        sales_rows = []
    finally:
        try:
            cur.close()
        except Exception:
            pass

    mapped_keys = set()
    for ym, _ in weights:
        for m in labor_analysis_mapping_effective_for_month(conn, ym):
            if (m.get("cost_type") or "").strip().lower() != "operational":
                continue
            if not (m.get("labor_position_name") or "").strip():
                continue
            lc = (m.get("sales_category_large_code") or "").strip()
            cat_name = (m.get("sales_category") or "").strip()
            key = lc if lc else cat_name
            if key:
                mapped_keys.add(key)

    out = []
    for r in sales_rows:
        code = (r.get("code") or "").strip()
        cat = (r.get("cat") or "").strip()
        s = float(r.get("s") or 0)
        if s <= 0:
            continue
        has_map = (code in mapped_keys) or (cat in mapped_keys)
        if not has_map:
            out.append({
                "category_large_code": code,
                "category_large": cat or code,
                "total_sales": round(s, 2),
            })
    return out
