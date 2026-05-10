# -*- coding: utf-8 -*-
# 阶段 D1：品类下钻相关路由（B3）
import sys
from datetime import date, timedelta

from flask import Blueprint, jsonify, redirect, request, send_from_directory

from labor_routes import labor_analysis_by_category


def _app():
    return sys.modules.get("app")


category_ext_bp = Blueprint("category_ext", __name__)


def register_category_routes(app):
    app.register_blueprint(category_ext_bp)


@category_ext_bp.route("/category_drill")
def page_category_drill():
    """大类→中类下钻页。"""
    M = _app()
    if M and M._auth_enabled() and not M._is_logged_in():
        return redirect("/login?next=/category_drill")
    return send_from_directory("static", "category_drill.html")


@category_ext_bp.route("/api/category_drill", methods=["GET", "OPTIONS"])
def api_category_drill():
    """某大类下中类销售、毛利、毛利率；人力按大类内销售额占比分摊。"""
    if request.method == "OPTIONS":
        return "", 204
    M = _app()
    if M and M._auth_enabled() and not M._is_logged_in():
        return jsonify({"success": False, "login_required": True}), 401
    large = (request.args.get("large_category") or request.args.get("large") or "").strip()
    start_d = (request.args.get("start_date") or "").strip()[:10]
    end_d = (request.args.get("end_date") or "").strip()[:10]
    if not large:
        return jsonify({"success": False, "message": "缺少 large_category"}), 400

    if not start_d or not end_d:
        end_d = date.today().isoformat()[:10]
        start_d = (date.today() - timedelta(days=29)).isoformat()[:10]
    store_id = (M._effective_store_id() if M else "沈阳超级仓")
    conn = M.get_conn()
    labor_cost_large = 0.0
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(category_mid), ''), '未分类') AS category_mid,
                   COALESCE(SUM(sale_amount), 0) AS sale_amount,
                   COALESCE(SUM(gross_profit), 0) AS gross_profit
            FROM t_htma_sale
            WHERE store_id = %s AND data_date BETWEEN %s AND %s
              AND (
                NULLIF(TRIM(category_large_code), '') = %s
                OR NULLIF(TRIM(category_large), '') = %s
              )
            GROUP BY COALESCE(NULLIF(TRIM(category_mid), ''), '未分类')
            ORDER BY sale_amount DESC
            """,
            (store_id, start_d, end_d, large, large),
        )
        mids = cur.fetchall() or []
        cur.execute(
            """
            SELECT COALESCE(SUM(sale_amount), 0) AS large_sale
            FROM t_htma_sale
            WHERE store_id = %s AND data_date BETWEEN %s AND %s
              AND (
                NULLIF(TRIM(category_large_code), '') = %s
                OR NULLIF(TRIM(category_large), '') = %s
              )
            """,
            (store_id, start_d, end_d, large, large),
        )
        lr = cur.fetchone() or {}
        large_sale = float(lr.get("large_sale") or 0)
        try:
            rows_labor = labor_analysis_by_category(conn, start_d, end_d)
            for rw in rows_labor or []:
                code = str(rw.get("category_large_code") or "")
                name = str(rw.get("category") or "")
                if code == large or name == large:
                    labor_cost_large = float(rw.get("labor_cost") or 0)
                    break
        except Exception:
            labor_cost_large = 0.0
    finally:
        conn.close()
    items = []
    for r in mids:
        sa = float(r.get("sale_amount") or 0)
        gp = float(r.get("gross_profit") or 0)
        margin_pct = round(gp / sa * 100, 2) if sa > 0 else 0
        share = sa / large_sale if large_sale > 0 else 0
        items.append({
            "category_mid": r.get("category_mid") or "未分类",
            "sales_amount": round(sa, 2),
            "gross_profit": round(gp, 2),
            "margin_pct": margin_pct,
            "labor_cost_allocated": round(labor_cost_large * share, 2) if large_sale > 0 else 0,
        })
    return jsonify({"success": True, "large_category": large, "start_date": start_d, "end_date": end_d, "items": items})
