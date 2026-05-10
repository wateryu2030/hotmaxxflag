# -*- coding: utf-8 -*-
"""报表与分析 API — serve_web/report：品类排行、洞察、结构化报告、营销报告、AI 对话"""

from flask import Blueprint, jsonify, request
from datetime import date, datetime, timedelta
import os

from core.db import get_conn
from core.context import (
    _effective_store_id, _query_filters, _profit_category_cond_and_params,
    _inv_category_cond_and_params, period_over_period_ranges,
)
from core.cache import _cache_get, _cache_set
from core.utils import safe_int, safe_float, safe_str

report_bp = Blueprint("report", __name__)

@report_bp.route("/api/category_rank_detail")
def api_category_rank_detail():
    """品类排行明细：按大类下的中类/小类（扁平列表，兼容旧用）。需传 category_large_code 或 category_large"""
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
                SELECT COALESCE(category, '未分类') AS category,
                       MAX(COALESCE(category_mid, '')) AS category_mid,
                       MAX(COALESCE(category_small, '')) AS category_small,
                       SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}{large_cond}
                GROUP BY category
                ORDER BY total_sale DESC
                LIMIT 100
            """, params)
            rows = cur.fetchall()
        total_sale = sum(float(r["total_sale"] or 0) for r in rows)
        total_profit = sum(float(r["total_profit"] or 0) for r in rows)
        out = []
        for i, r in enumerate(rows, 1):
            sale = float(r["total_sale"] or 0)
            profit = float(r["total_profit"] or 0)
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "rank": i,
                "category_mid": r.get("category_mid") or "",
                "category": r["category"] or "未分类",
                "sale_amount": round(sale, 2),
                "profit_amount": round(profit, 2),
                "margin_pct": round(margin, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


@report_bp.route("/api/category_rank")
def api_category_rank():
    """品类排行：销售、毛利、毛利率、贡献度。支持 start_date、end_date、category 及 hierarchy"""
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    params = (_effective_store_id(),) + date_params + profit_cat_params
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(category, '未分类') AS category,
                       SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                GROUP BY category
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
        out = category_rank_data(rows, total_sale, total_profit)
        return jsonify(out)
    finally:
        conn.close()


@report_bp.route("/api/insights")
def api_insights():
    """智能分析建议：基于零售业数据模型生成"""
    if _auth_enabled() and not _has_module_access("profit"):
        return jsonify({"success": False, "message": "无权访问盈利分析模块，请联系管理员"}), 403
    conn = get_conn()
    try:
        insights = build_insights(conn, _effective_store_id())
        return jsonify({"insights": insights})
    finally:
        conn.close()


@report_bp.route("/api/enhanced_insights")
def api_enhanced_insights():
    """增强分析卡片数据：时间周期、大类可选，返回高毛利/集中度/库存/动销/退货/周转/数据质量等"""
    if _auth_enabled() and not _has_module_access("profit"):
        return jsonify({"success": False, "message": "无权访问盈利分析模块，请联系管理员"}), 403
    period = request.args.get("period", "30").strip()
    try:
        period_days = int(period) if period else 30
    except ValueError:
        period_days = 30
    period_days = min(90, max(7, period_days))
    category_large = (request.args.get("category") or request.args.get("category_large") or "").strip() or None
    conn = get_conn()
    try:
        data = build_enhanced_insights(conn, _effective_store_id(), period_days=period_days, category_large=category_large)
        if isinstance(data, dict) and data.get("error"):
            return jsonify({"success": False, "message": data["error"]}), 500
        return jsonify({"success": True, "data": data or {}})
    finally:
        conn.close()


def _advanced_search_range_days(period, start_date, end_date):
    """根据 period/start_date/end_date 计算查询区间天数，用于周转天数计算。"""
    if start_date and end_date:
        try:
            s = datetime.strptime(start_date, "%Y-%m-%d").date() if isinstance(start_date, str) else start_date
            e = datetime.strptime(end_date, "%Y-%m-%d").date() if isinstance(end_date, str) else end_date
            if s > e:
                s, e = e, s
            return max(1, (e - s).days + 1)
        except (ValueError, TypeError):
            pass
    if period == "day":
        return 1
    if period == "week":
        return 7
    if period == "month":
        today = date.today()
        try:
            from calendar import monthrange
            return monthrange(today.year, today.month)[1]
        except Exception:
            return 30
    return int(os.environ.get("HTMA_DAYS", DEFAULT_DAYS))


@report_bp.route("/api/consumer_insight/advanced_search_options")
def api_advanced_search_options():
    """高级查询下拉选项：品牌、供应商、品类（去重），从商品档案与销售表取数。"""
    if _auth_enabled() and not _has_module_access("profit"):
        return jsonify({"code": 403, "brands": [], "suppliers": [], "categories": []}), 403
    conn = get_conn()
    try:
        sid_as = _effective_store_id()
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT TRIM(brand_name) AS v FROM t_htma_product_master WHERE store_id = %s AND TRIM(COALESCE(brand_name,'')) != '' ORDER BY v",
            (sid_as,),
        )
        brands = [r["v"] for r in cur.fetchall()]
        cur.execute(
            "SELECT DISTINCT TRIM(supplier_name) AS v FROM t_htma_product_master WHERE store_id = %s AND TRIM(COALESCE(supplier_name,'')) != '' ORDER BY v",
            (sid_as,),
        )
        suppliers = [r["v"] for r in cur.fetchall()]
        cur.execute(
            "SELECT DISTINCT TRIM(category_name) AS v FROM t_htma_product_master WHERE store_id = %s AND TRIM(COALESCE(category_name,'')) != '' ORDER BY v",
            (sid_as,),
        )
        categories = [r["v"] for r in cur.fetchall()]
        cur.close()
        return jsonify({"code": 0, "brands": brands, "suppliers": suppliers, "categories": categories})
    finally:
        conn.close()


@report_bp.route("/api/consumer_insight/advanced_search")
def api_advanced_search():
    """消费洞察高级查询：价格区间、品牌、供应商、品类、库存状态筛选，分页排序。export=1 时返回 CSV 下载。"""
    if _auth_enabled() and not _has_module_access("profit"):
        return jsonify({"code": 403, "data": {"total": 0, "page": 1, "page_size": 20, "items": []}}), 403
    period = (request.args.get("period") or "recent30").strip()
    start_date = (request.args.get("start_date") or "").strip() or None
    end_date = (request.args.get("end_date") or "").strip() or None
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    brands = (request.args.get("brands") or "").strip() or None
    suppliers = (request.args.get("suppliers") or "").strip() or None
    categories = (request.args.get("categories") or "").strip() or None
    stock_status = (request.args.get("stock_status") or "").strip() or None
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 20, type=int)
    if request.args.get("export") == "1":
        page, page_size = 1, 10000
    sort_by = (request.args.get("sort_by") or "sales_amount").strip()
    sort_order = (request.args.get("sort_order") or "desc").strip()
    range_days = _advanced_search_range_days(period, start_date, end_date)
    conn = get_conn()
    try:
        result = advanced_search_consumer_insight(
            conn,
            store_id=_effective_store_id(),
            period=period,
            start_date=start_date,
            end_date=end_date,
            min_price=min_price,
            max_price=max_price,
            brands=brands,
            suppliers=suppliers,
            categories=categories,
            stock_status=stock_status,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            range_days=range_days,
        )
        if request.args.get("export") == "1":
            import csv
            import io
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(["SKU", "品名", "品牌", "品类", "供应商", "平均单价", "销量", "销售额", "库存", "周转天数"])
            for x in result["items"]:
                writer.writerow([
                    x.get("sku_code") or "",
                    x.get("product_name") or "",
                    x.get("brand") or "",
                    x.get("category") or "",
                    x.get("supplier") or "",
                    x.get("avg_unit_price"),
                    x.get("total_qty"),
                    x.get("total_sales"),
                    x.get("stock_qty"),
                    x.get("stock_turnover_days"),
                ])
            resp = Response(out.getvalue(), mimetype="text/csv; charset=utf-8-sig")
            resp.headers["Content-Disposition"] = "attachment; filename=advanced_search.csv"
            return resp
        items = _enrich_advanced_search_with_price_compare(conn, result["items"])
        return jsonify({
            "code": 0,
            "data": {
                "total": result["total"],
                "page": page,
                "page_size": page_size,
                "items": items,
            },
        })
    finally:
        conn.close()


def _enrich_advanced_search_with_price_compare(conn, items):
    """为高级查询结果每项附加最新比价信息（从 t_price_compare 取各平台最新一条）。"""
    if not items:
        return items
    sku_list = list({x.get("sku_code") for x in items if x.get("sku_code")})
    if not sku_list:
        return items
    try:
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(sku_list))
        cur.execute(
            """
            SELECT sku_code, platform, price, original_price, promotion_info, good_rate, capture_date
            FROM t_price_compare
            WHERE sku_code IN (""" + placeholders + """)
            ORDER BY capture_date DESC
            """,
            sku_list,
        )
        rows = cur.fetchall()
        cur.close()
        by_sku = {}
        for r in rows:
            sku = r.get("sku_code")
            if sku not in by_sku:
                by_sku[sku] = {}
            platform = r.get("platform") or ""
            if platform and platform not in by_sku[sku]:
                cap = r.get("capture_date")
                by_sku[sku][platform] = {
                    "price": float(r["price"]) if r.get("price") is not None else None,
                    "original_price": float(r["original_price"]) if r.get("original_price") is not None else None,
                    "promotion": (r.get("promotion_info") or "")[:200],
                    "good_rate": float(r["good_rate"]) if r.get("good_rate") is not None else None,
                    "capture_date": cap.strftime("%Y-%m-%d %H:%M") if cap else None,
                }
        for x in items:
            x["price_compare"] = by_sku.get(x.get("sku_code")) or {}
        return items
    except Exception:
        for x in items:
            x["price_compare"] = {}
        return items


@report_bp.route("/api/price_compare/history")
def api_price_compare_history():
    """某商品比价历史趋势，用于详情弹窗图表。表 t_price_compare 不存在时返回空数据。"""
    sku_code = (request.args.get("sku_code") or "").strip()
    days = min(90, max(7, int(request.args.get("days", 30))))
    if not sku_code:
        return jsonify({"code": 1, "message": "缺少 sku_code", "product_name": "", "latest": {}, "history": []}), 400
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT sku_code, product_name, brand, platform, price, original_price, promotion_info, good_rate, capture_date
            FROM t_price_compare
            WHERE sku_code = %s AND capture_date >= DATE_SUB(NOW(), INTERVAL %s DAY)
            ORDER BY capture_date ASC
            """,
            (sku_code, days),
        )
        rows = cur.fetchall()
        cur.close()
        product_name = ""
        latest = {}
        history = []
        for r in rows:
            if not product_name and r.get("product_name"):
                product_name = r.get("product_name") or ""
            cap = r.get("capture_date")
            cap_str = cap.strftime("%Y-%m-%d %H:%M") if cap else ""
            platform = r.get("platform") or ""
            price = float(r["price"]) if r.get("price") is not None else None
            history.append({"platform": platform, "capture_date": cap_str, "price": price})
            if platform and platform not in latest:
                latest[platform] = {
                    "price": price,
                    "original_price": float(r["original_price"]) if r.get("original_price") is not None else None,
                    "promotion": (r.get("promotion_info") or "")[:200],
                    "good_rate": float(r["good_rate"]) if r.get("good_rate") is not None else None,
                    "capture_date": cap_str,
                }
        return jsonify({"code": 0, "product_name": product_name, "sku_code": sku_code, "latest": latest, "history": history})
    except Exception:
        return jsonify({"code": 0, "product_name": "", "sku_code": sku_code, "latest": {}, "history": []})
    finally:
        conn.close()


