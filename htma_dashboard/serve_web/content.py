# -*- coding: utf-8 -*-
"""serve_web/content：消费洞察 API"""

from flask import Blueprint, jsonify, request
from datetime import date, datetime, timedelta
from collections import defaultdict
import pymysql, pymysql.cursors, json

from core.db import get_conn
from core.context import _effective_store_id
from core.utils import safe_float
from query_layer import query_filters_from_request as _ql_query_filters
from query_layer import query_filters_from_params as _ql_query_filters_from_params

content_bp = Blueprint("content", __name__)


def _query_filters():
    """兼容 app.py 的 _query_filters 包装（返回 5 元素元组）。"""
    date_cond, date_params, params, category_cond, _ = _ql_query_filters()
    if params and params[0] is None:
        sid = _effective_store_id()
        params = (sid,) + tuple(params[1:])
    return date_cond, date_params, params, category_cond, _


def _ensure_product_master_distribution_mode(conn):
    """确保 product_master 表有 distribution_mode 列。"""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='t_htma_product_master' "
                "AND COLUMN_NAME='distribution_mode' LIMIT 1"
            )
            if cur.fetchone() is None:
                cur.execute("ALTER TABLE t_htma_product_master ADD COLUMN distribution_mode VARCHAR(32) DEFAULT ''")
    except Exception:
        pass

@content_bp.route("/api/consumer_insight", methods=["GET", "POST", "HEAD", "OPTIONS"])
def api_consumer_insight():
    """消费洞察：概览、品类/品牌/价格带/经销方式/新品。GET/POST 均支持，参数从 query 取，便于代理只放行 POST 时使用。"""
    if request.method in ("OPTIONS", "HEAD"):
        return "", 204 if request.method == "OPTIONS" else 200
    try:
        data = _get_consumer_insight_data()
        return jsonify(data)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return jsonify({"error": str(e), "traceback": tb, "overview": {}, "category_matrix": [], "category_top_sale": [], "category_top_profit": [], "category_top_margin": [], "brand": [], "price_band": [], "supplier": [], "top_sku": [], "distribution": [], "new_product": {}, "return_rate_pct": 0, "return_by_cat": [], "color_style": {}, "period_over_period": {}, "date_range": "", "discount_band": [], "zero_sale_skus": [], "high_discount_low_margin": [], "bi_insight": {}}), 500
def _build_bi_insight(overview, period_over_period, category_matrix, return_rate_pct, distribution, date_range):
    """根据概览、环比、品类矩阵、退货率、经销方式生成 BI 分析摘要与建议。"""
    highlights = []
    trend_desc = "本期数据已加载。"
    try:
        pop = period_over_period or {}
        pct = pop.get("pct_change")
        if pct is not None:
            try:
                pct_val = float(pct)
                if pct_val > 0:
                    trend_desc = "环比上期销售额上升 {:.1f}%，趋势向好。".format(pct_val)
                elif pct_val < 0:
                    trend_desc = "环比上期销售额下降 {:.1f}%，建议关注动销与促销。".format(abs(pct_val))
                else:
                    trend_desc = "环比上期销售额基本持平。"
            except (TypeError, ValueError):
                pass
        total_sale = (overview or {}).get("total_sale") or 0
        if total_sale > 0 and category_matrix:
            top_cat = category_matrix[0] if category_matrix else {}
            cat_name = (top_cat.get("category") or "").strip() or "头部品类"
            contrib = top_cat.get("sale_contrib_pct") or 0
            try:
                contrib_val = float(contrib)
            except (TypeError, ValueError):
                contrib_val = 0
            highlights.append("「{}」销售占比最高（{:.1f}%），可作为核心品类持续优化。".format(cat_name[:10], contrib_val))
        if return_rate_pct is not None and return_rate_pct > 3:
            try:
                rr = float(return_rate_pct)
                highlights.append("整体退货率 {:.2f}%，略高，建议排查高退货品类与品控。".format(rr))
            except (TypeError, ValueError):
                pass
        if distribution and len(distribution) >= 1:
            d1 = distribution[0]
            mode1 = (d1.get("mode") or "").strip() or "代销"
            c1 = d1.get("contrib_pct")
            if c1 is not None:
                try:
                    c1_val = float(c1)
                    highlights.append("经销方式以「{}」为主（占比 {:.1f}%），供应链结构稳定。".format(mode1[:4], c1_val))
                except (TypeError, ValueError):
                    pass
        if not highlights:
            highlights.append("可结合走势图观察销售额与品类的时间趋势，积累多月数据后可做季节性分析。")
    except Exception:
        highlights = ["数据加载正常，可切换时间粒度查看走势。"]
    return {"trend_desc": trend_desc, "highlights": highlights, "date_range": date_range or ""}
