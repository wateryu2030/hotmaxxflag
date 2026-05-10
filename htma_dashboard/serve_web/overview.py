# -*- coding: utf-8 -*-
"""概览 API — serve_web/overview：KPI、品类占比、趋势、环比"""

from flask import Blueprint, jsonify, request
from datetime import date, datetime, timedelta

from core.db import get_conn
from core.context import (
    _effective_store_id, _query_filters, _profit_category_cond_and_params,
    _inv_category_cond_and_params, period_over_period_ranges,
)
from core.cache import _cache_get, _cache_set
from core.utils import safe_int, safe_float, safe_str

overview_bp = Blueprint("overview", __name__)

@overview_bp.route("/api/date_range")
def api_date_range():
    """返回自定义日期选择器的可选范围；起止默认值为库中有数据的最早/最晚日期（销售表）。缓存 60 秒。"""
    sid = _effective_store_id()
    cache_key = "date_range:" + (sid or "")
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)
    out = {"min_date": "2010-01-01", "max_date": "2030-12-31", "data_min_date": None, "data_max_date": None}
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MIN(data_date) AS min_d, MAX(data_date) AS max_d FROM t_htma_sale WHERE store_id = %s",
                (sid,),
            )
            row = cur.fetchone()
        conn.close()
        if row and row.get("min_d") and row.get("max_d"):
            out["data_min_date"] = row["min_d"].strftime("%Y-%m-%d") if hasattr(row["min_d"], "strftime") else str(row["min_d"])[:10]
            out["data_max_date"] = row["max_d"].strftime("%Y-%m-%d") if hasattr(row["max_d"], "strftime") else str(row["max_d"])[:10]
    except Exception:
        pass
    _cache_set(cache_key, out)
    return jsonify(out)


@overview_bp.route("/api/kpi")
def api_kpi():
    """4 个 KPI：总销售额、总毛利、平均毛利率、库存总额。支持 period、start_date、end_date、category 及 hierarchy。非自定义周期时缓存 60 秒。"""
    sid = _effective_store_id()
    period = request.args.get("period", "recent30")
    start_d = request.args.get("start_date", "").strip()
    end_d = request.args.get("end_date", "").strip()
    use_cache = (period != "custom" and not (start_d and end_d))
    if use_cache:
        cache_key = "kpi:%s:%s:%s:%s:%s:%s" % (
            sid or "", period,
            request.args.get("category_large_code", ""),
            request.args.get("category_mid_code", ""),
            request.args.get("category_small_code", ""),
            request.args.get("sku_code", ""),
        )
        cached = _cache_get(cache_key)
        if cached is not None:
            return jsonify(cached)
    date_cond, date_params, params, sale_cat_cond, sku_cond = _query_filters()
    # 总销售额、总毛利直接从 t_htma_sale 聚合，与手工统计、导入明细一致，避免与 t_htma_profit 不同步导致显示不一致
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    inv_cond, inv_params, need_join = _inv_category_cond_and_params()
    sku_code = request.args.get("sku_code", "").strip()
    conn = get_conn()
    try:
        total_sale = None
        total_profit = None
        if not sale_cat_cond and not sku_cond:
            try:
                from daily_stats_service import try_totals_from_daily_stats

                _pair = try_totals_from_daily_stats(conn, sid, period, start_d, end_d)
                if _pair is not None:
                    total_sale, total_profit = float(_pair[0]), float(_pair[1])
            except Exception:
                total_sale = total_profit = None
        with conn.cursor() as cur:
            if total_sale is None:
                cur.execute(f"""
                    SELECT COALESCE(SUM(sale_amount), 0) AS total_sale_amount,
                           COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS total_gross_profit
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{sale_cat_cond}{sku_cond}
                """, params)
                row = cur.fetchone()
                total_sale = float(row["total_sale_amount"] or 0)
                total_profit = float(row["total_gross_profit"] or 0)
            avg_rate = (total_profit / total_sale * 100) if total_sale > 0 else 0

            if need_join or sku_code:
                sku_cond = " AND st.sku_code = %s" if sku_code else ""
                stock_params = (sid, sid, sid)
                if sku_code:
                    stock_params = stock_params + (sku_code,)
                if need_join:
                    stock_params = stock_params + inv_params
                if need_join:
                    cur.execute(f"""
                        SELECT COALESCE(SUM(st.stock_amount), 0) AS total_stock_amount
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
                        ){sku_cond}{inv_cond}
                    """, stock_params)
                else:
                    cur.execute(f"""
                        SELECT COALESCE(SUM(stock_amount), 0) AS total_stock_amount
                        FROM t_htma_stock
                        WHERE store_id = %s AND data_date = (
                            SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                        ){sku_cond.replace('st.', '')}
                    """, (sid, sid) + ((sku_code,) if sku_code else ()))
                stock_row = cur.fetchone()
                total_stock = float(stock_row["total_stock_amount"] or 0)
            else:
                cur.execute("""
                    SELECT COALESCE(SUM(stock_amount), 0) AS total_stock_amount
                    FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    )
                """, (sid, sid))
                stock_row = cur.fetchone()
                total_stock = float(stock_row["total_stock_amount"] or 0)

        period_label = f"{start_d} ~ {end_d}" if (start_d and end_d) else {"day": "今日", "week": "本周", "month": "本月", "recent30": "近30天"}.get(period, "近30天")
        out = {
            "total_sale_amount": round(total_sale, 2),
            "total_gross_profit": round(total_profit, 2),
            "avg_profit_rate_pct": round(avg_rate, 2),
            "total_stock_amount": round(total_stock, 2),
            "period": period,
            "period_label": period_label,
            "start_date": start_d or None,
            "end_date": end_d or None,
            "store_id": sid,
        }
        if use_cache:
            _cache_set(cache_key, out)
        return jsonify(out)
    finally:
        conn.close()


