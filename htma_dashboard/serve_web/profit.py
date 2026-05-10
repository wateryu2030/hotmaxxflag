# -*- coding: utf-8 -*-
"""经营分析 API — serve_web/profit：利润、库存、品牌、供应商、价格带、SKU 周转等"""

from flask import Blueprint, jsonify, request
from datetime import date, datetime, timedelta

from core.db import get_conn
from core.context import (
    _effective_store_id, _query_filters, _profit_category_cond_and_params,
    _inv_category_cond_and_params, period_over_period_ranges,
)
from core.cache import _cache_get, _cache_set
from core.utils import safe_int, safe_float, safe_str

profit_bp = Blueprint("profit", __name__)

@profit_bp.route("/api/profit_summary")
def api_profit_summary():
    """品类汇总：按时间段合并，大类/中类/小类、销售额、毛利、毛利率。支持 period、start_date、end_date、category 及 hierarchy"""
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    params = (_effective_store_id(),) + date_params + profit_cat_params
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(category, '未分类') AS category,
                       MAX(COALESCE(category_large, '')) AS category_large,
                       MAX(COALESCE(category_mid, '')) AS category_mid,
                       MAX(COALESCE(category_small, '')) AS category_small,
                       SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                GROUP BY category
                ORDER BY total_sale DESC
            """, params)
            rows = cur.fetchall()
        return jsonify([{
            "category": r["category"] or "未分类",
            "category_large": r.get("category_large") or "",
            "category_mid": r.get("category_mid") or "",
            "category_small": r.get("category_small") or "",
            "total_sale": round(float(r["total_sale"] or 0), 2),
            "total_profit": round(float(r["total_profit"] or 0), 2),
            "profit_rate": round((float(r["total_profit"] or 0) / float(r["total_sale"] or 1) * 100), 2) if r["total_sale"] else 0,
        } for r in rows])
    finally:
        conn.close()


@profit_bp.route("/api/sale_summary")
def api_sale_summary():
    """商品汇总：按时间段合并，SKU、品名、品类、销量、销售额、成本、毛利、毛利率。支持 period、start_date、end_date、category、page、page_size"""
    date_cond, _, params, category_cond, sku_cond = _query_filters(include_sku=True)
    page = max(1, int(request.args.get("page", "1")))
    page_size = min(200, max(10, int(request.args.get("page_size", "50"))))
    offset = (page - 1) * page_size
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COUNT(DISTINCT sku_code) AS total FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
            """, params)
            total = cur.fetchone()["total"] or 0
            cur.execute(f"""
                SELECT sku_code,
                       MAX(COALESCE(product_name, '')) AS product_name,
                       MAX(COALESCE(category, '未分类')) AS category,
                       MAX(COALESCE(category_large, '')) AS category_large,
                       MAX(COALESCE(category_mid, '')) AS category_mid,
                       MAX(COALESCE(category_small, '')) AS category_small,
                       SUM(sale_qty) AS sale_qty, SUM(sale_amount) AS sale_amount,
                       SUM(sale_cost) AS sale_cost, SUM(gross_profit) AS gross_profit
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                GROUP BY sku_code
                ORDER BY sale_amount DESC
                LIMIT %s OFFSET %s
            """, (*params, page_size, offset))
            rows = cur.fetchall()
        return jsonify({
            "items": [{
                "sku_code": r["sku_code"],
                "product_name": r.get("product_name") or "",
                "category": r["category"] or "未分类",
                "category_large": r.get("category_large") or "",
                "category_mid": r.get("category_mid") or "",
                "category_small": r.get("category_small") or "",
                "sale_qty": float(r["sale_qty"] or 0),
                "sale_amount": round(float(r["sale_amount"] or 0), 2),
                "sale_cost": round(float(r["sale_cost"] or 0), 2),
                "gross_profit": round(float(r["gross_profit"] or 0), 2),
                "profit_rate_pct": round((float(r["gross_profit"] or 0) / float(r["sale_amount"] or 1) * 100), 2) if r["sale_amount"] else 0,
            } for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    finally:
        conn.close()


@profit_bp.route("/api/profit_detail")
def api_profit_detail():
    """毛利明细表：日期、品类、销售额、毛利、毛利率。支持 period、start_date、end_date、category 及 hierarchy、expand_category（展开某品类时传）、page、page_size"""
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    expand_category = request.args.get("expand_category", "").strip()
    expand_cond = " AND COALESCE(category, '未分类') = %s" if expand_category else ""
    expand_params = (expand_category,) if expand_category else ()
    params = (_effective_store_id(),) + date_params + profit_cat_params + expand_params
    page = max(1, int(request.args.get("page", "1")))
    page_size = min(200, max(10, int(request.args.get("page_size", "50"))))
    offset = (page - 1) * page_size
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COUNT(*) AS total FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}{expand_cond}
            """, params)
            total = cur.fetchone()["total"] or 0
            cur.execute(f"""
                SELECT data_date, category, total_sale, total_profit, profit_rate, store_id,
                       COALESCE(category_large, '') AS category_large, COALESCE(category_mid, '') AS category_mid, COALESCE(category_small, '') AS category_small
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}{expand_cond}
                ORDER BY data_date DESC, total_sale DESC
                LIMIT %s OFFSET %s
            """, (*params, page_size, offset))
            rows = cur.fetchall()
        return jsonify({
            "items": [{
            "data_date": r["data_date"].strftime("%Y-%m-%d") if hasattr(r["data_date"], "strftime") else str(r["data_date"]),
            "category": r["category"] or "未分类",
            "category_large": r.get("category_large") or "",
            "category_mid": r.get("category_mid") or "",
            "category_small": r.get("category_small") or "",
            "total_sale": float(r["total_sale"] or 0),
            "total_profit": float(r["total_profit"] or 0),
            "profit_rate": float(r["profit_rate"] or 0) * 100 if r["profit_rate"] else 0,
            "store_id": r["store_id"],
        } for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    finally:
        conn.close()


@profit_bp.route("/api/inv_alert_list")
def api_inv_alert_list():
    """低库存明细：SKU、品类、库存数量、库存金额。支持 page、page_size、category_large/mid/small"""
    sid = _effective_store_id()
    inv_cond, inv_params, need_join = _inv_category_cond_and_params()
    page = max(1, int(request.args.get("page", "1")))
    page_size = min(100, max(10, int(request.args.get("page_size", "50"))))
    offset = (page - 1) * page_size
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if need_join:
                cur.execute(f"""
                    SELECT COUNT(*) AS total
                    FROM t_htma_stock st
                    INNER JOIN (
                        SELECT sku_code,
                               MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                               MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                               MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                        FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                    ) s ON st.sku_code = s.sku_code
                    WHERE st.store_id = %s AND st.data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND st.stock_qty < 50 AND st.stock_qty >= 0 AND (st.stock_qty != 0 OR st.stock_amount != 0) {inv_cond}
                """, (sid, sid, sid) + inv_params)
                total = cur.fetchone()["total"] or 0
                cur.execute(f"""
                    SELECT st.sku_code, COALESCE(st.category, s.category, '') AS category,
                           COALESCE(st.product_name, '') AS product_name, st.stock_qty, st.stock_amount, st.data_date
                    FROM t_htma_stock st
                    INNER JOIN (
                        SELECT sku_code,
                               MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                               MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                               MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                        FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                    ) s ON st.sku_code = s.sku_code
                    WHERE st.store_id = %s AND st.data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND st.stock_qty < 50 AND st.stock_qty >= 0 AND (st.stock_qty != 0 OR st.stock_amount != 0) {inv_cond}
                    ORDER BY st.stock_qty ASC
                    LIMIT %s OFFSET %s
                """, (sid, sid, sid) + inv_params + (page_size, offset))
            else:
                cur.execute("""
                    SELECT COUNT(*) AS total FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND stock_qty < 50 AND stock_qty >= 0 AND (stock_qty != 0 OR stock_amount != 0)
                """, (sid, sid))
                total = cur.fetchone()["total"] or 0
                cur.execute("""
                    SELECT sku_code, category, COALESCE(product_name, '') AS product_name, stock_qty, stock_amount, data_date
                    FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND stock_qty < 50 AND stock_qty >= 0 AND (stock_qty != 0 OR stock_amount != 0)
                    ORDER BY stock_qty ASC
                    LIMIT %s OFFSET %s
                """, (sid, sid, page_size, offset))
            rows = cur.fetchall()
        return jsonify({
            "items": [{
                "sku_code": r["sku_code"],
                "category": r["category"] or "未分类",
                "product_name": r.get("product_name") or "",
                "stock_qty": float(r["stock_qty"] or 0),
                "stock_amount": float(r["stock_amount"] or 0),
                "data_date": r["data_date"].strftime("%Y-%m-%d") if hasattr(r["data_date"], "strftime") else str(r["data_date"]),
            } for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    finally:
        conn.close()


@profit_bp.route("/api/data_status")
def api_data_status():
    """数据状态：用于实时展示导入数据概况"""
    sid = _effective_store_id()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM t_htma_sale WHERE store_id = %s", (sid,))
            sale_cnt = cur.fetchone()["cnt"] or 0
            cur.execute("SELECT COUNT(*) AS cnt FROM t_htma_stock WHERE store_id = %s", (sid,))
            stock_cnt = cur.fetchone()["cnt"] or 0
            cur.execute("SELECT COUNT(*) AS cnt FROM t_htma_profit WHERE store_id = %s", (sid,))
            profit_cnt = cur.fetchone()["cnt"] or 0
            cur.execute("SELECT MIN(data_date) AS min_d, MAX(data_date) AS max_d FROM t_htma_sale WHERE store_id = %s", (sid,))
            dr = cur.fetchone()
            min_d = dr["min_d"]
            max_d = dr["max_d"]
        return jsonify({
            "sale_count": sale_cnt,
            "stock_count": stock_cnt,
            "profit_count": profit_cnt,
            "min_date": min_d.strftime("%Y-%m-%d") if min_d and hasattr(min_d, "strftime") else None,
            "max_date": max_d.strftime("%Y-%m-%d") if max_d and hasattr(max_d, "strftime") else None,
            "store_id": sid,
        })
    finally:
        conn.close()


# ---------- 经营性分析 API（见 docs/现有数据还能做哪些经营性分析.md） ----------

@profit_bp.route("/api/return_gift_summary")
def api_return_gift_summary():
    """退货与赠送汇总：退货/赠送金额与件数占比，支持 period/start_date/end_date"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(SUM(sale_amount), 0) AS total_sale, COALESCE(SUM(sale_qty), 0) AS total_qty,
                       COALESCE(SUM(return_amount), 0) AS return_amt, COALESCE(SUM(return_qty), 0) AS return_qty,
                       COALESCE(SUM(gift_amount), 0) AS gift_amt, COALESCE(SUM(gift_qty), 0) AS gift_qty
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond}
            """, params)
            row = cur.fetchone()
        total_sale = float(row["total_sale"] or 0)
        total_qty = float(row["total_qty"] or 0)
        return_amt = float(row["return_amt"] or 0)
        return_qty = float(row["return_qty"] or 0)
        gift_amt = float(row["gift_amt"] or 0)
        gift_qty = float(row["gift_qty"] or 0)
        return_ratio_amt = (return_amt / total_sale * 100) if total_sale > 0 else 0
        return_ratio_qty = (return_qty / total_qty * 100) if total_qty > 0 else 0
        gift_ratio_amt = (gift_amt / total_sale * 100) if total_sale > 0 else 0
        gift_ratio_qty = (gift_qty / total_qty * 100) if total_qty > 0 else 0
        return jsonify({
            "total_sale_amount": round(total_sale, 2),
            "total_sale_qty": round(total_qty, 2),
            "return_amount": round(return_amt, 2),
            "return_qty": round(return_qty, 2),
            "gift_amount": round(gift_amt, 2),
            "gift_qty": round(gift_qty, 2),
            "return_ratio_amt_pct": round(return_ratio_amt, 2),
            "return_ratio_qty_pct": round(return_ratio_qty, 2),
            "gift_ratio_amt_pct": round(gift_ratio_amt, 2),
            "gift_ratio_qty_pct": round(gift_ratio_qty, 2),
            "data_hint": "无数据时请检查：1) 是否已导入销售日报/销售汇总 Excel；2) 所选周期是否覆盖数据日期。可用 /api/data_status 查看库内数据范围。" if total_sale == 0 else None,
        })
    finally:
        conn.close()


@profit_bp.route("/api/brand_summary")
def api_brand_summary():
    """品牌贡献：按品牌汇总销售额、毛利、销量、毛利率、贡献占比。支持 period/start_date/end_date"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(NULLIF(TRIM(brand_name), ''), '未填') AS brand_name,
                       SUM(sale_amount) AS sale_amount, SUM(gross_profit) AS profit, SUM(sale_qty) AS qty
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond}
                GROUP BY brand_name
                HAVING SUM(sale_amount) > 0
                ORDER BY SUM(sale_amount) DESC
                LIMIT 50
            """, params)
            rows = cur.fetchall()
            cur.execute(f"""
                SELECT COALESCE(SUM(sale_amount), 0) AS total_sale, COALESCE(SUM(gross_profit), 0) AS total_profit
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond}
            """, params)
            tot = cur.fetchone()
        total_sale = float(tot["total_sale"] or 0)
        total_profit = float(tot["total_profit"] or 0)
        out = []
        for r in rows:
            sale = float(r["sale_amount"] or 0)
            profit = float(r["profit"] or 0)
            contrib = (sale / total_sale * 100) if total_sale > 0 else 0
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "brand_name": r["brand_name"] or "未填",
                "sale_amount": round(sale, 2),
                "profit": round(profit, 2),
                "qty": round(float(r["qty"] or 0), 2),
                "margin_pct": round(margin, 2),
                "contrib_pct": round(contrib, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


@profit_bp.route("/api/brand_categories", methods=["GET", "HEAD"])
def api_brand_categories():
    """经营分析-品牌下钻：按品牌返回涉及的大类/中类/小类及销售额、毛利。用于品牌行展开后展示品类明细。"""
    brand = (request.args.get("brand") or request.args.get("brand_name") or "").strip()
    if not brand:
        return jsonify([])
    try:
        date_cond, _, params, category_cond, _ = _query_filters()
        params = list(params)
        brand_cond = " AND TRIM(COALESCE(brand_name, '')) = %s"
        params.append(brand)
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT
                        COALESCE(NULLIF(TRIM(category_large), ''), '未分类') AS category_large,
                        COALESCE(NULLIF(TRIM(category_large_code), ''), NULLIF(TRIM(category_large), ''), '') AS category_large_code,
                        COALESCE(NULLIF(TRIM(category_mid), ''), '未分类') AS category_mid,
                        COALESCE(NULLIF(TRIM(category_mid_code), ''), NULLIF(TRIM(category_mid), ''), '') AS category_mid_code,
                        COALESCE(NULLIF(TRIM(category_small), ''), NULLIF(TRIM(category), ''), '未分类') AS category_small,
                        COALESCE(NULLIF(TRIM(category_small_code), ''), NULLIF(TRIM(category_small), ''), NULLIF(TRIM(category), ''), '') AS category_small_code,
                        SUM(sale_amount) AS sale_amount,
                        SUM(COALESCE(gross_profit, sale_amount - sale_cost, 0)) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{brand_cond}
                    GROUP BY category_large, category_large_code, category_mid, category_mid_code, category_small, category_small_code
                    ORDER BY sale_amount DESC
                    LIMIT 200
                """, tuple(params))
                rows = cur.fetchall()
            out = []
            for i, r in enumerate(rows, 1):
                sale = float(r["sale_amount"] or 0)
                profit = float(r["profit_amount"] or 0)
                margin = (profit / sale * 100) if sale > 0 else 0
                out.append({
                    "rank": i,
                    "category_large": r.get("category_large") or "未分类",
                    "category_large_code": r.get("category_large_code") or "",
                    "category_mid": r.get("category_mid") or "未分类",
                    "category_mid_code": r.get("category_mid_code") or "",
                    "category_small": r.get("category_small") or "未分类",
                    "category_small_code": r.get("category_small_code") or "",
                    "sale_amount": round(sale, 2),
                    "profit_amount": round(profit, 2),
                    "margin_pct": round(margin, 2),
                })
            return jsonify(out)
        finally:
            conn.close()
    except Exception:
        return jsonify([])