def _structured_report_to_html(report):
    """将结构化报告 dict 转为可读 HTML，用于导出下载。"""
    if not report:
        return "<!DOCTYPE html><html><head><meta charset=\"utf-8\"/><title>报告</title></head><body><p>无数据</p></body></html>"
    import html as html_module
    parts = ["<!DOCTYPE html><html><head><meta charset=\"utf-8\"/>", "<title>结构化分析报告</title>", "<style>body{font-family:sans-serif;margin:20px;background:#0f172a;color:#e2e8f0;} h2{margin-top:24px;color:#38bdf8;} table{border-collapse:collapse;} th,td{border:1px solid #334155;padding:6px 10px;text-align:left;} th{background:#1e293b;} .section{margin-bottom:20px;}</style>", "</head><body>"]
    summary = report.get("summary") or {}
    kpi = summary.get("kpi") or {}
    parts.append("<h2>1. 总览</h2><div class=\"section\">")
    parts.append("<p>销售额: %s | 毛利: %s | 毛利率: %s%% | 动销SKU: %s</p>" % (kpi.get("total_sale"), kpi.get("total_profit"), kpi.get("margin_pct"), kpi.get("sku_sold")))
    if summary.get("conclusion"):
        parts.append("<p>%s</p>" % html_module.escape(summary["conclusion"][:500]))
    parts.append("</div>")
    cat = report.get("category_structure") or {}
    if cat.get("top_sales") or cat.get("matrix"):
        parts.append("<h2>2. 品类结构</h2><div class=\"section\">")
        for row in (cat.get("top_sales") or cat.get("matrix") or [])[:15]:
            c = row.get("category") or row.get("cat") or "-"
            s = row.get("sale_amount") or row.get("sale") or 0
            p = row.get("profit") or 0
            parts.append("<p>%s — 销售: %s 毛利: %s</p>" % (html_module.escape(str(c)), s, p))
        parts.append("</div>")
    drill = report.get("drill_section") or {}
    if drill.get("brands") or drill.get("styles") or drill.get("skus"):
        parts.append("<h2>3. 下钻摘要</h2><div class=\"section\">")
        parts.append("<p>类型: %s</p>" % html_module.escape(drill.get("type", "")))
        for b in (drill.get("brands") or [])[:10]:
            parts.append("<p>品牌: %s 销售: %s</p>" % (html_module.escape(str(b.get("brand"))), b.get("sale_amount")))
        for s in (drill.get("styles") or [])[:10]:
            parts.append("<p>款式: %s 销售: %s</p>" % (html_module.escape(str(s.get("product_name"))), s.get("sale_amount")))
        for s in (drill.get("skus") or [])[:15]:
            parts.append("<p>货号: %s 销售: %s</p>" % (html_module.escape(str(s.get("sku_code"))), s.get("sale_amount")))
        parts.append("</div>")
    issues = report.get("issues") or {}
    rg = issues.get("return_gift") or {}
    if rg.get("return_rate") is not None or rg.get("return_by_cat"):
        parts.append("<h2>4. 问题与行动</h2><div class=\"section\">")
        parts.append("<p>退货率: %s%%</p>" % (rg.get("return_rate") or 0))
        parts.append("</div>")
    if report.get("market_expansion"):
        parts.append("<h2>5. 市场拓展</h2><div class=\"section\"><pre>%s</pre></div>" % html_module.escape((report["market_expansion"] or "")[:2000]))
    parts.append("</body></html>")
    return "".join(parts)


