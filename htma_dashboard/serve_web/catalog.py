# -*- coding: utf-8 -*-
"""serve_web/catalog：商品目录与销售导出 API"""

from flask import Blueprint, jsonify, request, send_file
from datetime import date, datetime, timedelta
import io, csv, json, re, os, math

from core.db import get_conn
from core.context import _effective_store_id
from query_layer import query_filters_from_request as _ql_query_filters

catalog_bp = Blueprint("catalog", __name__)


def _query_filters(include_sku=False):
    """兼容 app.py 的 _query_filters 包装。"""
    date_cond, date_params, params, category_cond, sku_cond = _ql_query_filters(include_sku=include_sku)
    if params and params[0] is None:
        sid = _effective_store_id()
        params = (sid,) + tuple(params[1:])
    return date_cond, date_params, params, category_cond, sku_cond


def _profit_category_cond_and_params(date_cond, date_params_tuple):
    """从 request 提取品类筛选条件（兼容 app.py 版本）。"""
    category_large_code = request.args.get("category_large_code", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip()
    category_small_code = request.args.get("category_small_code", "").strip()
    if not (category_large_code or category_mid_code or category_small_code):
        return "", ()
    conds, params = [], []
    if category_large_code:
        conds.append("(COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)")
        params.extend([category_large_code, category_large_code])
    if category_mid_code:
        conds.append("(COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)")
        params.extend([category_mid_code, category_mid_code])
    if category_small_code:
        conds.append("(COALESCE(TRIM(category_small_code), '') = %s OR COALESCE(TRIM(category_small), '') = %s OR COALESCE(TRIM(category), '') = %s)")
        params.extend([category_small_code, category_small_code, category_small_code])
    return " AND " + " AND ".join(conds), tuple(params)


from flask import Response

@catalog_bp.route("/api/categories")
def api_categories():
    """获取品类列表。优先从 t_htma_category（品类主数据）级联；无则从 t_htma_sale、t_htma_profit 兜底。
    编码规则：中类编码前2位=大类编码，小类编码前4位=中类编码。level=large|mid|small。返回 [{code, name}]"""
    level = request.args.get("level", "large").strip() or "large"
    large_key = request.args.get("category_large_code", "").strip()
    mid_key = request.args.get("category_mid_code", "").strip()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 优先品类主数据表（附表结构，编码级联）
            cur.execute("SELECT COUNT(*) AS cnt FROM t_htma_category")
            cat_cnt = cur.fetchone().get("cnt") or 0
            if cat_cnt > 0:
                if level == "large":
                    cur.execute("""
                        SELECT DISTINCT category_large_code AS code, category_large AS name
                        FROM t_htma_category WHERE category_large_code != '' AND category_large != ''
                        ORDER BY category_large_code
                    """)
                elif level == "mid":
                    if large_key:
                        cur.execute("""
                            SELECT DISTINCT category_mid_code AS code, category_mid AS name
                            FROM t_htma_category
                            WHERE category_large_code = %s AND category_mid_code != ''
                            ORDER BY category_mid_code
                        """, (large_key,))
                    else:
                        cur.execute("""
                            SELECT DISTINCT category_mid_code AS code, category_mid AS name
                            FROM t_htma_category WHERE category_mid_code != ''
                            ORDER BY category_mid_code
                        """)
                elif level == "small":
                    if large_key and mid_key:
                        cur.execute("""
                            SELECT DISTINCT category_small_code AS code, category_small AS name
                            FROM t_htma_category
                            WHERE category_large_code = %s AND category_mid_code = %s AND category_small_code != ''
                            ORDER BY category_small_code
                        """, (large_key, mid_key))
                    elif large_key:
                        cur.execute("""
                            SELECT DISTINCT category_small_code AS code, category_small AS name
                            FROM t_htma_category
                            WHERE category_large_code = %s AND category_small_code != ''
                            ORDER BY category_small_code
                        """, (large_key,))
                    else:
                        cur.execute("""
                            SELECT DISTINCT category_small_code AS code, category_small AS name
                            FROM t_htma_category WHERE category_small_code != ''
                            ORDER BY category_small_code
                        """)
                else:
                    return jsonify([])
                rows = cur.fetchall()
                # 编码级联：中类前2位=大类，小类前4位=中类（兼容主数据表可能用编码过滤）
                if level == "mid" and large_key and not rows:
                    cur.execute("""
                        SELECT DISTINCT category_mid_code AS code, category_mid AS name
                        FROM t_htma_category
                        WHERE category_mid_code LIKE %s AND category_mid_code != ''
                        ORDER BY category_mid_code
                    """, (large_key[:2] + "%",))
                    rows = cur.fetchall()
                elif level == "small" and mid_key and not rows:
                    cur.execute("""
                        SELECT DISTINCT category_small_code AS code, category_small AS name
                        FROM t_htma_category
                        WHERE category_small_code LIKE %s AND category_small_code != ''
                        ORDER BY category_small_code
                    """, (mid_key[:4] + "%",))
                    rows = cur.fetchall()
            else:
                rows = []
            # 兜底：从 t_htma_sale、t_htma_profit 取
            if not rows:
                if level == "large":
                    cur.execute("""
                        SELECT DISTINCT
                            COALESCE(NULLIF(TRIM(category_large_code), ''), NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category), ''), '未分类') AS code,
                            COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category), ''), '未分类') AS name
                        FROM t_htma_sale WHERE store_id = %s
                          AND (COALESCE(TRIM(category_large_code), '') != '' OR COALESCE(TRIM(category_large), '') != '' OR COALESCE(TRIM(category), '') != '')
                        ORDER BY name
                    """, (_effective_store_id(),))
                elif level == "mid":
                    large_cond = "(COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)" if large_key else "1=1"
                    cur.execute(f"""
                        SELECT DISTINCT
                            COALESCE(NULLIF(TRIM(category_mid_code), ''), NULLIF(TRIM(category_mid), ''), COALESCE(category, '未分类')) AS code,
                            COALESCE(NULLIF(TRIM(category_mid), ''), COALESCE(category, '未分类')) AS name
                        FROM t_htma_sale WHERE store_id = %s AND {large_cond}
                          AND (COALESCE(TRIM(category_mid_code), '') != '' OR COALESCE(TRIM(category_mid), '') != '' OR COALESCE(TRIM(category), '') != '')
                        ORDER BY code
                    """, (_effective_store_id(), large_key, large_key) if large_key else (_effective_store_id(),))
                elif level == "small":
                    large_cond = "(COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)" if large_key else "1=1"
                    mid_cond = "(COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)" if mid_key else "1=1"
                    params = [_effective_store_id()]
                    if large_key:
                        params.extend([large_key, large_key])
                    if mid_key:
                        params.extend([mid_key, mid_key])
                    cur.execute(f"""
                        SELECT DISTINCT
                            COALESCE(NULLIF(TRIM(category_small_code), ''), NULLIF(TRIM(category_small), ''), COALESCE(category, '未分类')) AS code,
                            COALESCE(NULLIF(TRIM(category_small), ''), COALESCE(category, '未分类')) AS name
                        FROM t_htma_sale WHERE store_id = %s AND {large_cond} AND {mid_cond}
                          AND (COALESCE(TRIM(category_small_code), '') != '' OR COALESCE(TRIM(category_small), '') != '' OR COALESCE(TRIM(category), '') != '')
                        ORDER BY code
                    """, tuple(params))
                else:
                    return jsonify([])
                rows = cur.fetchall()
                if not rows and level == "large":
                    cur.execute("""
                        SELECT DISTINCT
                            COALESCE(NULLIF(TRIM(category_large_code), ''), NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category), ''), '未分类') AS code,
                            COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category), ''), '未分类') AS name
                        FROM t_htma_profit WHERE store_id = %s
                          AND (COALESCE(TRIM(category_large_code), '') != '' OR COALESCE(TRIM(category_large), '') != '' OR COALESCE(TRIM(category), '') != '')
                        ORDER BY name
                    """, (_effective_store_id(),))
                    rows = cur.fetchall()
        seen = {}
        for r in rows:
            code = str(r.get("code") or "").strip()
            name = str(r.get("name") or "").strip()
            if not name:
                continue
            if name not in seen or (code and not seen[name]["code"]):
                seen[name] = {"code": code or name, "name": name}
        return jsonify(list(seen.values()))
    finally:
        conn.close()
@catalog_bp.route("/api/products")
def api_products():
    """获取商品列表（SKU+品类），用于下拉筛选。支持 category_*_code 编码或名称预筛"""
    category_large_code = request.args.get("category_large_code", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip()
    category_small_code = request.args.get("category_small_code", "").strip()
    conds, params = ["store_id = %s"], [_effective_store_id()]
    if category_large_code:
        conds.append("(COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)")
        params.extend([category_large_code, category_large_code])
    if category_mid_code:
        conds.append("(COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)")
        params.extend([category_mid_code, category_mid_code])
    if category_small_code:
        conds.append("(COALESCE(TRIM(category_small_code), '') = %s OR COALESCE(TRIM(category_small), '') = %s OR COALESCE(TRIM(category), '') = %s)")
        params.extend([category_small_code, category_small_code, category_small_code])
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT sku_code, COALESCE(category, '未分类') AS category
                FROM t_htma_sale
                WHERE """ + " AND ".join(conds) + """
                ORDER BY category, sku_code
            """, tuple(params))
            rows = cur.fetchall()
        return jsonify([{"sku_code": r["sku_code"], "category": r["category"]} for r in rows])
    finally:
        conn.close()

@catalog_bp.route("/api/sale_detail")
def api_sale_detail():
    """商品级销售毛利明细：日期、SKU、品类、销量、销售额、成本、毛利、毛利率。支持 period、start_date、end_date、category、sku_code、page、page_size"""
    date_cond, _, params, category_cond, sku_cond = _query_filters(include_sku=True)
    page = max(1, int(request.args.get("page", "1")))
    page_size = min(500, max(10, int(request.args.get("page_size", "50"))))
    offset = (page - 1) * page_size
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COUNT(*) AS total FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
            """, params)
            total = cur.fetchone()["total"] or 0
            cur.execute(f"""
                SELECT data_date, sku_code, COALESCE(category, '未分类') AS category,
                       COALESCE(product_name, '') AS product_name,
                       COALESCE(category_large, '') AS category_large, COALESCE(category_mid, '') AS category_mid, COALESCE(category_small, '') AS category_small,
                       sale_qty, sale_amount, sale_cost, gross_profit,
                       CASE WHEN sale_amount > 0 THEN (COALESCE(gross_profit, 0) / sale_amount) * 100 ELSE 0 END AS profit_rate_pct
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                ORDER BY data_date DESC, sale_amount DESC
                LIMIT %s OFFSET %s
            """, (*params, page_size, offset))
            rows = cur.fetchall()
        return jsonify({
            "items": [{
            "data_date": r["data_date"].strftime("%Y-%m-%d") if hasattr(r["data_date"], "strftime") else str(r["data_date"]),
            "sku_code": r["sku_code"],
            "category": r["category"],
            "product_name": r.get("product_name") or "",
            "category_large": r.get("category_large") or "",
            "category_mid": r.get("category_mid") or "",
            "category_small": r.get("category_small") or "",
            "sale_qty": float(r["sale_qty"] or 0),
            "sale_amount": float(r["sale_amount"] or 0),
            "sale_cost": float(r["sale_cost"] or 0),
            "gross_profit": float(r["gross_profit"] or 0),
            "profit_rate_pct": round(float(r["profit_rate_pct"] or 0), 2),
        } for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    finally:
        conn.close()

@catalog_bp.route("/api/export")
def api_export():
    """导出：商品从 t_htma_products，品类从 t_htma_category_profit。支持 period、start_date、end_date、category、sku_code、export_type=category|product"""
    from flask import Response
    import csv
    import io

    export_type = request.args.get("export_type", "product").strip() or "product"
    include_sku = export_type == "product"
    date_cond, date_params, params, category_cond, sku_cond = _query_filters(include_sku=include_sku)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if export_type == "category":
                # 品类：优先从 t_htma_category_profit，无则从 t_htma_profit 汇总
                try:
                    cur.execute("""
                        SELECT category, category_large, category_mid, category_small,
                               total_sale, total_profit, profit_rate, sale_count, period_start, period_end
                        FROM t_htma_category_profit
                        WHERE store_id = %s
                        ORDER BY total_sale DESC
                    """, (_effective_store_id(),))
                    rows = cur.fetchall()
                    headers = ["品类", "大类", "中类", "小类", "总销售额", "总毛利", "毛利率", "销售笔数", "周期起", "周期止"]
                    data_rows = []
                    for r in rows:
                        rate = float(r["profit_rate"] or 0) * 100 if r["profit_rate"] else 0
                        data_rows.append([
                            r["category"] or "未分类",
                            r["category_large"] or "",
                            r["category_mid"] or "",
                            r["category_small"] or "",
                            str(round(float(r["total_sale"] or 0), 2)),
                            str(round(float(r["total_profit"] or 0), 2)),
                            f"{rate:.2f}%",
                            str(r["sale_count"] or 0),
                            str(r["period_start"]) if r.get("period_start") else "",
                            str(r["period_end"]) if r.get("period_end") else "",
                        ])
                except Exception:
                    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
                    export_params = (_effective_store_id(),) + date_params + profit_cat_params
                    cur.execute(f"""
                        SELECT data_date, COALESCE(category, '未分类') AS category,
                               total_sale, total_profit, profit_rate
                        FROM t_htma_profit
                        WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                        ORDER BY data_date DESC, total_sale DESC
                    """, export_params)
                    rows = cur.fetchall()
                    headers = ["日期", "品类", "销售额", "毛利", "毛利率"]
                    data_rows = []
                    for r in rows:
                        rate = float(r["profit_rate"] or 0) * 100 if r["profit_rate"] else 0
                        data_rows.append([
                            r["data_date"].strftime("%Y-%m-%d") if hasattr(r["data_date"], "strftime") else str(r["data_date"]),
                            r["category"] or "未分类",
                            str(round(float(r["total_sale"] or 0), 2)),
                            str(round(float(r["total_profit"] or 0), 2)),
                            f"{rate:.2f}%",
                        ])
            else:
                # 商品：优先从 t_htma_products（含条码），无则从 t_htma_sale 汇总
                try:
                    cat_cond = ""
                    cat_params = [_effective_store_id()]
                    if params and len(params) > 2:
                        for i, p in enumerate(params[2:], 2):
                            if "category" in str(request.args):
                                break
                        # 简化：仅 store_id 筛选
                    cur.execute("""
                        SELECT sku_code, product_name, raw_name, spec, barcode, brand_name,
                               category, category_large, category_mid, category_small,
                               unit_price, sale_qty, sale_amount, gross_profit
                        FROM t_htma_products
                        WHERE store_id = %s
                        ORDER BY sale_amount DESC
                    """, (_effective_store_id(),))
                    rows = cur.fetchall()
                    headers = ["商品编码", "品名", "规格", "条码", "品牌", "品类", "大类", "中类", "小类", "售价", "销量", "销售额", "毛利"]
                    data_rows = []
                    for r in rows:
                        data_rows.append([
                            r["sku_code"] or "",
                            (r["product_name"] or r["raw_name"] or "")[:64],
                            r["spec"] or "",
                            r["barcode"] or "",
                            r["brand_name"] or "",
                            r["category"] or "未分类",
                            r["category_large"] or "",
                            r["category_mid"] or "",
                            r["category_small"] or "",
                            str(round(float(r["unit_price"] or 0), 2)),
                            str(float(r["sale_qty"] or 0)),
                            str(round(float(r["sale_amount"] or 0), 2)),
                            str(round(float(r["gross_profit"] or 0), 2)),
                        ])
                except Exception:
                    cur.execute(f"""
                        SELECT data_date, sku_code, COALESCE(category, '未分类') AS category,
                               sale_qty, sale_amount, sale_cost, gross_profit
                        FROM t_htma_sale
                        WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                        ORDER BY data_date DESC, sale_amount DESC
                    """, params)
                    rows = cur.fetchall()
                    headers = ["日期", "商品编码", "品类", "销售数量", "销售额", "成本", "毛利"]
                    data_rows = []
                    for r in rows:
                        data_rows.append([
                            r["data_date"].strftime("%Y-%m-%d") if hasattr(r["data_date"], "strftime") else str(r["data_date"]),
                            r["sku_code"] or "",
                            r["category"] or "未分类",
                            str(float(r["sale_qty"] or 0)),
                            str(round(float(r["sale_amount"] or 0), 2)),
                            str(round(float(r["sale_cost"] or 0), 2)),
                            str(round(float(r["gross_profit"] or 0), 2)),
                        ])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        for row in data_rows:
            writer.writerow(row)

        buf = io.BytesIO()
        buf.write(output.getvalue().encode("utf-8-sig"))
        buf.seek(0)
        fname = "htma_category.csv" if export_type == "category" else "htma_products.csv"
        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    finally:
        conn.close()

@catalog_bp.route("/api/dow_sales")
def api_dow_sales():
    """周几对比：与 KPI 一致，仅从 t_htma_sale 按星期几汇总，保证与总销售额、趋势图口径一致"""
    date_cond, date_params, params, sale_cat_cond, sku_cond = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT DAYOFWEEK(data_date) AS dow,
                       MAX(CASE DAYOFWEEK(data_date)
                         WHEN 1 THEN '周日' WHEN 2 THEN '周一' WHEN 3 THEN '周二' WHEN 4 THEN '周三'
                         WHEN 5 THEN '周四' WHEN 6 THEN '周五' WHEN 7 THEN '周六' ELSE '周日' END) AS dow_name,
                       COALESCE(SUM(sale_amount), 0) AS sale_amount,
                       COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount,
                       COUNT(DISTINCT data_date) AS day_count
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{sale_cat_cond}{sku_cond}
                GROUP BY DAYOFWEEK(data_date)
                ORDER BY dow
            """, params)
            rows = cur.fetchall()
        by_dow = {int(r["dow"]): r for r in rows}
        out = []
        for dow in range(1, 8):
            r = by_dow.get(dow, {})
            out.append({
                "dow": dow,
                "dow_name": r.get("dow_name") or DOW_NAMES.get(dow, "周?"),
                "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                "profit_amount": round(float(r.get("profit_amount") or 0), 2),
                "day_count": int(r.get("day_count") or 0),
            })
        return jsonify(out)
    finally:
        conn.close()
