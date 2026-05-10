# -*- coding: utf-8 -*-
"""品类排行 API — serve_web/category_rank"""

from flask import Blueprint, jsonify, request

from core.db import get_conn
from core.context import (
    _effective_store_id, _query_filters, _profit_category_cond_and_params,
)

cat_rank_bp = Blueprint("category_rank", __name__)

@cat_rank_bp.route("/api/category_rank_mid", methods=["GET", "HEAD"])
def api_category_rank_mid():
    """品类排行-中类列表：按大类返回中类汇总（羽绒服、夹克等）。需传 category_large_code 或 category_large"""
    category_large_code = request.args.get("category_large_code", "").strip() or request.args.get("category_large", "").strip()
    if not category_large_code:
        return jsonify([])
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    large_cond = " AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)"
    params = (_effective_store_id(),) + date_params + profit_cat_params + (category_large_code, category_large_code)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(NULLIF(TRIM(category_mid), ''), '未分类') AS category_mid,
                       COALESCE(NULLIF(TRIM(category_mid_code), ''), NULLIF(TRIM(category_mid), ''), '') AS category_mid_code,
                       SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}{large_cond}
                  AND (COALESCE(TRIM(category_mid), '') != '' OR COALESCE(TRIM(category_mid_code), '') != '')
                GROUP BY category_mid, category_mid_code
                ORDER BY total_sale DESC
                LIMIT 100
            """, params)
            rows = cur.fetchall()
        out = []
        for i, r in enumerate(rows, 1):
            sale = float(r["total_sale"] or 0)
            profit = float(r["total_profit"] or 0)
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "rank": i,
                "category_mid": r.get("category_mid") or "未分类",
                "category_mid_code": r.get("category_mid_code") or "",
                "sale_amount": round(sale, 2),
                "profit_amount": round(profit, 2),
                "margin_pct": round(margin, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


@cat_rank_bp.route("/api/category_rank_small", methods=["GET", "HEAD"])
def api_category_rank_small():
    """品类排行-小类列表：按大类+中类返回小类明细。需传 category_large_code、category_mid_code 或 category_mid"""
    category_large_code = request.args.get("category_large_code", "").strip() or request.args.get("category_large", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip() or request.args.get("category_mid", "").strip()
    if not category_large_code:
        return jsonify([])
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    large_cond = " AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)"
    mid_cond = " AND (COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)" if category_mid_code else ""
    params = (_effective_store_id(),) + date_params + profit_cat_params + (category_large_code, category_large_code)
    if category_mid_code:
        params = params + (category_mid_code, category_mid_code)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(category, '未分类') AS category_small,
                       MAX(COALESCE(NULLIF(TRIM(category_small_code), ''), NULLIF(TRIM(category_code), ''), '')) AS category_small_code,
                       SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}{large_cond}{mid_cond}
                GROUP BY category
                ORDER BY total_sale DESC
                LIMIT 200
            """, params)
            rows = cur.fetchall()
        out = []
        for i, r in enumerate(rows, 1):
            sale = float(r["total_sale"] or 0)
            profit = float(r["total_profit"] or 0)
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "rank": i,
                "category_small": r.get("category_small") or r.get("category") or "未分类",
                "category_small_code": r.get("category_small_code") or "",
                "sale_amount": round(sale, 2),
                "profit_amount": round(profit, 2),
                "margin_pct": round(margin, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


@cat_rank_bp.route("/api/category_rank_brands", methods=["GET", "HEAD"])
def api_category_rank_brands():
    """品类排行-品牌列表：按大类+中类+小类返回品牌汇总。用于小类下钻到品牌。"""
    category_large_code = request.args.get("category_large_code", "").strip() or request.args.get("category_large", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip() or request.args.get("category_mid", "").strip()
    category_small_code = request.args.get("category_small_code", "").strip() or request.args.get("category_small", "").strip() or request.args.get("category", "").strip()
    if not category_large_code:
        return jsonify([])
    date_cond, date_params, _, category_cond, _ = _query_filters()
    params = list((_effective_store_id(),) + date_params)
    conds = [f" store_id = %s AND {date_cond} "]
    conds.append(" AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)")
    params.extend([category_large_code, category_large_code])
    if category_mid_code:
        conds.append(" AND (COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)")
        params.extend([category_mid_code, category_mid_code])
    if category_small_code:
        conds.append(" AND (COALESCE(TRIM(category_small_code), '') = %s OR COALESCE(TRIM(category_small), '') = %s OR COALESCE(TRIM(category), '') = %s)")
        params.extend([category_small_code, category_small_code, category_small_code])
    cat_cond = "".join(conds)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(NULLIF(TRIM(brand_name), ''), '未分类') AS brand,
                       SUM(sale_amount) AS total_sale, SUM(COALESCE(gross_profit, sale_amount - sale_cost, 0)) AS total_profit
                FROM t_htma_sale
                WHERE {cat_cond}
                GROUP BY brand
                ORDER BY total_sale DESC
                LIMIT 200
            """, tuple(params))
            rows = cur.fetchall()
        out = []
        for i, r in enumerate(rows, 1):
            sale = float(r["total_sale"] or 0)
            profit = float(r["total_profit"] or 0)
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "rank": i,
                "brand": r.get("brand") or "未分类",
                "sale_amount": round(sale, 2),
                "profit_amount": round(profit, 2),
                "margin_pct": round(margin, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


@cat_rank_bp.route("/api/category_rank_products", methods=["GET", "HEAD"])
def api_category_rank_products():
    """品类排行-商品列表：按大类+中类+小类+品牌返回 SKU 汇总。用于品牌下钻到商品。"""
    category_large_code = request.args.get("category_large_code", "").strip() or request.args.get("category_large", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip() or request.args.get("category_mid", "").strip()
    category_small_code = request.args.get("category_small_code", "").strip() or request.args.get("category_small", "").strip() or request.args.get("category", "").strip()
    brand = (request.args.get("brand") or "").strip()
    if not category_large_code or not brand:
        return jsonify([])
    date_cond, date_params, _, _, _ = _query_filters()
    params = list((_effective_store_id(),) + date_params)
    conds = [f" store_id = %s AND {date_cond} "]
    conds.append(" AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)")
    params.extend([category_large_code, category_large_code])
    if category_mid_code:
        conds.append(" AND (COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)")
        params.extend([category_mid_code, category_mid_code])
    if category_small_code:
        conds.append(" AND (COALESCE(TRIM(category_small_code), '') = %s OR COALESCE(TRIM(category_small), '') = %s OR COALESCE(TRIM(category), '') = %s)")
        params.extend([category_small_code, category_small_code, category_small_code])
    conds.append(" AND COALESCE(TRIM(brand_name), '') = %s")
    params.append(brand)
    cat_cond = "".join(conds)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT sku_code, COALESCE(MAX(product_name), '') AS product_name,
                       SUM(sale_amount) AS total_sale, SUM(COALESCE(gross_profit, sale_amount - sale_cost, 0)) AS total_profit
                FROM t_htma_sale
                WHERE {cat_cond}
                GROUP BY sku_code
                ORDER BY total_sale DESC
                LIMIT 200
            """, tuple(params))
            rows = cur.fetchall()
        out = []
        for i, r in enumerate(rows, 1):
            sale = float(r["total_sale"] or 0)
            profit = float(r["total_profit"] or 0)
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "rank": i,
                "sku_code": r.get("sku_code") or "",
                "product_name": (r.get("product_name") or "")[:64],
                "sale_amount": round(sale, 2),
                "profit_amount": round(profit, 2),
                "margin_pct": round(margin, 2),
            })
        return jsonify(out)
    finally:
        conn.close()



