# -*- coding: utf-8 -*-
# 阶段 D1：销售侧扩展 API（贡献结构、退货赠送、热力图、负毛利）— 由 app 末尾注册
import csv
import io
import sys
from datetime import date, timedelta

from flask import Blueprint, Response, jsonify, request

from extensions import cache


def _app():
    return sys.modules.get("app")


sales_ext_bp = Blueprint("sales_ext", __name__, url_prefix="/api")


def register_sales_routes(app):
    """注册到主 Flask app（避免循环 import：运行时已加载 app）。"""
    app.register_blueprint(sales_ext_bp)


@sales_ext_bp.route("/contribution_structure", methods=["GET", "OPTIONS"])
def api_contribution_structure():
    """阶段 B1：各大类销售额占比 vs 毛利额占比（t_htma_sale）。"""
    if request.method == "OPTIONS":
        return "", 204
    M = _app()
    if M and M._auth_enabled() and not M._is_logged_in():
        return jsonify({"success": False, "login_required": True}), 401
    start_d = (request.args.get("start_date") or "").strip()[:10]
    end_d = (request.args.get("end_date") or "").strip()[:10]
    if not start_d or not end_d:
        end_d = date.today().isoformat()[:10]
        start_d = (date.today() - timedelta(days=29)).isoformat()[:10]
    store_id = (M._effective_store_id() if M else "沈阳超级仓")
    ck = "contrib:v1:%s:%s:%s" % (store_id, start_d, end_d)
    hit = cache.get(ck)
    if hit is not None:
        return jsonify(hit)
    conn = M.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(category_large), ''), '未分类') AS category_large,
                   COALESCE(SUM(sale_amount), 0) AS sale_amount,
                   COALESCE(SUM(gross_profit), 0) AS gross_profit
            FROM t_htma_sale
            WHERE store_id = %s AND data_date BETWEEN %s AND %s
              AND (category_large IS NOT NULL AND TRIM(category_large) != ''
                   OR category_large_code IS NOT NULL AND TRIM(category_large_code) != '')
            GROUP BY COALESCE(NULLIF(TRIM(category_large), ''), '未分类')
            ORDER BY sale_amount DESC
            """,
            (store_id, start_d, end_d),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()
    total_sale = sum(float(r.get("sale_amount") or 0) for r in rows)
    total_profit = sum(float(r.get("gross_profit") or 0) for r in rows)
    items = []
    for r in rows:
        sa = float(r.get("sale_amount") or 0)
        gp = float(r.get("gross_profit") or 0)
        items.append({
            "category_large": r.get("category_large") or "未分类",
            "sales_amount": round(sa, 2),
            "sales_share": round(sa / total_sale * 100, 2) if total_sale > 0 else 0,
            "gross_profit": round(gp, 2),
            "profit_share": round(gp / total_profit * 100, 2) if total_profit > 0 else 0,
        })
    body = {"success": True, "start_date": start_d, "end_date": end_d, "items": items}
    cache.set(ck, body, timeout=300)
    return jsonify(body)

@sales_ext_bp.route("/return_gift_share", methods=["GET", "OPTIONS"])
def api_return_gift_share():
    """阶段 C1：按大类退货率、赠送率（依赖 return_amount/gift_amount 列）。"""
    if request.method == "OPTIONS":
        return "", 204
    M = _app()
    if M and M._auth_enabled() and not M._is_logged_in():
        return jsonify({"success": False, "login_required": True}), 401
    start_d = (request.args.get("start_date") or "").strip()[:10]
    end_d = (request.args.get("end_date") or "").strip()[:10]
    if not start_d or not end_d:
        end_d = date.today().isoformat()[:10]
        start_d = (date.today() - timedelta(days=29)).isoformat()[:10]
    store_id = (M._effective_store_id() if M else "沈阳超级仓")
    conn = None
    try:
        conn = M.get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_htma_sale' AND COLUMN_NAME = 'return_amount'
            LIMIT 1
            """
        )
        if cur.fetchone() is None:
            # 无退货字段，跳过 C1
            return jsonify({"success": True, "skipped": True, "message": "无 return_amount 列", "items": []})
        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(category_large), ''), '未分类') AS category_large,
                   COALESCE(SUM(sale_amount), 0) AS sale_amount,
                   COALESCE(SUM(return_amount), 0) AS return_amount,
                   COALESCE(SUM(gift_amount), 0) AS gift_amount
            FROM t_htma_sale
            WHERE store_id = %s AND data_date BETWEEN %s AND %s
            GROUP BY COALESCE(NULLIF(TRIM(category_large), ''), '未分类')
            HAVING SUM(sale_amount) > 0
            ORDER BY sale_amount DESC
            """,
            (store_id, start_d, end_d),
        )
        rows = cur.fetchall() or []
    except Exception as e:
        return jsonify({"success": False, "message": str(e), "items": []}), 500
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    items = []
    for r in rows:
        sa = float(r.get("sale_amount") or 0)
        ra = float(r.get("return_amount") or 0)
        ga = float(r.get("gift_amount") or 0)
        items.append({
            "category_large": r.get("category_large") or "未分类",
            "return_rate_pct": round(ra / sa * 100, 2) if sa > 0 else 0,
            "gift_rate_pct": round(ga / sa * 100, 2) if sa > 0 else 0,
        })
    return jsonify({"success": True, "start_date": start_d, "end_date": end_d, "items": items})

@sales_ext_bp.route("/category_trend_heatmap", methods=["GET", "OPTIONS"])
def api_category_trend_heatmap():
    """阶段 C4：最近 12 个月 × 大类毛利率矩阵。"""
    if request.method == "OPTIONS":
        return "", 204
    M = _app()
    if M and M._auth_enabled() and not M._is_logged_in():
        return jsonify({"success": False, "login_required": True}), 401
    store_id = (M._effective_store_id() if M else "沈阳超级仓")
    conn = M.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DATE_FORMAT(data_date, '%%Y-%%m') AS ym,
                   COALESCE(NULLIF(TRIM(category_large), ''), '未分类') AS category_large,
                   COALESCE(SUM(gross_profit), 0) / NULLIF(COALESCE(SUM(sale_amount), 0), 0) * 100 AS margin_pct
            FROM t_htma_sale
            WHERE store_id = %s
              AND data_date >= DATE_SUB(CURDATE(), INTERVAL 400 DAY)
            GROUP BY DATE_FORMAT(data_date, '%%Y-%%m'),
                     COALESCE(NULLIF(TRIM(category_large), ''), '未分类')
            HAVING SUM(sale_amount) > 0
            ORDER BY ym, category_large
            """,
            (store_id,),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()
    months = sorted({r.get("ym") for r in rows if r.get("ym")})
    cats = sorted({r.get("category_large") for r in rows if r.get("category_large")})
    mat = []
    for cat in cats:
        rowd = {"category_large": cat, "by_month": {}}
        for r in rows:
            if (r.get("category_large") or "") != cat:
                continue
            ym = r.get("ym")
            if ym:
                rowd["by_month"][ym] = round(float(r.get("margin_pct") or 0), 2)
        mat.append(rowd)
    return jsonify({"success": True, "months": months, "categories": cats, "matrix": mat, "raw": [
        {"month": r.get("ym"), "category_large": r.get("category_large"), "margin_pct": round(float(r.get("margin_pct") or 0), 2)}
        for r in rows
    ]})