@overview_bp.route("/api/category_pie")
def api_category_pie():
    """品类销售额占比（Top10 + 其他），支持 period、start_date、end_date、category 及 hierarchy"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                WITH cs AS (
                    SELECT COALESCE(category, '未分类') AS category, SUM(sale_amount) AS sale_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}
                    GROUP BY category
                ),
                ranked AS (
                    SELECT category, sale_amount, ROW_NUMBER() OVER (ORDER BY sale_amount DESC) AS rn FROM cs
                )
                SELECT CASE WHEN rn <= 10 THEN category ELSE '其他' END AS category,
                       SUM(sale_amount) AS sale_amount
                FROM ranked
                GROUP BY CASE WHEN rn <= 10 THEN category ELSE '其他' END
                ORDER BY sale_amount DESC
            """, params)
            rows = cur.fetchall()
        return jsonify([{"category": r["category"], "sale_amount": float(r["sale_amount"])} for r in rows])
    finally:
        conn.close()


@overview_bp.route("/api/daily_trend")
def api_daily_trend():
    """日销售额趋势（兼容旧接口）"""
    return api_sales_trend("day")


@overview_bp.route("/api/sales_trend")
def api_sales_trend_route():
    """销售额/毛利趋势，支持 granularity、start_date、end_date、category"""
    g = request.args.get("granularity", "day")
    return api_sales_trend(g)


def api_sales_trend(granularity):
    """按日/周/月聚合销售额与毛利趋势。与 KPI 一致，均从 t_htma_sale 聚合。"""
    date_cond, date_params, params, category_cond, sku_cond = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if granularity == "day":
                cur.execute(f"""
                    SELECT data_date AS x_date,
                           COALESCE(SUM(sale_amount), 0) AS sale_amount,
                           COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                    GROUP BY data_date ORDER BY data_date
                """, params)
                rows = cur.fetchall()
                out = [_format_trend_row(r, "day") for r in rows]
            elif granularity == "week":
                cur.execute(f"""
                    SELECT MIN(data_date) AS week_start,
                           CONCAT(YEAR(MIN(data_date)), '-W', LPAD(WEEK(MIN(data_date), 3), 2, '0')) AS x_date,
                           COALESCE(SUM(sale_amount), 0) AS sale_amount,
                           COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                    GROUP BY YEAR(data_date), WEEK(data_date, 3)
                    ORDER BY MIN(data_date)
                """, params)
                rows = cur.fetchall()
                out = [_format_trend_row(r, "week") for r in rows]
            else:  # month
                cur.execute(f"""
                    SELECT DATE_FORMAT(MIN(data_date), '%%Y-%%m') AS x_date,
                           COALESCE(SUM(sale_amount), 0) AS sale_amount,
                           COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                    GROUP BY YEAR(data_date), MONTH(data_date)
                    ORDER BY MIN(data_date)
                """, params)
                rows = cur.fetchall()
                out = [_format_trend_row(r, "month") for r in rows]
            data_source = "sale"
        if not out:
            return jsonify({
                "data": [],
                "dates": [],
                "sales": [],
                "gross_profit": [],
                "data_source": None,
                "empty_hint": "所选条件下无销售数据，请调整周期或品类筛选后再试。",
            })
        dates = [r["x_date"] for r in out]
        sales = [r["sale_amount"] for r in out]
        gross_profit_list = [r["profit_amount"] for r in out]
        return jsonify({
            "data": out,
            "dates": dates,
            "sales": sales,
            "gross_profit": gross_profit_list,
            "data_source": data_source,
            "empty_hint": None,
        })
    except Exception as e:
        return jsonify({"error": str(e), "data": [], "data_source": None, "empty_hint": "请求异常，请稍后重试。"}), 500
    finally:
        conn.close()