@cat_rank_bp.route("/api/category_rank_by_large")
def api_category_rank_by_large():
    """品类排行按大类汇总：大类名称、销售额、毛利、毛利率、贡献度。支持 start_date、end_date、category 及 hierarchy"""
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    params = (_effective_store_id(),) + date_params + profit_cat_params
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category_large_code), ''), '未分类') AS category_large,
                       COALESCE(NULLIF(TRIM(category_large_code), ''), NULLIF(TRIM(category_large), ''), '') AS category_large_code,
                       SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                  AND (COALESCE(TRIM(category_large), '') != '' OR COALESCE(TRIM(category_large_code), '') != '')
                GROUP BY category_large, category_large_code
                ORDER BY total_sale DESC
                LIMIT 50
            """, params)
            rows = cur.fetchall()
            cur.execute(f"""
                SELECT COALESCE(SUM(total_sale), 0) AS total_sale, COALESCE(SUM(total_profit), 0) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}
            """, params)
            tot = cur.fetchone()
        total_sale = float(tot["total_sale"] or 0)
        total_profit = float(tot["total_profit"] or 0)
        out = []
        for i, r in enumerate(rows, 1):
            sale = float(r["total_sale"] or 0)
            profit = float(r["total_profit"] or 0)
            contrib_sale = (sale / total_sale * 100) if total_sale > 0 else 0
            contrib_profit = (profit / total_profit * 100) if total_profit > 0 else 0
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "rank": i,
                "category_large": r["category_large"] or "未分类",
                "category_large_code": r.get("category_large_code") or "",
                "sale_amount": round(sale, 2),
                "profit_amount": round(profit, 2),
                "margin_pct": round(margin, 2),
                "sale_contrib_pct": round(contrib_sale, 2),
                "profit_contrib_pct": round(contrib_profit, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