@sales_ext_bp.route("/negative_margin_items", methods=["GET", "OPTIONS"])
def api_negative_margin_items():
    """阶段 C3：负毛利率 SKU 汇总；export=1 返回 CSV。"""
    if request.method == "OPTIONS":
        return "", 204
    M = _app()
    if M and M._auth_enabled() and not M._is_logged_in():
        return jsonify({"success": False, "login_required": True}), 401
    start_d = (request.args.get("start_date") or "").strip()[:10]
    end_d = (request.args.get("end_date") or "").strip()[:10]
    if not start_d or not end_d:
        end_d = date.today().isoformat()[:10]
        start_d = (date.today() - timedelta(days=29)).isoformat()[:10]
    store_id = (M._effective_store_id() if M else "沈阳超级仓")
    export = (request.args.get("export") or "").strip() == "1"
    try:
        lim = int((request.args.get("limit") or "500").strip() or "500")
    except ValueError:
        lim = 500
    try:
        off = int((request.args.get("offset") or "0").strip() or "0")
    except ValueError:
        off = 0
    if export:
        lim = min(max(lim, 1), 2000)
        off = 0
    else:
        lim = max(1, min(lim, 500))
        off = max(0, off)
    conn = M.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT sku_code,
                   COALESCE(MAX(NULLIF(TRIM(product_name), '')), sku_code) AS product_name,
                   COALESCE(MAX(NULLIF(TRIM(category_large), '')), '') AS category_large,
                   SUM(sale_amount) AS sale_amount,
                   SUM(COALESCE(sale_cost, 0)) AS sale_cost,
                   SUM(gross_profit) AS gross_profit
            FROM t_htma_sale
            WHERE store_id = %s AND data_date BETWEEN %s AND %s
            GROUP BY sku_code
            HAVING SUM(sale_amount) > 0
               AND SUM(gross_profit) / SUM(sale_amount) < 0
            ORDER BY SUM(gross_profit) ASC
            LIMIT %s OFFSET %s
            """,
            (store_id, start_d, end_d, lim, off),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()
    items = []
    for r in rows:
        sa = float(r.get("sale_amount") or 0)
        gp = float(r.get("gross_profit") or 0)
        margin_pct = round(gp / sa * 100, 2) if sa > 0 else 0
        items.append({
            "sku_code": r.get("sku_code"),
            "product_name": r.get("product_name") or "",
            "category_large": r.get("category_large") or "",
            "sale_amount": round(sa, 2),
            "sale_cost": round(float(r.get("sale_cost") or 0), 2),
            "gross_profit": round(gp, 2),
            "margin_pct": margin_pct,
        })
    if export:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["sku_code", "product_name", "category_large", "sale_amount", "sale_cost", "gross_profit", "margin_pct"])
        for it in items:
            w.writerow([it["sku_code"], it["product_name"], it["category_large"], it["sale_amount"], it["sale_cost"], it["gross_profit"], it["margin_pct"]])
        return Response(
            buf.getvalue().encode("utf-8-sig"),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=negative_margin_skus.csv"},
        )
    return jsonify({
        "success": True,
        "start_date": start_d,
        "end_date": end_d,
        "limit": lim,
        "offset": off,
        "items": items,
    })