@profit_bp.route("/api/supplier_summary")
def api_supplier_summary():
    """供应商贡献：按供应商汇总销售额、毛利、销量、毛利率、贡献占比"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(NULLIF(TRIM(supplier_name), ''), '未填') AS supplier_name,
                       SUM(sale_amount) AS sale_amount, SUM(gross_profit) AS profit, SUM(sale_qty) AS qty
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond}
                GROUP BY supplier_name
                HAVING SUM(sale_amount) > 0
                ORDER BY SUM(sale_amount) DESC
                LIMIT 50
            """, params)
            rows = cur.fetchall()
            cur.execute(f"""
                SELECT COALESCE(SUM(sale_amount), 0) AS total_sale, COALESCE(SUM(gross_profit), 0) AS total_profit
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond}
            """, params)
            tot = cur.fetchone()
        total_sale = float(tot["total_sale"] or 0)
        total_profit = float(tot["total_profit"] or 0)
        out = []
        for r in rows:
            sale = float(r["sale_amount"] or 0)
            profit = float(r["profit"] or 0)
            contrib = (sale / total_sale * 100) if total_sale > 0 else 0
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "supplier_name": r["supplier_name"] or "未填",
                "sale_amount": round(sale, 2),
                "profit": round(profit, 2),
                "qty": round(float(r["qty"] or 0), 2),
                "margin_pct": round(margin, 2),
                "contrib_pct": round(contrib, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


@profit_bp.route("/api/supplier_categories", methods=["GET", "HEAD"])
def api_supplier_categories():
    """经营分析-供应商下钻：按供应商返回供应的品类（大类/中类/小类）及销售额、毛利。"""
    supplier = (request.args.get("supplier") or request.args.get("supplier_name") or "").strip()
    if not supplier:
        return jsonify([])
    try:
        date_cond, _, params, category_cond, _ = _query_filters()
        params = list(params)
        supplier_cond = " AND TRIM(COALESCE(supplier_name, '')) = %s"
        params.append(supplier)
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT
                        COALESCE(NULLIF(TRIM(category_large), ''), '未分类') AS category_large,
                        COALESCE(NULLIF(TRIM(category_large_code), ''), NULLIF(TRIM(category_large), ''), '') AS category_large_code,
                        COALESCE(NULLIF(TRIM(category_mid), ''), '未分类') AS category_mid,
                        COALESCE(NULLIF(TRIM(category_mid_code), ''), NULLIF(TRIM(category_mid), ''), '') AS category_mid_code,
                        COALESCE(NULLIF(TRIM(category_small), ''), NULLIF(TRIM(category), ''), '未分类') AS category_small,
                        COALESCE(NULLIF(TRIM(category_small_code), ''), NULLIF(TRIM(category_small), ''), NULLIF(TRIM(category), ''), '') AS category_small_code,
                        SUM(sale_amount) AS sale_amount,
                        SUM(COALESCE(gross_profit, sale_amount - sale_cost, 0)) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{supplier_cond}
                    GROUP BY category_large, category_large_code, category_mid, category_mid_code, category_small, category_small_code
                    ORDER BY sale_amount DESC
                    LIMIT 200
                """, tuple(params))
                rows = cur.fetchall()
            out = []
            for i, r in enumerate(rows, 1):
                sale = float(r["sale_amount"] or 0)
                profit = float(r["profit_amount"] or 0)
                margin = (profit / sale * 100) if sale > 0 else 0
                out.append({
                    "rank": i,
                    "category_large": r.get("category_large") or "未分类",
                    "category_large_code": r.get("category_large_code") or "",
                    "category_mid": r.get("category_mid") or "未分类",
                    "category_mid_code": r.get("category_mid_code") or "",
                    "category_small": r.get("category_small") or "未分类",
                    "category_small_code": r.get("category_small_code") or "",
                    "sale_amount": round(sale, 2),
                    "profit_amount": round(profit, 2),
                    "margin_pct": round(margin, 2),
                })
            return jsonify(out)
        finally:
            conn.close()
    except Exception:
        return jsonify([])


@profit_bp.route("/api/supplier_products", methods=["GET", "HEAD"])
def api_supplier_products():
    """经营分析-供应商下钻：按供应商+品类（大类/中类/小类）返回商品汇总。用于品类行展开后展示商品。"""
    supplier = (request.args.get("supplier") or request.args.get("supplier_name") or "").strip()
    category_large_code = request.args.get("category_large_code", "").strip() or request.args.get("category_large", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip() or request.args.get("category_mid", "").strip()
    category_small_code = request.args.get("category_small_code", "").strip() or request.args.get("category_small", "").strip() or request.args.get("category", "").strip()
    if not supplier:
        return jsonify([])
    date_cond, date_params, _, _, _ = _query_filters()
    params = list((_effective_store_id(),) + date_params)
    supplier_cond = " AND TRIM(COALESCE(supplier_name, '')) = %s"
    params.append(supplier)
    conds = [f" store_id = %s AND {date_cond}{supplier_cond} "]
    if category_large_code:
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


@profit_bp.route("/api/price_band_summary")
def api_price_band_summary():
    """价格带分布：按件单价分段（0-10/10-30/30-50/50-100/100+）的销售额、销量、消费笔数及占比"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT
                    CASE
                        WHEN COALESCE(sale_qty, 0) <= 0 THEN '0'
                        WHEN (sale_amount / sale_qty) < 10 THEN '0-10'
                        WHEN (sale_amount / sale_qty) < 30 THEN '10-30'
                        WHEN (sale_amount / sale_qty) < 50 THEN '30-50'
                        WHEN (sale_amount / sale_qty) < 100 THEN '50-100'
                        ELSE '100+'
                    END AS band,
                    SUM(sale_amount) AS sale_amount,
                    SUM(sale_qty) AS qty,
                    COUNT(*) AS record_count
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond} AND sale_qty > 0 AND sale_amount > 0
                GROUP BY band
            """, params)
            rows = cur.fetchall()
            cur.execute(f"""
                SELECT COALESCE(SUM(sale_amount), 0) AS total_sale,
                       COALESCE(SUM(sale_qty), 0) AS total_qty,
                       COUNT(*) AS total_records
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond} AND sale_qty > 0 AND sale_amount > 0
            """, params)
            tot = cur.fetchone()
        total_sale = float(tot["total_sale"] or 0)
        total_qty = float(tot["total_qty"] or 0)
        total_records = int(tot["total_records"] or 0)
        band_order = ["0", "0-10", "10-30", "30-50", "50-100", "100+"]
        out = []
        for r in rows:
            band = r["band"] or "0"
            sale = float(r["sale_amount"] or 0)
            qty = float(r["qty"] or 0)
            record_count = int(r["record_count"] or 0)
            out.append({
                "band": band,
                "sale_amount": round(sale, 2),
                "qty": round(qty, 2),
                "record_count": record_count,
                "sale_contrib_pct": round((sale / total_sale * 100), 2) if total_sale > 0 else 0,
                "qty_contrib_pct": round((qty / total_qty * 100), 2) if total_qty > 0 else 0,
                "record_contrib_pct": round((record_count / total_records * 100), 2) if total_records > 0 else 0,
            })
        out.sort(key=lambda x: (band_order.index(x["band"]) if x["band"] in band_order else 99, x["band"]))
        return jsonify(out)
    finally:
        conn.close()


def _price_band_unit_cond(band):
    """根据价格带返回 SQL 条件：件单价 (sale_amount/sale_qty) 落在该区间。返回 (cond_sql,)."""
    band = (band or "").strip()
    if band == "0":
        return (" AND COALESCE(sale_qty, 0) <= 0 ",)
    if band == "0-10":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) < 10 ",)
    if band == "10-30":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) >= 10 AND (sale_amount / sale_qty) < 30 ",)
    if band == "30-50":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) >= 30 AND (sale_amount / sale_qty) < 50 ",)
    if band == "50-100":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) >= 50 AND (sale_amount / sale_qty) < 100 ",)
    if band == "100+":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) >= 100 ",)
    return (" AND 1=0 ",)


@profit_bp.route("/api/price_band_categories", methods=["GET", "HEAD"])
def api_price_band_categories():
    """经营分析-价格带下钻：按价格带返回涉及的品类（大类/中类/小类）及销售额、毛利。"""
    band = (request.args.get("band") or "").strip()
    if not band:
        return jsonify([])
    try:
        unit_cond = _price_band_unit_cond(band)
        date_cond, _, params, category_cond, _ = _query_filters()
        params = tuple(params)
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT
                        COALESCE(NULLIF(TRIM(category_large), ''), '未分类') AS category_large,
                        COALESCE(NULLIF(TRIM(category_large_code), ''), NULLIF(TRIM(category_large), ''), '') AS category_large_code,
                        COALESCE(NULLIF(TRIM(category_mid), ''), '未分类') AS category_mid,
                        COALESCE(NULLIF(TRIM(category_mid_code), ''), NULLIF(TRIM(category_mid), ''), '') AS category_mid_code,
                        COALESCE(NULLIF(TRIM(category_small), ''), NULLIF(TRIM(category), ''), '未分类') AS category_small,
                        COALESCE(NULLIF(TRIM(category_small_code), ''), NULLIF(TRIM(category_small), ''), NULLIF(TRIM(category), ''), '') AS category_small_code,
                        SUM(sale_amount) AS sale_amount,
                        SUM(COALESCE(gross_profit, sale_amount - sale_cost, 0)) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{unit_cond[0]}
                    GROUP BY category_large, category_large_code, category_mid, category_mid_code, category_small, category_small_code
                    ORDER BY sale_amount DESC
                    LIMIT 200
                """, params)
                rows = cur.fetchall()
            out = []
            for i, r in enumerate(rows, 1):
                sale = float(r["sale_amount"] or 0)
                profit = float(r["profit_amount"] or 0)
                margin = (profit / sale * 100) if sale > 0 else 0
                out.append({
                    "rank": i,
                    "category_large": r.get("category_large") or "未分类",
                    "category_large_code": r.get("category_large_code") or "",
                    "category_mid": r.get("category_mid") or "未分类",
                    "category_mid_code": r.get("category_mid_code") or "",
                    "category_small": r.get("category_small") or "未分类",
                    "category_small_code": r.get("category_small_code") or "",
                    "sale_amount": round(sale, 2),
                    "profit_amount": round(profit, 2),
                    "margin_pct": round(margin, 2),
                })
            return jsonify(out)
        finally:
            conn.close()
    except Exception:
        return jsonify([])