@content_bp.route("/api/consumer_insight_trend", methods=["GET", "POST", "HEAD", "OPTIONS"])
def api_consumer_insight_trend():
    """消费洞察走势：按日/周/月汇总销售额、毛利、动销数、退货率；与 KPI 周期一致（period/start_date/end_date）。
    固定显示总体情况，按粒度（天、周、月）展示走势；品类 Top5 固定为销售额占比最高的 5 个品类，不受品类/品牌下钻影响。"""
    if request.method in ("OPTIONS", "HEAD"):
        return "", 204 if request.method == "OPTIONS" else 200
    granularity = request.args.get("granularity", "week").strip().lower()
    if granularity not in ("day", "week", "month"):
        granularity = "week"
    try:
        days = int(request.args.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    date_cond, date_params, _, _, _ = _ql_query_filters(include_sku=False)
    # 走势固定显示总体：不传 category/brand，仅用日期筛选；params 仅含 store_id + date_params
    cond = " store_id = %s AND " + date_cond
    params = (_effective_store_id(),) + tuple(date_params)
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        # 兼容无 return_amount 列（03_add_full_columns 可能未执行）
        try:
            cur.execute(
                "SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='t_htma_sale' AND COLUMN_NAME='return_amount' LIMIT 1"
            )
            has_return_amount = cur.fetchone() is not None
        except Exception:
            has_return_amount = False
        net_return_sql = (
            "COALESCE(SUM(sale_amount), 0) - COALESCE(SUM(return_amount), 0) AS net_sale, COALESCE(SUM(return_amount), 0) AS return_amt"
            if has_return_amount
            else "COALESCE(SUM(sale_amount), 0) AS net_sale, 0 AS return_amt"
        )
        if granularity == "day":
            cur.execute(
                """
                SELECT data_date AS dt,
                    COALESCE(SUM(sale_amount), 0) AS total_sale,
                    COALESCE(SUM(gross_profit), 0) AS total_profit,
                    COUNT(DISTINCT sku_code) AS sku_sold,
                    """ + net_return_sql + """
                FROM t_htma_sale
                WHERE """ + cond + """
                GROUP BY data_date ORDER BY data_date
            """,
                params,
            )
            rows = cur.fetchall()
            labels = []
            total_sale = []
            total_profit = []
            sku_sold = []
            return_rate = []
            for r in rows:
                dt = r.get("dt")
                labels.append(dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt))
                total_sale.append(round(float(r.get("total_sale") or 0), 2))
                total_profit.append(round(float(r.get("total_profit") or 0), 2))
                sku_sold.append(int(r.get("sku_sold") or 0))
                net = float(r.get("net_sale") or 0)
                ret = float(r.get("return_amt") or 0)
                return_rate.append(round(ret / net * 100, 2) if net > 0 else 0)
        elif granularity == "week":
            cur.execute(
                """
                SELECT YEAR(data_date) AS y, WEEK(data_date, 3) AS w, MIN(data_date) AS week_start,
                    COALESCE(SUM(sale_amount), 0) AS total_sale,
                    COALESCE(SUM(gross_profit), 0) AS total_profit,
                    COUNT(DISTINCT sku_code) AS sku_sold,
                    """ + net_return_sql + """
                FROM t_htma_sale
                WHERE """ + cond + """
                GROUP BY YEAR(data_date), WEEK(data_date, 3)
                ORDER BY week_start
            """,
                params,
            )
            rows = cur.fetchall()
            labels = []
            total_sale = []
            total_profit = []
            sku_sold = []
            return_rate = []
            for r in rows:
                labels.append("%s-W%02d" % (r.get("y"), r.get("w") or 0))
                total_sale.append(round(float(r.get("total_sale") or 0), 2))
                total_profit.append(round(float(r.get("total_profit") or 0), 2))
                sku_sold.append(int(r.get("sku_sold") or 0))
                net = float(r.get("net_sale") or 0)
                ret = float(r.get("return_amt") or 0)
                return_rate.append(round(ret / net * 100, 2) if net > 0 else 0)
        else:
            cur.execute(
                """
                SELECT YEAR(data_date) AS y, MONTH(data_date) AS m, DATE_FORMAT(MIN(data_date), '%%Y-%%m') AS month_key,
                    COALESCE(SUM(sale_amount), 0) AS total_sale,
                    COALESCE(SUM(gross_profit), 0) AS total_profit,
                    COUNT(DISTINCT sku_code) AS sku_sold,
                    """ + net_return_sql + """
                FROM t_htma_sale
                WHERE """ + cond + """
                GROUP BY YEAR(data_date), MONTH(data_date)
                ORDER BY MIN(data_date)
            """,
                params,
            )
            rows = cur.fetchall()
            labels = []
            total_sale = []
            total_profit = []
            sku_sold = []
            return_rate = []
            for r in rows:
                labels.append(r.get("month_key") or "")
                total_sale.append(round(float(r.get("total_sale") or 0), 2))
                total_profit.append(round(float(r.get("total_profit") or 0), 2))
                sku_sold.append(int(r.get("sku_sold") or 0))
                net = float(r.get("net_sale") or 0)
                ret = float(r.get("return_amt") or 0)
                return_rate.append(round(ret / net * 100, 2) if net > 0 else 0)
        by_category = {}
        by_distribution = {}
        # by_category：品类 Top5 走势，单条 SQL 按 (时间维度, 品类) 聚合，减少往返
        if rows and len(rows) <= 120:
            try:
                cur.execute("""
                    SELECT COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category_mid), ''), NULLIF(TRIM(category), ''), '未分类') AS cat
                    FROM t_htma_sale WHERE """ + cond + """
                    GROUP BY cat ORDER BY SUM(sale_amount) DESC LIMIT 5
                """, tuple(params))
                cat_list = [(r.get("cat") or "未分类").strip() for r in cur.fetchall()]
                if cat_list:
                    cat_placeholders = ",".join(["%s"] * len(cat_list))
                    cat_cond = " AND COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category_mid), ''), NULLIF(TRIM(category), ''), '未分类') IN (" + cat_placeholders + ")"
                    p = tuple(params) + tuple(cat_list)
                    if granularity == "day":
                        cur.execute("""
                            SELECT data_date AS dt, COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category_mid), ''), NULLIF(TRIM(category), ''), '未分类') AS cat, COALESCE(SUM(sale_amount), 0) AS v
                            FROM t_htma_sale WHERE """ + cond + cat_cond + """
                            GROUP BY data_date, cat ORDER BY data_date
                        """, p)
                    elif granularity == "week":
                        cur.execute("""
                            SELECT YEAR(data_date) AS y, WEEK(data_date, 3) AS w, MIN(data_date) AS week_start,
                                COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category_mid), ''), NULLIF(TRIM(category), ''), '未分类') AS cat, COALESCE(SUM(sale_amount), 0) AS v
                            FROM t_htma_sale WHERE """ + cond + cat_cond + """
                            GROUP BY YEAR(data_date), WEEK(data_date, 3), cat ORDER BY week_start
                        """, p)
                    else:
                        cur.execute("""
                            SELECT DATE_FORMAT(MIN(data_date), '%%Y-%%m') AS month_key,
                                COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category_mid), ''), NULLIF(TRIM(category), ''), '未分类') AS cat, COALESCE(SUM(sale_amount), 0) AS v
                            FROM t_htma_sale WHERE """ + cond + cat_cond + """
                            GROUP BY YEAR(data_date), MONTH(data_date), cat ORDER BY MIN(data_date)
                        """, p)
                    cat_rows = cur.fetchall()
                    from collections import defaultdict
                    cat_to_map = defaultdict(dict)
                    for x in cat_rows:
                        cat = (x.get("cat") or "未分类").strip()
                        v = round(float(x.get("v") or 0), 2)
                        if granularity == "day":
                            k = x.get("dt")
                            k = k.strftime("%Y-%m-%d") if hasattr(k, "strftime") else str(k)
                        elif granularity == "week":
                            k = "%s-W%02d" % (x.get("y"), x.get("w") or 0)
                        else:
                            k = x.get("month_key") or ""
                        cat_to_map[cat][k] = v
                    for cat in cat_list:
                        by_category[cat[:16]] = [cat_to_map[cat].get(lb, 0) for lb in labels]
            except Exception:
                by_category = {}
            # 经销方式走势已移除：依赖 distribution_mode，生产库缺列易导致 500；主走势与品类 Top5 不依赖
        cur.close()
        empty_hint = "所选条件下无销售数据，请调整周期或品类筛选后再试。" if not labels else None
        return jsonify({
            "granularity": granularity,
            "days": days,
            "labels": labels,
            "series": {"total_sale": total_sale, "total_profit": total_profit, "sku_sold": sku_sold, "return_rate": return_rate},
            "by_category": by_category,
            "by_distribution": by_distribution,
            "seasonality_note": "按月查看可观察季节性；积累 12 个月以上数据后可做同比与季节指数。" if granularity == "month" else None,
            "data_source": "sale",
            "empty_hint": empty_hint,
        })
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return jsonify({"error": str(e), "traceback": tb, "labels": [], "series": {}, "by_category": {}, "by_distribution": [], "empty_hint": "请求异常，请稍后重试。"}), 500
    finally:
        conn.close()