@report_bp.route("/api/structured_report")
def api_structured_report():
    """结构化分析报告：整合智能建议、消费洞察、下钻摘要与可选市场拓展报告。export=1 时返回附件（format=json 或 html）。"""
    if _auth_enabled() and not _has_module_access("profit"):
        return jsonify({"code": 403, "msg": "无权访问盈利分析模块，请联系管理员"}), 403
    period = (request.args.get("period") or "recent30").strip()
    start_date = (request.args.get("start_date") or "").strip() or None
    end_date = (request.args.get("end_date") or "").strip() or None
    category = (request.args.get("category") or "").strip() or None
    brand = (request.args.get("brand") or "").strip() or None
    product_name = (request.args.get("product_name") or "").strip() or None
    category_large_code = (request.args.get("category_large_code") or "").strip() or None
    category_mid_code = (request.args.get("category_mid_code") or "").strip() or None
    category_small_code = (request.args.get("category_small_code") or "").strip() or None
    include_market = (request.args.get("include_market") or "false").strip().lower() == "true"

    param_override = {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "category": category,
        "brand": brand,
        "product_name": product_name,
        "category_large_code": category_large_code,
        "category_mid_code": category_mid_code,
        "category_small_code": category_small_code,
    }
    conn = get_conn()
    try:
        insight_data = _get_consumer_insight_data(param_override=param_override)
        drill_context = None
        if category or brand or product_name:
            drill_context = {
                "category": category,
                "brand": brand,
                "product_name": product_name,
                "drill_brands": insight_data.get("drill_brands"),
                "drill_styles": insight_data.get("drill_styles"),
                "drill_sku_rank": insight_data.get("drill_sku_rank"),
            }
        eff_sr = _effective_store_id()
        insights = build_insights(conn, eff_sr, drill_context=drill_context)
        market_report_text = None
        if include_market:
            try:
                market_lines = build_marketing_report(conn, eff_sr, days=30, mode="market_expansion")
                market_report_text = "\n".join(market_lines) if isinstance(market_lines, list) else str(market_lines)
            except Exception:
                market_report_text = ""
        report = build_structured_report(insight_data, insights, market_report_text=market_report_text)
        # 报告导出：export=1 时返回附件下载；format=json（默认）或 format=html
        if request.args.get("export") == "1":
            import json
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            fmt = (request.args.get("format") or "json").strip().lower()
            if fmt == "html":
                html = _structured_report_to_html(report)
                return Response(html.encode("utf-8"), mimetype="text/html; charset=utf-8", headers={"Content-Disposition": "attachment; filename=\"structured_report_%s.html\"" % ts})
            body = json.dumps({"code": 0, "data": report}, ensure_ascii=False, indent=2)
            return Response(body.encode("utf-8"), mimetype="application/json; charset=utf-8", headers={"Content-Disposition": "attachment; filename=\"structured_report_%s.json\"" % ts})
        return jsonify({"code": 0, "data": report})
    except Exception as e:
        import traceback
        return jsonify({"code": 500, "msg": str(e), "traceback": traceback.format_exc()}), 500
    finally:
        conn.close()