def _format_trend_row(r, granularity):
    """安全格式化趋势行，避免日期/空值导致的异常"""
    x_date = r.get("x_date")
    if x_date is not None and hasattr(x_date, "strftime"):
        x_str = x_date.strftime("%Y-%m-%d" if granularity == "day" else "%Y-%m")
    else:
        x_str = str(x_date) if x_date else ""
    week_start = r.get("week_start")
    if week_start is not None and hasattr(week_start, "strftime"):
        ws_str = week_start.strftime("%Y-%m-%d")
    else:
        ws_str = str(week_start) if week_start else ""
    return {
        "x_date": x_str,
        "week_start": ws_str,
        "sale_amount": float(r.get("sale_amount") or 0),
        "profit_amount": float(r.get("profit_amount") or 0),
    }


@overview_bp.route("/api/trend_analysis")
def api_trend_analysis():
    """走势分析：环比（与 KPI 周期联动）、同比、趋势描述。数据与 KPI 一致，均从 t_htma_sale 聚合。"""
    granularity = request.args.get("granularity", "day")
    period = request.args.get("period", "recent30")
    date_cond, date_params, params, sale_cat_cond, sku_cond = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    params_ta = params  # 与 KPI 一致：从 t_htma_sale 查，用 sale_cat_cond
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            curr_start, curr_end, prev_start, prev_end, curr_label, prev_label = _period_over_period_ranges(
                period, start_date or None, end_date or None
            )
            cat_params = tuple(params[1 + len(date_params):]) if len(params) > 1 + len(date_params) else ()
            cur.execute(
                """SELECT COALESCE(SUM(sale_amount), 0) AS sale_amount, COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                   FROM t_htma_sale WHERE store_id = %s AND data_date BETWEEN %s AND %s """ + sale_cat_cond,
                (params[0], curr_start, curr_end) + cat_params,
            )
            curr_row = cur.fetchone()
            cur.execute(
                """SELECT COALESCE(SUM(sale_amount), 0) AS sale_amount, COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                   FROM t_htma_sale WHERE store_id = %s AND data_date BETWEEN %s AND %s """ + sale_cat_cond,
                (params[0], prev_start, prev_end) + cat_params,
            )
            prev_row = cur.fetchone()
            _curr_sale = float(curr_row["sale_amount"] or 0)
            _curr_profit = float(curr_row["profit_amount"] or 0)
            _prev_sale = float(prev_row["sale_amount"] or 0)
            _prev_profit = float(prev_row["profit_amount"] or 0)
            _sale_chg = ((_curr_sale - _prev_sale) / _prev_sale * 100) if _prev_sale > 0 else 0
            _profit_chg = ((_curr_profit - _prev_profit) / _prev_profit * 100) if _prev_profit > 0 else 0
            pop = {
                "current_period": curr_label,
                "prev_period": prev_label,
                "current_sale": round(_curr_sale, 2),
                "prev_sale": round(_prev_sale, 2),
                "current_profit": round(_curr_profit, 2),
                "prev_profit": round(_prev_profit, 2),
                "sale_change_pct": round(_sale_chg, 2),
                "profit_change_pct": round(_profit_chg, 2),
            }

            if granularity == "day":
                cur.execute(f"""
                    SELECT data_date, COALESCE(SUM(sale_amount), 0) AS sale_amount, COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{sale_cat_cond}{sku_cond}
                    GROUP BY data_date ORDER BY data_date
                """, params_ta)
            elif granularity == "week":
                cur.execute(f"""
                    SELECT YEAR(data_date) AS y, WEEK(data_date, 3) AS w,
                           MIN(data_date) AS week_start,
                           COALESCE(SUM(sale_amount), 0) AS sale_amount, COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{sale_cat_cond}{sku_cond}
                    GROUP BY YEAR(data_date), WEEK(data_date, 3)
                    ORDER BY week_start
                """, params_ta)
            else:
                cur.execute(f"""
                    SELECT YEAR(data_date) AS y, MONTH(data_date) AS m,
                           DATE_FORMAT(MIN(data_date), '%%Y-%%m') AS month_key,
                           COALESCE(SUM(sale_amount), 0) AS sale_amount, COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{sale_cat_cond}{sku_cond}
                    GROUP BY YEAR(data_date), MONTH(data_date)
                    ORDER BY MIN(data_date)
                """, params_ta)

            rows = cur.fetchall()
            if not rows:
                return jsonify({"message": "数据不足", "period_over_period": pop, "year_over_year": None, "trend": "neutral", "trend_summary": None})

            # 转为列表便于索引
            data_list = []
            for r in rows:
                if granularity == "day":
                    data_list.append({
                        "key": r["data_date"].strftime("%Y-%m-%d") if hasattr(r["data_date"], "strftime") else str(r["data_date"]),
                        "sale_amount": float(r["sale_amount"]),
                        "profit_amount": float(r["profit_amount"]),
                    })
                elif granularity == "week":
                    data_list.append({
                        "key": f"{r['y']}-W{r['w']:02d}",
                        "sale_amount": float(r["sale_amount"]),
                        "profit_amount": float(r["profit_amount"]),
                    })
                else:
                    data_list.append({
                        "key": r["month_key"] or "",
                        "sale_amount": float(r["sale_amount"]),
                        "profit_amount": float(r["profit_amount"]),
                    })

            # 同比：本期 vs 去年同期（月粒度需13期；周粒度需53期；日粒度需366期）
            yoy = None
            idx_last_year = {"month": 13, "week": 53, "day": 366}.get(granularity, 13)
            if len(data_list) >= idx_last_year:
                curr = data_list[-1]
                same_last_year = data_list[-idx_last_year]
                curr_sale, last_sale = curr["sale_amount"], same_last_year["sale_amount"]
                curr_profit, last_profit = curr["profit_amount"], same_last_year["profit_amount"]
                sale_yoy = ((curr_sale - last_sale) / last_sale * 100) if last_sale > 0 else 0
                profit_yoy = ((curr_profit - last_profit) / last_profit * 100) if last_profit > 0 else 0
                yoy = {
                    "current_period": curr["key"],
                    "same_period_last_year": same_last_year["key"],
                    "sale_change_pct": round(sale_yoy, 2),
                    "profit_change_pct": round(profit_yoy, 2),
                }

            # 趋势：最近5期简单线性趋势（斜率正负）
            trend = "neutral"
            if len(data_list) >= 5:
                recent = [x["sale_amount"] for x in data_list[-5:]]
                n = len(recent)
                x_mean = (n - 1) / 2
                y_mean = sum(recent) / n
                numer = sum((i - x_mean) * (recent[i] - y_mean) for i in range(n))
                denom = sum((i - x_mean) ** 2 for i in range(n))
                slope = (numer / denom) if denom > 0 else 0
                trend = "up" if slope > 0 else "down" if slope < 0 else "neutral"

            # 走势数据摘要：供「走势与同比」卡片展示近期销售额/毛利；自定义区间时 latest_date 不超出请求的 end_date
            trend_summary = None
            if data_list:
                take = min(5, len(data_list))
                recent_list = data_list[-take:]
                recent_sale = sum(x["sale_amount"] for x in recent_list)
                recent_profit = sum(x["profit_amount"] for x in recent_list)
                last = data_list[-1]
                latest_date_val = last["key"]
                req_end = request.args.get("end_date", "").strip()
                if req_end and latest_date_val and latest_date_val > req_end:
                    latest_date_val = req_end  # 仅限制展示日期不超出所选区间，金额仍用结果集最后一条
                trend_summary = {
                    "recent_days": take,
                    "recent_sale": round(recent_sale, 2),
                    "recent_profit": round(recent_profit, 2),
                    "latest_date": latest_date_val,
                    "latest_sale": round(last["sale_amount"], 2),
                    "latest_profit": round(last["profit_amount"], 2),
                }

        # 同比所需最少期数说明
        yoy_required = {"month": 13, "week": 53, "day": 366}.get(granularity, 13)
        yoy_reason = None
        if not yoy and len(data_list) > 0:
            yoy_reason = f"同比需至少{yoy_required}期数据（{'月' if granularity=='month' else '周' if granularity=='week' else '日'}粒度），当前仅{len(data_list)}期"
        return jsonify({
            "granularity": granularity,
            "period_over_period": pop,
            "year_over_year": yoy,
            "trend": trend,
            "data_points": len(data_list),
            "trend_summary": trend_summary,
            "yoy_reason": yoy_reason,
        })
    finally:
        conn.close()


DOW_NAMES = {1: "周日", 2: "周一", 3: "周二", 4: "周三", 5: "周四", 6: "周五", 7: "周六"}


