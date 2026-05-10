# -*- coding: utf-8 -*-
# 阶段 C2：品牌表现 Top10（t_htma_sale.brand_name）
import sys
from datetime import date, timedelta

from flask import Blueprint, jsonify, request


def _app():
    return sys.modules.get("app")


insights_ext_bp = Blueprint("insights_ext", __name__, url_prefix="/api")


def register_insights_routes(app):
    app.register_blueprint(insights_ext_bp)


@insights_ext_bp.route("/brand_performance", methods=["GET", "OPTIONS"])
def api_brand_performance():
    """销售额 Top10 品牌：销售额、毛利、毛利率。"""
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
    conn = M.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(brand_name), ''), '未填') AS brand_name,
                   SUM(sale_amount) AS sale_amount,
                   SUM(gross_profit) AS gross_profit
            FROM t_htma_sale
            WHERE store_id = %s AND data_date BETWEEN %s AND %s
            GROUP BY COALESCE(NULLIF(TRIM(brand_name), ''), '未填')
            HAVING SUM(sale_amount) > 0
            ORDER BY SUM(sale_amount) DESC
            LIMIT 10
            """,
            (store_id, start_d, end_d),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()
    items = []
    for r in rows:
        sa = float(r.get("sale_amount") or 0)
        gp = float(r.get("gross_profit") or 0)
        items.append({
            "brand_name": r.get("brand_name") or "未填",
            "sale_amount": round(sa, 2),
            "gross_profit": round(gp, 2),
            "margin_pct": round(gp / sa * 100, 2) if sa > 0 else 0,
        })
    return jsonify({"success": True, "start_date": start_d, "end_date": end_d, "items": items})