@report_bp.route("/api/repair_recalc_unit_price", methods=["POST"])
def api_repair_recalc_unit_price():
    """将金额/成本按单价×数量重算：当导入时误将单价当总金额时使用"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE t_htma_sale
                SET sale_amount = sale_amount * CASE WHEN sale_qty > 0 THEN sale_qty ELSE 1 END,
                    sale_cost = sale_cost * CASE WHEN sale_qty > 0 THEN sale_qty ELSE 1 END
            """)
            cur.execute("UPDATE t_htma_sale SET gross_profit = sale_amount - sale_cost")
            conn.commit()
            cur.execute("TRUNCATE TABLE t_htma_profit")
            cur.execute("""
                INSERT INTO t_htma_profit (data_date, category, total_sale, total_profit, profit_rate, store_id,
                    category_code, category_large_code, category_large, category_mid_code, category_mid, category_small_code, category_small)
                SELECT data_date, COALESCE(category, '未分类'),
                       SUM(sale_amount), SUM(COALESCE(gross_profit, 0)),
                       LEAST(1, GREATEST(-1, CASE WHEN SUM(sale_amount) > 0 THEN SUM(COALESCE(gross_profit, 0)) / SUM(sale_amount) ELSE 0 END)),
                       store_id,
                       MAX(category_code), MAX(category_large_code), MAX(category_large),
                       MAX(category_mid_code), MAX(category_mid), MAX(category_small_code), MAX(category_small)
                FROM t_htma_sale
                GROUP BY data_date, category, store_id
            """)
            conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "已按单价×数量重算销售额与成本"})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "message": str(e)}), 500