def _get_consumer_insight_data(param_override=None):
    """消费洞察：概览 KPI、品类贡献、品牌贡献、价格带、经销方式、新品表现。与经营分析/税率同周期。
    param_override: 可选 dict，含 period/start_date/end_date/category/brand/product_name，用于非 request 调用（如结构化报告）。"""
    if param_override:
        date_cond, date_params, params, category_cond, _ = _ql_query_filters_from_params(
            period=param_override.get("period") or "recent30",
            start_date=param_override.get("start_date"),
            end_date=param_override.get("end_date"),
            category=param_override.get("category"),
            brand=param_override.get("brand"),
            category_large_code=param_override.get("category_large_code"),
            category_mid_code=param_override.get("category_mid_code"),
            category_small_code=param_override.get("category_small_code"),
        )
        if params and params[0] is None:
            params = (_effective_store_id(),) + tuple(params[1:])
    else:
        date_cond, date_params, params, category_cond, _ = _ql_query_filters(include_sku=False)
    date_only_params = (_effective_store_id(),) + tuple(date_params)
    conn = get_conn()
    try:
        _ensure_product_master_distribution_mode(conn)
    except Exception:
        pass
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        category_matrix = []
        discount_band = []
        zero_sale_skus = []
        high_discount_low_margin = []
        # 1. 概览
        cur.execute(f"""
            SELECT
                COALESCE(SUM(sale_amount), 0) AS total_sale,
                COALESCE(SUM(gross_profit), 0) AS total_profit,
                COUNT(DISTINCT sku_code) AS sku_sold,
                COALESCE(SUM(sale_qty), 0) AS total_qty
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
        """, params)
        row = cur.fetchone()
        total_sale = float(row.get("total_sale") or 0)
        total_profit = float(row.get("total_profit") or 0)
        sku_sold = int(row.get("sku_sold") or 0)
        total_qty = float(row.get("total_qty") or 0)
        margin_pct = (total_profit / total_sale * 100) if total_sale > 0 else 0
        unit_price = (total_sale / total_qty) if total_qty > 0 else 0
        # 商品主数据总数（动销率分母）
        cur.execute("SELECT COUNT(*) AS c FROM t_htma_product_master WHERE store_id = %s", (_effective_store_id(),))
        r2 = cur.fetchone()
        sku_total = int(r2.get("c") or 0)
        sell_through_pct = (sku_sold / sku_total * 100) if sku_total > 0 else None
        # 平均零售价（商品主数据）
        cur.execute("SELECT AVG(retail_price) AS avg_retail FROM t_htma_product_master WHERE store_id = %s AND COALESCE(retail_price, 0) > 0", (_effective_store_id(),))
        r_retail = cur.fetchone()
        avg_retail_price = round(float(r_retail.get("avg_retail") or 0), 2) if r_retail and r_retail.get("avg_retail") else None
        # 库存周转天数（近期库存/日均销量）
        try:
            cur.execute("SELECT COALESCE(SUM(stock_qty), 0) AS total_stock FROM t_htma_stock WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)", (_effective_store_id(), _effective_store_id()))
            stock_row = cur.fetchone()
            total_stock = float(stock_row.get("total_stock") or 0)
            interval_days = max(1, int(date_params[0]) if date_params and isinstance(date_params[0], (int, float)) else 30)
            daily_sale_qty = total_qty / interval_days if interval_days else 0
            inventory_turnover_days = round(total_stock / daily_sale_qty, 1) if daily_sale_qty > 0 and total_stock >= 0 else None
        except Exception:
            inventory_turnover_days = None
        s_date_cond = date_cond.replace("data_date", "s.data_date")
        overview = {
            "total_sale": round(total_sale, 2),
            "total_qty": round(total_qty, 2),
            "total_profit": round(total_profit, 2),
            "margin_pct": round(margin_pct, 2),
            "sku_sold": sku_sold,
            "sku_total": sku_total,
            "sell_through_pct": round(sell_through_pct, 2) if sell_through_pct is not None else None,
            "unit_price": round(unit_price, 2),
            "avg_retail_price": avg_retail_price,
            "inventory_turnover_days": inventory_turnover_days,
        }
        # 2. 品类贡献矩阵（动销SKU、销量、销售额、占比、毛利、毛利率、平均售价、平均折扣率）；支持一级下钻
        cur.execute(f"""
            SELECT
                COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category_mid), ''), NULLIF(TRIM(category), ''), '未分类') AS cat,
                COUNT(DISTINCT sku_code) AS sku_sold,
                COALESCE(SUM(sale_qty), 0) AS qty,
                SUM(sale_amount) AS sale_amount,
                SUM(gross_profit) AS profit,
                CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct,
                AVG(sale_price) AS avg_sale_price
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
            GROUP BY cat
            HAVING SUM(sale_amount) > 0
            ORDER BY sale_amount DESC
            LIMIT 20
        """, params)
        cat_matrix_rows = cur.fetchall()
        total_sale_for_contrib = total_sale or 1
        total_profit_for_contrib = max(1, sum(float(x.get("profit") or 0) for x in cat_matrix_rows))
        category_matrix = []
        for r in cat_matrix_rows:
            cat = r.get("cat") or "未分类"
            sale_amt = float(r.get("sale_amount") or 0)
            profit_amt = float(r.get("profit") or 0)
            category_matrix.append({
                "category": cat,
                "sku_sold": int(r.get("sku_sold") or 0),
                "qty": round(float(r.get("qty") or 0), 2),
                "sale_amount": round(sale_amt, 2),
                "sale_contrib_pct": round(sale_amt / total_sale_for_contrib * 100, 2),
                "profit": round(profit_amt, 2),
                "profit_contrib_pct": round(profit_amt / total_profit_for_contrib * 100, 2),
                "margin_pct": round(float(r.get("margin_pct") or 0), 2),
                "avg_sale_price": round(float(r.get("avg_sale_price") or 0), 2),
                "avg_discount_pct": None,
            })
        # 品类平均折扣率（按品类 join 主数据）
        try:
            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(TRIM(s.category_large), ''), NULLIF(TRIM(s.category_mid), ''), NULLIF(TRIM(s.category), ''), '未分类') AS cat,
                    SUM(s.sale_amount * (1 - s.sale_price / NULLIF(m.list_price, 0))) / NULLIF(SUM(s.sale_amount), 0) * 100 AS avg_discount_pct
                FROM t_htma_sale s
                INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND COALESCE(m.list_price, 0) > 0
                WHERE s.store_id = %s AND {s_date_cond}
                GROUP BY cat
            """, date_only_params)
            for row in cur.fetchall():
                c = row.get("cat") or "未分类"
                for cm in category_matrix:
                    if cm["category"] == c:
                        cm["avg_discount_pct"] = round(float(row.get("avg_discount_pct") or 0), 2)
                        break
        except Exception:
            pass
        category_top_sale = [{"category": c["category"], "sale_amount": c["sale_amount"], "profit": c["profit"], "margin_pct": c["margin_pct"], "sale_contrib_pct": c.get("sale_contrib_pct"), "profit_contrib_pct": c.get("profit_contrib_pct")} for c in category_matrix[:10]]
        category_top_profit = sorted([{"category": c["category"], "sale_amount": c["sale_amount"], "profit": c["profit"], "margin_pct": c["margin_pct"]} for c in category_matrix], key=lambda x: x["profit"], reverse=True)[:10]
        category_top_margin = sorted([{"category": c["category"], "sale_amount": c["sale_amount"], "profit": c["profit"], "margin_pct": c["margin_pct"]} for c in category_matrix if c["margin_pct"] > 0], key=lambda x: x["margin_pct"], reverse=True)[:5]
        # 3. 品牌贡献（含 sku_sold 供气泡图）
        cur.execute(f"""
            SELECT
                COALESCE(NULLIF(TRIM(brand_name), ''), '未分类') AS brand,
                COUNT(DISTINCT sku_code) AS sku_sold,
                SUM(sale_amount) AS sale_amount,
                SUM(gross_profit) AS profit,
                SUM(sale_qty) AS qty,
                CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
            GROUP BY brand
            HAVING SUM(sale_amount) > 0
            ORDER BY sale_amount DESC
            LIMIT 30
        """, params)
        brand_rows = cur.fetchall()
        brand = [{"brand": r.get("brand") or "未分类", "sku_sold": int(r.get("sku_sold") or 0), "sale_amount": round(float(r.get("sale_amount") or 0), 2), "profit": round(float(r.get("profit") or 0), 2), "qty": round(float(r.get("qty") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2), "contrib_pct": round(float(r.get("sale_amount") or 0) / total_sale_for_contrib * 100, 2)} for r in brand_rows]
        # 4. 价格带（按实际售价分段）：销售额、销量、SKU数占比、销售额占比、毛利率、平均折扣率
        cur.execute(f"""
            SELECT
                CASE
                    WHEN COALESCE(sale_price, 0) <= 0 THEN '0'
                    WHEN sale_price < 50 THEN '1-49'
                    WHEN sale_price < 100 THEN '50-99'
                    WHEN sale_price < 200 THEN '100-199'
                    WHEN sale_price < 500 THEN '200-499'
                    WHEN sale_price < 1000 THEN '500-999'
                    ELSE '1000+'
                END AS band,
                COUNT(DISTINCT sku_code) AS sku_count,
                SUM(sale_amount) AS sale_amount,
                SUM(sale_qty) AS qty,
                CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
            GROUP BY band
            ORDER BY FIELD(band, '0', '1-49', '50-99', '100-199', '200-499', '500-999', '1000+')
        """, params)
        price_rows = cur.fetchall()
        total_qty_for_band = total_qty or 1
        total_sku_bands = sum(int(r.get("sku_count") or 0) for r in price_rows) or 1
        price_band = [{"band": r.get("band") or "0", "sku_count": int(r.get("sku_count") or 0), "sale_amount": round(float(r.get("sale_amount") or 0), 2), "qty": round(float(r.get("qty") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2), "avg_discount_pct": None} for r in price_rows]
        for pb in price_band:
            pb["sale_contrib_pct"] = round(pb["sale_amount"] / total_sale_for_contrib * 100, 2) if total_sale > 0 else 0
            pb["qty_contrib_pct"] = round(pb["qty"] / total_qty_for_band * 100, 2) if total_qty > 0 else 0
            pb["sku_contrib_pct"] = round(pb["sku_count"] / total_sku_bands * 100, 2)
        try:
            cur.execute(f"""
                SELECT
                    CASE WHEN COALESCE(s.sale_price, 0) <= 0 THEN '0' WHEN s.sale_price < 50 THEN '1-49' WHEN s.sale_price < 100 THEN '50-99' WHEN s.sale_price < 200 THEN '100-199' WHEN s.sale_price < 500 THEN '200-499' WHEN s.sale_price < 1000 THEN '500-999' ELSE '1000+'
                    END AS band,
                    SUM(s.sale_amount * (1 - s.sale_price / NULLIF(m.list_price, 0))) / NULLIF(SUM(s.sale_amount), 0) * 100 AS avg_discount_pct
                FROM t_htma_sale s
                INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND COALESCE(m.list_price, 0) > 0 AND s.sale_price <= m.list_price
                WHERE s.store_id = %s AND {s_date_cond}
                GROUP BY band
            """, date_only_params)
            for row in cur.fetchall():
                b = row.get("band") or "0"
                for pb in price_band:
                    if pb["band"] == b:
                        pb["avg_discount_pct"] = round(float(row.get("avg_discount_pct") or 0), 2)
                        break
        except Exception:
            pass
        # 4b. 供应商贡献（与品牌同维）
        cur.execute(f"""
            SELECT
                COALESCE(NULLIF(TRIM(supplier_name), ''), '未填') AS supplier,
                SUM(sale_amount) AS sale_amount,
                SUM(gross_profit) AS profit,
                SUM(sale_qty) AS qty,
                CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
            GROUP BY supplier
            HAVING SUM(sale_amount) > 0
            ORDER BY sale_amount DESC
            LIMIT 20
        """, params)
        supplier_rows = cur.fetchall()
        supplier = [{"supplier": r.get("supplier") or "未填", "sale_amount": round(float(r.get("sale_amount") or 0), 2), "profit": round(float(r.get("profit") or 0), 2), "qty": round(float(r.get("qty") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2), "contrib_pct": round(float(r.get("sale_amount") or 0) / total_sale_for_contrib * 100, 2)} for r in supplier_rows]
        # 4c. 单品销售 Top20（SKU 维度）
        cur.execute(f"""
            SELECT
                sku_code,
                COALESCE(NULLIF(TRIM(product_name), ''), sku_code) AS product_name,
                SUM(sale_amount) AS sale_amount,
                SUM(gross_profit) AS profit,
                SUM(sale_qty) AS qty,
                CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
            GROUP BY sku_code, product_name
            HAVING SUM(sale_amount) > 0
            ORDER BY sale_amount DESC
            LIMIT 20
        """, params)
        sku_rows = cur.fetchall()
        top_sku = [{"sku_code": r.get("sku_code") or "", "product_name": (r.get("product_name") or "")[:40], "sale_amount": round(float(r.get("sale_amount") or 0), 2), "profit": round(float(r.get("profit") or 0), 2), "qty": round(float(r.get("qty") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2)} for r in sku_rows]
        # 4d. 平均折扣率（sale 关联 product_master.list_price，有划线价的记录）
        try:
            cur.execute(f"""
                SELECT
                    SUM(s.sale_amount) AS sale_with_list,
                    SUM(s.sale_qty) AS qty_with_list,
                    SUM(s.sale_amount * (1 - s.sale_price / NULLIF(m.list_price, 0))) / NULLIF(SUM(s.sale_amount), 0) * 100 AS avg_discount_pct
                FROM t_htma_sale s
                INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND COALESCE(m.list_price, 0) > 0 AND s.sale_price <= m.list_price
                WHERE s.store_id = %s AND {s_date_cond}
            """, date_only_params)
            dr = cur.fetchone()
            if dr and float(dr.get("sale_with_list") or 0) > 0:
                avg_discount_pct = round(float(dr.get("avg_discount_pct") or 0), 2)
            else:
                avg_discount_pct = None
        except Exception:
            avg_discount_pct = None
        overview["avg_discount_pct"] = avg_discount_pct
        # 5. 经销方式（代销/购销 销售额占比、毛利率、平均售价对比）；distribution_mode 缺列时静默回退
        try:
            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(TRIM(m.distribution_mode), ''), '未分类') AS mode_name,
                    SUM(s.sale_amount) AS sale_amount,
                    SUM(s.sale_qty) AS sale_qty,
                    SUM(s.gross_profit) AS profit,
                    CASE WHEN SUM(s.sale_amount) > 0 THEN SUM(s.gross_profit)/SUM(s.sale_amount)*100 ELSE 0 END AS margin_pct
                FROM t_htma_sale s
                LEFT JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id
                WHERE s.store_id = %s AND {s_date_cond}
                GROUP BY mode_name
                HAVING SUM(s.sale_amount) > 0
                ORDER BY sale_amount DESC
            """, date_only_params)
        except Exception:
            cur.execute(f"""
                SELECT
                    '购销' AS mode_name,
                    SUM(sale_amount) AS sale_amount,
                    COALESCE(SUM(sale_qty), 0) AS sale_qty,
                    SUM(gross_profit) AS profit,
                    CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}
            """, (_effective_store_id(),) + tuple(date_params))
        dist_rows = cur.fetchall()
        distribution = []
        for r in dist_rows:
            amt = float(r.get("sale_amount") or 0)
            qty = float(r.get("sale_qty") or 0)
            distribution.append({
                "mode": r.get("mode_name") or "未分类",
                "sale_amount": round(amt, 2),
                "profit": round(float(r.get("profit") or 0), 2),
                "margin_pct": round(float(r.get("margin_pct") or 0), 2),
                "contrib_pct": round(amt / total_sale_for_contrib * 100, 2),
                "avg_sale_price": round(amt / qty, 2) if qty > 0 else None,
            })
        # 6. 新品表现（关联商品主数据 product_status=新品）
        try:
            cur.execute(f"""
                SELECT
                    SUM(s.sale_amount) AS new_sale,
                    SUM(s.gross_profit) AS new_profit,
                    COUNT(DISTINCT s.sku_code) AS new_sku_sold
                FROM t_htma_sale s
                INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND TRIM(COALESCE(m.product_status,'')) = '新品'
                WHERE s.store_id = %s AND {s_date_cond}
            """, date_only_params)
            nr = cur.fetchone()
            new_sale = float(nr.get("new_sale") or 0)
            new_profit = float(nr.get("new_profit") or 0)
            new_sku_sold = int(nr.get("new_sku_sold") or 0)
            cur.execute("SELECT COUNT(*) AS c FROM t_htma_product_master WHERE store_id = %s AND TRIM(COALESCE(product_status,'')) = '新品'", (_effective_store_id(),))
            new_sku_total = int(cur.fetchone().get("c") or 0)
        except Exception:
            new_sale = new_profit = 0
            new_sku_sold = new_sku_total = 0
        new_product = {
            "new_sale": round(new_sale, 2),
            "new_profit": round(new_profit, 2),
            "new_sale_contrib_pct": round(new_sale / total_sale_for_contrib * 100, 2) if total_sale > 0 else 0,
            "new_margin_pct": round(new_profit / new_sale * 100, 2) if new_sale > 0 else 0,
            "new_sku_sold": new_sku_sold,
            "new_sku_total": new_sku_total,
            "new_sell_through_pct": round(new_sku_sold / new_sku_total * 100, 2) if new_sku_total > 0 else None,
        }
        # 6b. 老品销售额占比（非新品）
        old_sale = total_sale - new_sale
        new_product["old_sale_contrib_pct"] = round(old_sale / total_sale_for_contrib * 100, 2) if total_sale > 0 else 0
        # 7. 退货率（整体 + 按品类）
        cur.execute(f"""
            SELECT
                COALESCE(SUM(return_amount), 0) AS total_return,
                COALESCE(SUM(return_qty), 0) AS total_return_qty
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
        """, params)
        ret_row = cur.fetchone()
        total_return = float(ret_row.get("total_return") or 0)
        return_rate_pct = round(total_return / total_sale_for_contrib * 100, 2) if total_sale > 0 else 0
        cur.execute(f"""
            SELECT
                COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category_mid), ''), NULLIF(TRIM(category), ''), '未分类') AS cat,
                SUM(sale_amount) AS sale_amount,
                SUM(return_amount) AS return_amount,
                CASE WHEN SUM(sale_amount) > 0 THEN SUM(return_amount)/SUM(sale_amount)*100 ELSE 0 END AS return_rate_pct
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
            GROUP BY cat
            HAVING SUM(sale_amount) > 0 AND SUM(return_amount) > 0
            ORDER BY return_amount DESC
            LIMIT 10
        """, params)
        return_by_cat = [{"category": r.get("cat") or "未分类", "sale_amount": round(float(r.get("sale_amount") or 0), 2), "return_amount": round(float(r.get("return_amount") or 0), 2), "return_rate_pct": round(float(r.get("return_rate_pct") or 0), 2)} for r in cur.fetchall()]
        # 8. 色系/风格（有字段则查）
        color_style = {}
        try:
            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(TRIM(color_system), ''), '未填') AS k,
                    SUM(sale_amount) AS sale_amount,
                    CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}
                GROUP BY k HAVING SUM(sale_amount) > 0 ORDER BY sale_amount DESC LIMIT 10
            """, params)
            color_style["color_system"] = [{"name": r.get("k") or "未填", "sale_amount": round(float(r.get("sale_amount") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2)} for r in cur.fetchall()]
        except Exception:
            color_style["color_system"] = []
        try:
            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(TRIM(style), ''), '未填') AS k,
                    SUM(sale_amount) AS sale_amount,
                    CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}
                GROUP BY k HAVING SUM(sale_amount) > 0 ORDER BY sale_amount DESC LIMIT 10
            """, params)
            color_style["style"] = [{"name": r.get("k") or "未填", "sale_amount": round(float(r.get("sale_amount") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2)} for r in cur.fetchall()]
        except Exception:
            color_style["style"] = []
        # 8b. 折扣区间分析（0-10%、10-20%、20-30%、30%+）
        discount_band = []
        try:
            cur.execute(f"""
                SELECT
                    CASE
                        WHEN (1 - s.sale_price / NULLIF(m.list_price, 0)) * 100 < 0 THEN '0-10%%'
                        WHEN (1 - s.sale_price / NULLIF(m.list_price, 0)) * 100 < 10 THEN '0-10%%'
                        WHEN (1 - s.sale_price / NULLIF(m.list_price, 0)) * 100 < 20 THEN '10-20%%'
                        WHEN (1 - s.sale_price / NULLIF(m.list_price, 0)) * 100 < 30 THEN '20-30%%'
                        ELSE '30%%+'
                    END AS band,
                    COUNT(DISTINCT s.sku_code) AS sku_cnt,
                    SUM(s.sale_amount) AS sale_amount,
                    SUM(s.gross_profit) AS profit,
                    SUM(s.sale_qty) AS qty,
                    CASE WHEN SUM(s.sale_amount) > 0 THEN SUM(s.gross_profit)/SUM(s.sale_amount)*100 ELSE 0 END AS margin_pct
                FROM t_htma_sale s
                INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND COALESCE(m.list_price, 0) > 0
                WHERE s.store_id = %s AND {s_date_cond}
                GROUP BY band
                ORDER BY FIELD(band, '0-10%%', '10-20%%', '20-30%%', '30%%+')
            """, date_only_params)
            for r in cur.fetchall():
                discount_band.append({
                    "band": r.get("band") or "0-10%",
                    "sku_cnt": int(r.get("sku_cnt") or 0),
                    "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                    "profit": round(float(r.get("profit") or 0), 2),
                    "qty": round(float(r.get("qty") or 0), 2),
                    "margin_pct": round(float(r.get("margin_pct") or 0), 2),
                })
        except Exception:
            pass
        # 8c. 零销售商品（主数据中有、本周期内无销售的 SKU，限 100 条）；用 date_params 避免与 category/brand 混淆
        try:
            use_date_range = len(date_params) == 2 and all(isinstance(x, str) and "-" in str(x) for x in date_params)
            if use_date_range:
                cur.execute("""
                    SELECT pm.sku_code, pm.product_name, pm.category_name, pm.brand_name, pm.retail_price
                    FROM t_htma_product_master pm
                    LEFT JOIN (SELECT DISTINCT sku_code FROM t_htma_sale WHERE store_id = %s AND data_date BETWEEN %s AND %s) s ON pm.sku_code = s.sku_code
                    WHERE pm.store_id = %s AND s.sku_code IS NULL
                    LIMIT 100
                """, (_effective_store_id(), date_params[0], date_params[1], _effective_store_id()))
            else:
                interval_days = int(date_params[0]) if date_params and isinstance(date_params[0], (int, float)) else 30
                cur.execute("""
                    SELECT pm.sku_code, pm.product_name, pm.category_name, pm.brand_name, pm.retail_price
                    FROM t_htma_product_master pm
                    LEFT JOIN (SELECT DISTINCT sku_code FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)) s ON pm.sku_code = s.sku_code
                    WHERE pm.store_id = %s AND s.sku_code IS NULL
                    LIMIT 100
                """, (_effective_store_id(), interval_days, _effective_store_id()))
            for r in cur.fetchall():
                zero_sale_skus.append({
                    "sku_code": r.get("sku_code") or "",
                    "product_name": (r.get("product_name") or "")[:50],
                    "category_name": (r.get("category_name") or "")[:32],
                    "brand_name": (r.get("brand_name") or "")[:32],
                    "retail_price": round(float(r.get("retail_price") or 0), 2),
                })
        except Exception:
            pass
        # 8d. 高折扣低毛利（平均折扣>30% 且 毛利率<10%，按 SKU 汇总取前 50）
        high_discount_low_margin = []
        try:
            cur.execute(f"""
                SELECT
                    s.sku_code,
                    MAX(s.product_name) AS product_name,
                    SUM(s.sale_amount) AS sale_amount,
                    SUM(s.gross_profit) AS profit,
                    CASE WHEN SUM(s.sale_amount) > 0 THEN SUM(s.gross_profit)/SUM(s.sale_amount)*100 ELSE 0 END AS margin_pct,
                    AVG((1 - s.sale_price / NULLIF(m.list_price, 0)) * 100) AS avg_discount_pct
                FROM t_htma_sale s
                INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND COALESCE(m.list_price, 0) > 0
                WHERE s.store_id = %s AND {s_date_cond}
                GROUP BY s.sku_code
                HAVING margin_pct < 10 AND avg_discount_pct > 30
                ORDER BY sale_amount DESC
                LIMIT 50
            """, date_only_params)
            for r in cur.fetchall():
                high_discount_low_margin.append({
                    "sku_code": r.get("sku_code") or "",
                    "product_name": (r.get("product_name") or "")[:40],
                    "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                    "profit": round(float(r.get("profit") or 0), 2),
                    "margin_pct": round(float(r.get("margin_pct") or 0), 2),
                    "avg_discount_pct": round(float(r.get("avg_discount_pct") or 0), 2),
                })
        except Exception:
            try:
                cur.execute(f"""
                    SELECT s.sku_code, MAX(s.product_name) AS product_name, SUM(s.sale_amount) AS sale_amount, SUM(s.gross_profit) AS profit,
                    CASE WHEN SUM(s.sale_amount) > 0 THEN SUM(s.gross_profit)/SUM(s.sale_amount)*100 ELSE 0 END AS margin_pct
                    FROM t_htma_sale s
                    INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND COALESCE(m.list_price, 0) > 0
                    WHERE s.store_id = %s AND {s_date_cond} AND s.sale_price <= m.list_price * 0.7
                    GROUP BY s.sku_code
                    HAVING margin_pct < 10
                    ORDER BY sale_amount DESC LIMIT 50
                """, date_only_params)
                for r in cur.fetchall():
                    high_discount_low_margin.append({
                        "sku_code": r.get("sku_code") or "",
                        "product_name": (r.get("product_name") or "")[:40],
                        "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                        "profit": round(float(r.get("profit") or 0), 2),
                        "margin_pct": round(float(r.get("margin_pct") or 0), 2),
                    })
            except Exception:
                pass
        # 9. 环比趋势（本期 vs 上期同长度：近30天则对比前30天）；用 date_params 避免与 category/brand 混淆
        period_over_period = {}
        try:
            interval_days = int(date_params[0]) if date_params and isinstance(date_params[0], (int, float)) else 30
            if interval_days >= 1:
                cur.execute("""
                    SELECT COALESCE(SUM(sale_amount), 0) AS prev_sale
                    FROM t_htma_sale
                    WHERE store_id = %s AND data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL %s DAY) AND DATE_SUB(CURDATE(), INTERVAL %s DAY)
                """, (_effective_store_id(), interval_days * 2, interval_days + 1))
                prev_row = cur.fetchone()
                prev_sale = float(prev_row.get("prev_sale") or 0)
                pct_change = round((total_sale - prev_sale) / prev_sale * 100, 2) if prev_sale > 0 else None
                period_over_period = {"prev_sale": round(prev_sale, 2), "pct_change": pct_change}
        except Exception:
            period_over_period = {}
        # 日期范围文案（与税率计算一致：自定义用 start_date~end_date，否则用 period 标签）
        if param_override:
            start_d = (param_override.get("start_date") or "").strip()
            end_d = (param_override.get("end_date") or "").strip()
            period = (param_override.get("period") or "recent30").strip()
        else:
            start_d = (request.args.get("start_date") or "").strip()
            end_d = (request.args.get("end_date") or "").strip()
            period = request.args.get("period", "recent30")
        date_range = f"{start_d} ~ {end_d}" if (start_d and end_d) else {"day": "今日", "week": "本周", "month": "本月", "recent30": "近30天"}.get(period, "近30天")
        bi_insight = _build_bi_insight(overview, period_over_period, category_matrix, return_rate_pct, distribution, date_range)
        # 下钻层级：品类 → 品牌 → 款式(品名) → 货号明细
        drill_brands = []
        drill_styles = []
        drill_subcategory = []
        drill_sku_rank = []
        if param_override:
            category_name = (param_override.get("category") or "").strip()
            brand_name = (param_override.get("brand") or "").strip()
            product_name = (param_override.get("product_name") or "").strip()
        else:
            category_name = (request.args.get("category") or "").strip()
            brand_name = (request.args.get("brand") or "").strip()
            product_name = (request.args.get("product_name") or "").strip()
        try:
            if category_name:
                # 二级：该品类下品牌列表（点击品牌进入三级）
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(brand_name), ''), '未填') AS brand,
                           COUNT(DISTINCT sku_code) AS sku_sold, COALESCE(SUM(sale_qty), 0) AS qty,
                           SUM(sale_amount) AS sale_amount, SUM(gross_profit) AS profit,
                           CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}
                    GROUP BY COALESCE(NULLIF(TRIM(brand_name), ''), '未填')
                    HAVING SUM(sale_amount) > 0
                    ORDER BY SUM(sale_amount) DESC
                    LIMIT 50
                """, params)
                for r in cur.fetchall():
                    drill_brands.append({
                        "brand": r.get("brand") or "未填",
                        "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                        "profit": round(float(r.get("profit") or 0), 2),
                        "qty": round(float(r.get("qty") or 0), 2),
                        "margin_pct": round(float(r.get("margin_pct") or 0), 2),
                        "sku_sold": int(r.get("sku_sold") or 0),
                    })
            if category_name and brand_name and not product_name:
                # 三级：该品类+品牌下款式(品名)列表（点击款式进入四级）
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(product_name), ''), '未填') AS style_name,
                           COUNT(DISTINCT sku_code) AS sku_sold, COALESCE(SUM(sale_qty), 0) AS qty,
                           SUM(sale_amount) AS sale_amount, SUM(gross_profit) AS profit,
                           CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}
                    GROUP BY COALESCE(NULLIF(TRIM(product_name), ''), '未填')
                    HAVING SUM(sale_amount) > 0
                    ORDER BY SUM(sale_amount) DESC
                    LIMIT 100
                """, params)
                for r in cur.fetchall():
                    drill_styles.append({
                        "product_name": r.get("style_name") or "未填",
                        "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                        "profit": round(float(r.get("profit") or 0), 2),
                        "qty": round(float(r.get("qty") or 0), 2),
                        "margin_pct": round(float(r.get("margin_pct") or 0), 2),
                        "sku_sold": int(r.get("sku_sold") or 0),
                    })
            if category_name and brand_name and product_name:
                # 四级：该品类+品牌+款式下货号明细（表头可展示品牌、款式）
                product_cond = " AND TRIM(COALESCE(product_name, '')) = %s"
                params_sku = params + (product_name,)
                cur.execute(f"""
                    SELECT sku_code, COALESCE(MAX(product_name), '') AS product_name, COALESCE(MAX(brand_name), '') AS brand_name,
                           SUM(sale_amount) AS sale_amount, SUM(gross_profit) AS profit, SUM(sale_qty) AS qty,
                           CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{product_cond}
                    GROUP BY sku_code
                    HAVING SUM(sale_amount) > 0
                    ORDER BY SUM(sale_amount) DESC
                    LIMIT 100
                """, params_sku)
                for r in cur.fetchall():
                    drill_sku_rank.append({
                        "sku_code": r.get("sku_code") or "",
                        "product_name": (r.get("product_name") or "").strip() or "-",
                        "brand_name": (r.get("brand_name") or "").strip() or "-",
                        "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                        "profit": round(float(r.get("profit") or 0), 2),
                        "qty": round(float(r.get("qty") or 0), 2),
                        "margin_pct": round(float(r.get("margin_pct") or 0), 2),
                        "avg_discount_pct": None,
                    })
                try:
                    sku_list = [row["sku_code"] for row in drill_sku_rank]
                    if sku_list:
                        placeholders = ",".join(["%s"] * len(sku_list))
                        cur.execute("""
                            SELECT s.sku_code, AVG(1 - s.sale_price / NULLIF(p.list_price, 0)) * 100 AS avg_discount_pct
                            FROM t_htma_sale s
                            INNER JOIN t_htma_product_master p ON p.sku_code = s.sku_code AND p.store_id = s.store_id AND COALESCE(p.list_price, 0) > 0
                            WHERE s.store_id = %s AND s.sku_code IN (""" + placeholders + """)
                            GROUP BY s.sku_code
                        """, (_effective_store_id(),) + tuple(sku_list))
                        discount_map = {r.get("sku_code"): round(float(r.get("avg_discount_pct") or 0), 2) for r in cur.fetchall()}
                        for row in drill_sku_rank:
                            row["avg_discount_pct"] = discount_map.get(row["sku_code"])
                except Exception:
                    pass
        except Exception:
            drill_brands = []
            drill_styles = []
            drill_sku_rank = []
        return {
            "overview": overview,
            "bi_insight": bi_insight,
            "category_matrix": category_matrix,
            "category_top_sale": category_top_sale,
            "category_top_profit": category_top_profit,
            "category_top_margin": category_top_margin,
            "brand": brand,
            "price_band": price_band,
            "supplier": supplier,
            "top_sku": top_sku,
            "distribution": distribution,
            "new_product": new_product,
            "return_rate_pct": return_rate_pct,
            "return_by_cat": return_by_cat,
            "color_style": color_style,
            "period_over_period": period_over_period,
            "date_range": date_range,
            "discount_band": discount_band,
            "zero_sale_skus": zero_sale_skus,
            "high_discount_low_margin": high_discount_low_margin,
            "drill_brands": drill_brands,
            "drill_styles": drill_styles,
            "drill_subcategory": drill_subcategory,
            "drill_sku_rank": drill_sku_rank,
        }
    finally:
        conn.close()