@profit_bp.route("/api/price_band_products", methods=["GET", "HEAD"])
def api_price_band_products():
    """经营分析-价格带下钻：按价格带+品类返回商品汇总。用于品类行展开后展示商品。"""
    band = (request.args.get("band") or "").strip()
    category_large_code = request.args.get("category_large_code", "").strip() or request.args.get("category_large", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip() or request.args.get("category_mid", "").strip()
    category_small_code = request.args.get("category_small_code", "").strip() or request.args.get("category_small", "").strip() or request.args.get("category", "").strip()
    unit_cond = _price_band_unit_cond(band)
    date_cond, date_params, _, _, _ = _query_filters()
    params = list((_effective_store_id(),) + date_params)
    conds = [f" store_id = %s AND {date_cond}{unit_cond[0]} "]
    if category_large_code:
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


@profit_bp.route("/api/sku_turnover")
def api_sku_turnover():
    """SKU 周转：近 N 天销量、最新库存、周转天数（库存/日均销量）。limit 默认 100"""
    date_cond, _, params, category_cond, _ = _query_filters()
    limit = min(int(request.args.get("limit", 100)), 500)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT s.sku_code,
                       COALESCE(st.product_name, s.product_name, s.sku_code) AS product_name,
                       s.category,
                       SUM(s.sale_qty) AS sale_qty,
                       SUM(s.sale_amount) AS sale_amount,
                       COALESCE(st.stock_qty, 0) AS stock_qty
                FROM t_htma_sale s
                LEFT JOIN (
                    SELECT sku_code, stock_qty, product_name
                    FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
                ) st ON st.sku_code = s.sku_code
                WHERE s.store_id = %s AND {date_cond}{category_cond}
                GROUP BY s.sku_code, st.product_name, s.product_name, s.category, st.stock_qty
                HAVING SUM(s.sale_qty) > 0
                ORDER BY SUM(s.sale_qty) DESC
                LIMIT %s
            """, (params[0], params[0]) + tuple(params) + (limit,))
            rows = cur.fetchall()
        days = 30
        if request.args.get("start_date") and request.args.get("end_date"):
            try:
                from datetime import datetime
                e = datetime.strptime(request.args.get("end_date"), "%Y-%m-%d").date()
                s = datetime.strptime(request.args.get("start_date"), "%Y-%m-%d").date()
                days = max(1, (e - s).days + 1)
            except Exception:
                pass
        elif request.args.get("period") == "week":
            days = 7
        elif request.args.get("period") == "month":
            days = 31
        out = []
        for r in rows:
            sale_qty = float(r["sale_qty"] or 0)
            stock_qty = float(r["stock_qty"] or 0)
            daily_sale = sale_qty / days if days > 0 else 0
            turnover_days = (stock_qty / daily_sale) if daily_sale > 0 else (9999 if stock_qty > 0 else 0)
            out.append({
                "sku_code": r["sku_code"],
                "product_name": (r["product_name"] or r["sku_code"])[:64],
                "category": (r["category"] or "")[:32],
                "sale_qty": round(sale_qty, 2),
                "sale_amount": round(float(r["sale_amount"] or 0), 2),
                "stock_qty": round(stock_qty, 2),
                "turnover_days": round(turnover_days, 1) if turnover_days < 9999 else None,
            })
        return jsonify(out)
    finally:
        conn.close()


@profit_bp.route("/api/sku_abc")
def api_sku_abc():
    """SKU ABC 分类：按销售额累计占比 A(前80%)/B(80-95%)/C(其余)。返回每类数量及明细（可 limit）"""
    date_cond, _, params, category_cond, _ = _query_filters()
    limit = min(int(request.args.get("limit", 200)), 500)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT s.sku_code,
                       COALESCE(st.product_name, s.product_name, s.sku_code) AS product_name,
                       s.category,
                       SUM(s.sale_amount) AS sale_amount,
                       SUM(s.gross_profit) AS profit
                FROM t_htma_sale s
                LEFT JOIN (
                    SELECT sku_code, product_name FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
                ) st ON st.sku_code = s.sku_code
                WHERE s.store_id = %s AND {date_cond}{category_cond}
                GROUP BY s.sku_code, st.product_name, s.product_name, s.category
                HAVING SUM(s.sale_amount) > 0
                ORDER BY SUM(s.sale_amount) DESC
            """, (params[0], params[0]) + tuple(params))
            rows = cur.fetchall()
        total_sale = sum(float(r["sale_amount"] or 0) for r in rows)
        cum = 0
        out = []
        a_cnt, b_cnt, c_cnt = 0, 0, 0
        for i, r in enumerate(rows):
            sale = float(r["sale_amount"] or 0)
            cum += sale
            pct = (cum / total_sale * 100) if total_sale > 0 else 0
            if pct <= 80:
                cls = "A"
                a_cnt += 1
            elif pct <= 95:
                cls = "B"
                b_cnt += 1
            else:
                cls = "C"
                c_cnt += 1
            if len(out) < limit:
                out.append({
                    "sku_code": r["sku_code"],
                    "product_name": (r["product_name"] or r["sku_code"])[:64],
                    "category": (r["category"] or "")[:32],
                    "sale_amount": round(sale, 2),
                    "profit": round(float(r["profit"] or 0), 2),
                    "cum_contrib_pct": round(pct, 2),
                    "abc_class": cls,
                })
        return jsonify({
            "summary": {"A_count": a_cnt, "B_count": b_cnt, "C_count": c_cnt, "total_sale": round(total_sale, 2)},
            "items": out,
        })
    finally:
        conn.close()