@report_bp.route("/api/repair_swap_amount_cost", methods=["POST"])
def api_repair_swap_amount_cost():
    """对调 t_htma_sale 中 sale_amount 与 sale_cost，并重算毛利表。用于修复金额/进价列错位导入的数据"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE t_htma_sale SET sale_amount = sale_cost, sale_cost = sale_amount")
            cur.execute("UPDATE t_htma_sale SET gross_profit = sale_amount - sale_cost")
            conn.commit()
            cur.execute("TRUNCATE TABLE t_htma_profit")
            cur.execute("""
                INSERT INTO t_htma_profit (data_date, category, total_sale, total_profit, profit_rate, store_id,
                    category_code, category_large_code, category_large, category_mid_code, category_mid, category_small_code, category_small)
                SELECT data_date, COALESCE(category, '未分类'),
                       SUM(sale_amount), SUM(COALESCE(gross_profit, 0)),
                       LEAST(1, GREATEST(-1, CASE WHEN SUM(sale_amount) > 0 THEN SUM(COALESCE(gross_profit, 0)) / SUM(sale_amount) ELSE 0 END)),
                       store_id,
                       MAX(category_code), MAX(category_large_code), MAX(category_large),
                       MAX(category_mid_code), MAX(category_mid), MAX(category_small_code), MAX(category_small)
                FROM t_htma_sale
                GROUP BY data_date, category, store_id
            """)
            conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "已对调金额与成本并重算毛利表"})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "message": str(e)}), 500


def _ensure_report_log_table(conn):
    """确保 t_htma_report_log 表存在"""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS t_htma_report_log (
              id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
              report_date DATE NOT NULL,
              report_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              store_id VARCHAR(32) DEFAULT '沈阳超级仓',
              report_content TEXT NOT NULL,
              feishu_at_user_id VARCHAR(64) DEFAULT NULL,
              feishu_at_user_name VARCHAR(32) DEFAULT NULL,
              send_status TINYINT DEFAULT 1,
              send_error VARCHAR(512) DEFAULT NULL,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              KEY idx_report_date (report_date),
              KEY idx_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.commit()
        cur.close()
    except Exception:
        pass


def _save_report_log(conn, report, send_ok, send_err=None):
    """将报告保存到 t_htma_report_log"""
    try:
        _ensure_report_log_table(conn)
        from feishu_util import FEISHU_AT_USER_ID, FEISHU_AT_USER_NAME
        uid = (FEISHU_AT_USER_ID or "").strip()
        if uid and not uid.startswith("ou_"):
            uid = f"ou_{uid}"
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO t_htma_report_log
               (report_date, report_time, store_id, report_content, feishu_at_user_id, feishu_at_user_name, send_status, send_error)
               VALUES (CURDATE(), NOW(), %s, %s, %s, %s, %s, %s)""",
            (STORE_ID, report, uid or None, FEISHU_AT_USER_NAME, 1 if send_ok else 0, (send_err or "")[:512]),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        pass  # 表可能未创建，静默失败