@profit_bp.route("/api/negative_margin_detail")
def api_negative_margin_detail():
    """负毛利明细：销售额>0 且毛利<0 的 SKU 列表。format=csv 时返回 CSV 下载"""
    date_cond, _, params, category_cond, _ = _query_filters()
    limit = min(int(request.args.get("limit", 200)), 1000)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT s.sku_code,
                       COALESCE(st.product_name, s.product_name, s.sku_code) AS product_name,
                       s.category,
                       SUM(s.sale_qty) AS qty,
                       SUM(s.sale_amount) AS sale_amount,
                       SUM(s.sale_cost) AS cost,
                       SUM(s.gross_profit) AS profit
                FROM t_htma_sale s
                LEFT JOIN (
                    SELECT sku_code, product_name FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
                ) st ON st.sku_code = s.sku_code
                WHERE s.store_id = %s AND {date_cond}{category_cond}
                GROUP BY s.sku_code, st.product_name, s.product_name, s.category
                HAVING SUM(s.sale_amount) > 0 AND SUM(s.gross_profit) < 0
                ORDER BY SUM(s.gross_profit) ASC
                LIMIT %s
            """, (params[0], params[0]) + tuple(params) + (limit,))
            rows = cur.fetchall()
        out = []
        for r in rows:
            sale = float(r["sale_amount"] or 0)
            profit = float(r["profit"] or 0)
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "sku_code": r["sku_code"],
                "product_name": (r["product_name"] or r["sku_code"])[:64],
                "category": (r["category"] or "")[:32],
                "qty": round(float(r["qty"] or 0), 2),
                "sale_amount": round(sale, 2),
                "cost": round(float(r["cost"] or 0), 2),
                "profit": round(profit, 2),
                "margin_pct": round(margin, 2),
            })
        if request.args.get("format") == "csv":
            import io
            import csv
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["商品编码", "品名", "品类", "销量", "销售额", "成本", "毛利", "毛利率%"])
            for row in out:
                writer.writerow([
                    row["sku_code"], row["product_name"], row["category"],
                    row["qty"], row["sale_amount"], row["cost"], row["profit"], row["margin_pct"],
                ])
            return Response(buf.getvalue(), mimetype="text/csv; charset=utf-8-sig",
                           headers={"Content-Disposition": "attachment; filename=negative_margin_detail.csv"})
        return jsonify(out)
    finally:
        conn.close()


@profit_bp.route("/api/category_structure_trend")
def api_category_structure_trend():
    """品类结构趋势：按周或月汇总各品类销售额、毛利及占比。granularity=week|month，默认 week"""
    granularity = request.args.get("granularity", "week")
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if granularity == "month":
                cur.execute(f"""
                    SELECT DATE_FORMAT(data_date, '%%Y-%%m') AS period,
                           COALESCE(category, '未分类') AS category,
                           SUM(sale_amount) AS sale_amount,
                           SUM(COALESCE(gross_profit, sale_amount - sale_cost, 0)) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}
                    GROUP BY DATE_FORMAT(data_date, '%%Y-%%m'), COALESCE(category, '未分类')
                    ORDER BY period, sale_amount DESC
                """, params)
            else:
                cur.execute(f"""
                    SELECT CONCAT(YEAR(data_date), '-W', LPAD(WEEK(data_date, 3), 2, '0')) AS period,
                           COALESCE(category, '未分类') AS category,
                           SUM(sale_amount) AS sale_amount,
                           SUM(COALESCE(gross_profit, sale_amount - sale_cost, 0)) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}
                    GROUP BY CONCAT(YEAR(data_date), '-W', LPAD(WEEK(data_date, 3), 2, '0')), COALESCE(category, '未分类')
                    ORDER BY period, sale_amount DESC
                """, params)
            rows = cur.fetchall()
        from collections import defaultdict
        period_totals = defaultdict(float)
        period_profit_totals = defaultdict(float)
        period_cats = defaultdict(list)
        for r in rows:
            period = r["period"] or ""
            cat = r["category"] or "未分类"
            amt = float(r["sale_amount"] or 0)
            profit = float(r["profit_amount"] or 0)
            period_totals[period] += amt
            period_profit_totals[period] += profit
            period_cats[period].append({
                "category": cat,
                "sale_amount": round(amt, 2),
                "profit_amount": round(profit, 2),
            })
        out = []
        for period in sorted(period_totals.keys()):
            total = period_totals[period]
            total_profit = period_profit_totals[period]
            cats = period_cats[period]
            for c in cats:
                pct = (c["sale_amount"] / total * 100) if total > 0 else 0
                profit_pct = (c["profit_amount"] / total_profit * 100) if total_profit > 0 else 0
                c["share_pct"] = round(pct, 2)
                c["profit_share_pct"] = round(profit_pct, 2)
            out.append({"period": period, "total_sale": round(total, 2), "total_profit": round(total_profit, 2), "by_category": cats})
        return jsonify(out)
    finally:
        conn.close()


@profit_bp.route("/api/inventory_turnover_summary")
def api_inventory_turnover_summary():
    """库存周转汇总：期末库存金额、周期内销售成本（或销售额）、周转天数"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(SUM(stock_amount), 0) AS total_stock
                FROM t_htma_stock
                WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
            """, (params[0], params[0]))
            stock_row = cur.fetchone()
            cur.execute(f"""
                SELECT COALESCE(SUM(sale_amount), 0) AS sale_amount, COALESCE(SUM(sale_cost), 0) AS cost_amount
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond}
            """, params)
            sale_row = cur.fetchone()
        total_stock = float(stock_row["total_stock"] or 0)
        total_sale = float(sale_row["sale_amount"] or 0)
        total_cost = float(sale_row["cost_amount"] or 0)
        days = 30
        if request.args.get("start_date") and request.args.get("end_date"):
            try:
                e = datetime.strptime(request.args.get("end_date"), "%Y-%m-%d").date()
                s = datetime.strptime(request.args.get("start_date"), "%Y-%m-%d").date()
                days = max(1, (e - s).days + 1)
            except Exception:
                pass
        daily_cost = total_cost / days if days > 0 else 0
        turnover_days = (total_stock / daily_cost) if daily_cost > 0 else None
        return jsonify({
            "total_stock_amount": round(total_stock, 2),
            "period_sale_amount": round(total_sale, 2),
            "period_cost_amount": round(total_cost, 2),
            "turnover_days": round(turnover_days, 1) if turnover_days is not None else None,
            "days": days,
        })
    finally:
        conn.close()


@profit_bp.route("/api/inventory_turnover_by_category")
def api_inventory_turnover_by_category():
    """库存周转按品类：按大类汇总期末库存金额、周期销售成本、周转天数，与 summary 口径一致"""
    date_cond, _, params, category_cond, _ = _query_filters()
    days = 30
    if request.args.get("start_date") and request.args.get("end_date"):
        try:
            e = datetime.strptime(request.args.get("end_date"), "%Y-%m-%d").date()
            s = datetime.strptime(request.args.get("start_date"), "%Y-%m-%d").date()
            days = max(1, (e - s).days + 1)
        except Exception:
            pass
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(NULLIF(TRIM(st.category_large), ''), NULLIF(TRIM(st.category), ''), '未分类') AS category_large,
                       COALESCE(SUM(st.stock_amount), 0) AS stock_amount
                FROM t_htma_stock st
                WHERE st.store_id = %s AND st.data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
                GROUP BY category_large
                HAVING stock_amount > 0
            """, (params[0], params[0]))
            stock_rows = cur.fetchall()
            cur.execute(f"""
                SELECT COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category), ''), '未分类') AS category_large,
                       COALESCE(SUM(sale_cost), 0) AS cost_amount
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}
                GROUP BY category_large
            """, params)
            cost_rows = cur.fetchall()
        stock_by_cat = {r["category_large"] or "未分类": float(r["stock_amount"] or 0) for r in stock_rows}
        cost_by_cat = {r["category_large"] or "未分类": float(r["cost_amount"] or 0) for r in cost_rows}
        all_cats = sorted(set(stock_by_cat.keys()) | set(cost_by_cat.keys()))
        out = []
        for cat in all_cats:
            stock_amt = stock_by_cat.get(cat, 0)
            cost_amt = cost_by_cat.get(cat, 0)
            daily_cost = cost_amt / days if days > 0 else 0
            turnover_days = (stock_amt / daily_cost) if daily_cost > 0 else None
            out.append({
                "category_large": cat,
                "stock_amount": round(stock_amt, 2),
                "period_cost_amount": round(cost_amt, 2),
                "turnover_days": round(turnover_days, 1) if turnover_days is not None else None,
                "days": days,
            })
        out.sort(key=lambda x: (-(x["stock_amount"] or 0), x["category_large"]))
        return jsonify(out)
    finally:
        conn.close()


@profit_bp.route("/api/data_quality")
def api_data_quality():
    """数据质量：成本/售价缺失条数、同 SKU 多品类异常数（与 data_status 互补）"""
    sid_dq = _effective_store_id()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM t_htma_sale
                WHERE store_id = %s AND (sale_cost IS NULL OR sale_cost = 0) AND sale_amount > 0
            """, (sid_dq,))
            missing_cost = cur.fetchone()["cnt"] or 0
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM t_htma_sale
                WHERE store_id = %s AND (sale_price IS NULL OR sale_price = 0) AND sale_qty > 0
            """, (sid_dq,))
            missing_price = cur.fetchone()["cnt"] or 0
            cur.execute("""
                SELECT sku_code, COUNT(DISTINCT COALESCE(category, '')) AS cat_cnt
                FROM t_htma_sale WHERE store_id = %s
                GROUP BY sku_code HAVING cat_cnt > 1
            """, (sid_dq,))
            inconsistent = cur.fetchall()
        inconsistent_sku_count = len(inconsistent)
        return jsonify({
            "missing_cost_rows": missing_cost,
            "missing_price_rows": missing_price,
            "inconsistent_category_sku_count": inconsistent_sku_count,
            "inconsistent_sku_sample": [r["sku_code"] for r in inconsistent[:20]],
        })
    finally:
        conn.close()