@report_bp.route("/api/marketing_report")
def api_marketing_report():
    """进销存营销分析报告。mode=internal 为明细版（Top10 列清品名/利润/利润率+专家建议），market_expansion 为市场拓展版。send=1 时推送飞书"""
    send_feishu_flag = request.args.get("send", "").strip() in ("1", "true", "yes")
    mode = request.args.get("mode", "internal").strip() or "internal"
    if _auth_enabled() and not _has_module_access("profit"):
        return jsonify({"success": False, "message": "无权访问盈利分析模块，请联系管理员"}), 403
    try:
        from analytics import build_marketing_report
        conn = get_conn()
        try:
            report = build_marketing_report(conn, STORE_ID, mode=mode)
            report_text = "\n".join(report) if isinstance(report, list) else str(report or "")
            send_ok = False
            send_err = None
            wecom_ok = dingtalk_ok = False
            if send_feishu_flag:
                _load_env_from_file(_env_path, force_keys=("FEISHU_WEBHOOK_URL",))
                try:
                    from notify_util import notify_all
                    results, _ = notify_all(report_text, title="好特卖进销存营销分析",
                        feishu_at_user_id="ou_8db735f2", feishu_at_user_name="余为军")
                    send_ok = results.get("feishu", (False,))[0]
                    wecom_ok = results.get("wecom", (False,))[0]
                    dingtalk_ok = results.get("dingtalk", (False,))[0]
                    send_err = None if send_ok else (results.get("feishu", (False, ""))[1])
                except Exception as e:
                    from feishu_util import send_feishu
                    send_ok, send_err = send_feishu(report_text, at_user_id="ou_8db735f2", at_user_name="余为军")
            _save_report_log(conn, report_text, send_ok, send_err)
            return jsonify({
                "success": True, "report": report_text,
                "feishu_sent": send_feishu_flag, "feishu_ok": send_ok,
                "feishu_error": send_err if (send_feishu_flag and not send_ok) else None,
                "wecom_ok": wecom_ok, "dingtalk_ok": dingtalk_ok,
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@report_bp.route("/api/report_history")
def api_report_history():
    """营销报告历史列表，供 AI 分析界面展示"""
    try:
        limit = min(int(request.args.get("limit", "20")), 100)
        conn = get_conn()
        try:
            _ensure_report_log_table(conn)
            cur = conn.cursor()
            cur.execute(
                """SELECT id, report_date, report_time, store_id, feishu_at_user_name, send_status, send_error,
                          LEFT(report_content, 200) AS summary, LENGTH(report_content) AS content_len
                   FROM t_htma_report_log
                   ORDER BY report_time DESC
                   LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
            cur.close()
            return jsonify([{
                "id": r["id"],
                "report_date": r["report_date"].isoformat() if r.get("report_date") else None,
                "report_time": r["report_time"].isoformat() if r.get("report_time") else None,
                "store_id": r["store_id"],
                "feishu_at_user_name": r["feishu_at_user_name"],
                "send_status": r["send_status"],
                "send_error": (r.get("send_error") or "").strip() or None,
                "summary": r["summary"],
                "content_len": r["content_len"],
            } for r in rows])
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"error": str(e), "items": []}), 500


@report_bp.route("/api/report_history/<int:rid>")
def api_report_detail(rid):
    """获取单条报告全文"""
    try:
        conn = get_conn()
        try:
            _ensure_report_log_table(conn)
            cur = conn.cursor()
            cur.execute(
                """SELECT id, report_date, report_time, store_id, report_content, feishu_at_user_name, send_status
                   FROM t_htma_report_log WHERE id = %s""",
                (rid,),
            )
            r = cur.fetchone()
            cur.close()
            if not r:
                return jsonify({"error": "未找到"}), 404
            return jsonify({
                "id": r["id"],
                "report_date": r["report_date"].isoformat() if r.get("report_date") else None,
                "report_time": r["report_time"].isoformat() if r.get("report_time") else None,
                "store_id": r["store_id"],
                "report_content": r["report_content"],
                "feishu_at_user_name": r["feishu_at_user_name"],
                "send_status": r["send_status"],
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