@profit_bp.route("/api/inv_alert_by_category")
def api_inv_alert_by_category():
    """低库存按品类层级汇总：level=large 按大类，level=mid 按中类，level=small 按小类。支持 category_large_code/mid 筛选"""
    level = request.args.get("level", "large").strip() or "large"
    category_large_code = request.args.get("category_large_code", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip()
    sid = _effective_store_id()
    inv_cond, inv_params, need_join = _inv_category_cond_and_params()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if level == "large":
                if need_join:
                    cur.execute(f"""
                        SELECT COALESCE(NULLIF(TRIM(s.category_large), ''), NULLIF(TRIM(s.category_large_code), ''), COALESCE(NULLIF(TRIM(st.category_name), ''), '未分类')) AS category_large,
                               COALESCE(NULLIF(TRIM(s.category_large_code), ''), NULLIF(TRIM(s.category_large), ''), '') AS category_large_code,
                               COUNT(DISTINCT st.sku_code) AS alert_sku_count,
                               COALESCE(SUM(st.stock_amount), 0) AS stock_amount
                        FROM t_htma_stock st
                        LEFT JOIN (
                            SELECT sku_code,
                                   MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                                   MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                                   MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                            FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                        ) s ON st.sku_code = s.sku_code
                        WHERE st.store_id = %s AND st.data_date = (
                            SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                        ) AND st.stock_qty < 50 AND st.stock_qty >= 0 {inv_cond}
                        GROUP BY category_large, category_large_code
                        ORDER BY alert_sku_count DESC
                    """, (sid, sid, sid) + inv_params)
                else:
                    cur.execute("""
                        SELECT COALESCE(NULLIF(TRIM(s.category_large), ''), NULLIF(TRIM(s.category_large_code), ''), COALESCE(NULLIF(TRIM(st.category_name), ''), COALESCE(NULLIF(TRIM(st.category), ''), '未分类'))) AS category_large,
                               COALESCE(NULLIF(TRIM(s.category_large_code), ''), NULLIF(TRIM(s.category_large), ''), '') AS category_large_code,
                               COUNT(DISTINCT st.sku_code) AS alert_sku_count,
                               COALESCE(SUM(st.stock_amount), 0) AS stock_amount
                        FROM t_htma_stock st
                        LEFT JOIN (
                            SELECT sku_code,
                                   MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                                   MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                                   MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                            FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                        ) s ON st.sku_code = s.sku_code
                        WHERE st.store_id = %s AND st.data_date = (
                            SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                        ) AND st.stock_qty < 50 AND st.stock_qty >= 0
                        GROUP BY category_large, category_large_code
                        ORDER BY alert_sku_count DESC
                    """, (sid, sid, sid))
            elif level == "mid" and category_large_code:
                large_cond = " AND (COALESCE(TRIM(s.category_large_code), '') = %s OR COALESCE(TRIM(s.category_large), '') = %s)"
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(s.category_mid), ''), NULLIF(TRIM(s.category_mid_code), ''), '未分类') AS category_mid,
                           COALESCE(NULLIF(TRIM(s.category_mid_code), ''), NULLIF(TRIM(s.category_mid), ''), '') AS category_mid_code,
                           COUNT(DISTINCT st.sku_code) AS alert_sku_count,
                           COALESCE(SUM(st.stock_amount), 0) AS stock_amount
                    FROM t_htma_stock st
                    INNER JOIN (
                        SELECT sku_code,
                               MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                               MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                               MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                        FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                    ) s ON st.sku_code = s.sku_code
                    WHERE st.store_id = %s AND st.data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND st.stock_qty < 50 AND st.stock_qty >= 0 {large_cond}
                    GROUP BY category_mid, category_mid_code
                    ORDER BY alert_sku_count DESC
                """, (sid, sid, sid, category_large_code, category_large_code))
            elif level == "small" and category_large_code and category_mid_code:
                mid_cond = " AND (COALESCE(TRIM(s.category_mid_code), '') = %s OR COALESCE(TRIM(s.category_mid), '') = %s)"
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(s.category_small), ''), NULLIF(TRIM(s.category_small_code), ''), COALESCE(NULLIF(TRIM(s.category), ''), '未分类')) AS category_small,
                           COALESCE(NULLIF(TRIM(s.category_small_code), ''), NULLIF(TRIM(s.category), ''), '') AS category_small_code,
                           COUNT(DISTINCT st.sku_code) AS alert_sku_count,
                           COALESCE(SUM(st.stock_amount), 0) AS stock_amount
                    FROM t_htma_stock st
                    INNER JOIN (
                        SELECT sku_code,
                               MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                               MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                               MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                        FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                    ) s ON st.sku_code = s.sku_code
                    WHERE st.store_id = %s AND st.data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND st.stock_qty < 50 AND st.stock_qty >= 0
                    AND (COALESCE(TRIM(s.category_large_code), '') = %s OR COALESCE(TRIM(s.category_large), '') = %s) {mid_cond}
                    GROUP BY category_small, category_small_code
                    ORDER BY alert_sku_count DESC
                """, (sid, sid, sid, category_large_code, category_large_code, category_mid_code, category_mid_code))
            else:
                return jsonify([])
            rows = cur.fetchall()
        key = "category_large" if level == "large" else ("category_mid" if level == "mid" else "category_small")
        code_key = key + "_code"
        return jsonify([{
            key: r.get(key) or "未分类",
            code_key: r.get(code_key) or "",
            "alert_sku_count": int(r["alert_sku_count"] or 0),
            "stock_amount": round(float(r["stock_amount"] or 0), 2),
        } for r in rows])
    finally:
        conn.close()



@profit_bp.route("/api/inv_alert")
def api_inv_alert():
    """低库存预警 SKU 数，支持 category_large_code/mid/small 筛选"""
    sid = _effective_store_id()
    inv_cond, inv_params, need_join = _inv_category_cond_and_params()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if need_join:
                cur.execute(f"""
                    SELECT COUNT(DISTINCT st.sku_code) AS alert_sku_count
                    FROM t_htma_stock st
                    INNER JOIN (
                        SELECT sku_code,
                               MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                               MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                               MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                        FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                    ) s ON st.sku_code = s.sku_code
                    WHERE st.store_id = %s AND st.data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND st.stock_qty < 50 AND st.stock_qty >= 0 {inv_cond}
                """, (sid, sid, sid) + inv_params)
            else:
                cur.execute("""
                    SELECT COUNT(DISTINCT sku_code) AS alert_sku_count
                    FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND stock_qty < 50 AND stock_qty >= 0
                """, (sid, sid))
            row = cur.fetchone()
        return jsonify({"alert_sku_count": int(row["alert_sku_count"] or 0)})
    finally:
        conn.close()


