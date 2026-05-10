#!/usr/bin/env python3
"""好特卖超级仓 - 商业管理看板增强版数据API
为首页提供经营统计数据，供前端使用
"""
from __future__ import annotations
import json, os
import sys
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from flask import Blueprint, jsonify, request
from db_config import get_conn


biz_bp = Blueprint("biz", __name__, url_prefix="/api/biz")


def _effective_store_id() -> str:
    """与首页 KPI 一致：飞书绑定门店 → HTMA_STORE_ID → 默认；供 /api/biz/* 全量 SQL 过滤。"""
    # 生产常见：`cd htma_dashboard && python -u app.py` → 主模块名为 __main__ 而非 app
    mod = sys.modules.get("app") or sys.modules.get("__main__")
    if mod is not None and hasattr(mod, "_effective_store_id"):
        try:
            sid = mod._effective_store_id()
            if sid:
                return str(sid).strip()
        except Exception:
            pass
    return (os.environ.get("HTMA_STORE_ID") or "沈阳超级仓").strip() or "沈阳超级仓"


def register_biz_routes(app):
    app.register_blueprint(biz_bp)


@biz_bp.before_request
def _biz_before_request():
    if request.method == "OPTIONS":
        return None
    from flask import g
    g.wechat_jwt_payload = None
    return None


def _row_to_float(r, key, default=0.0):
    try:
        return float(r.get(key) or default)
    except (TypeError, ValueError):
        return default


@biz_bp.route("/monthly", methods=["GET"])
def api_biz_monthly():
    """按月汇总：销售额、毛利、毛利率、天数"""
    sid = _effective_store_id()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT LEFT(data_date,7) AS ym,
                   ROUND(SUM(sale_amount),0) AS sales,
                   ROUND(SUM(COALESCE(gross_profit,0)),0) AS profit,
                   COUNT(DISTINCT data_date) AS days,
                   COUNT(*) AS total_rows
            FROM t_htma_sale
            WHERE store_id = %s
            GROUP BY ym ORDER BY ym
        """, (sid,))
        items = []
        for r in cur.fetchall():
            s = _row_to_float(r, "sales")
            p = _row_to_float(r, "profit")
            items.append({
                "ym": r["ym"],
                "sales": s,
                "profit": p,
                "margin_pct": round(p / s * 100, 2) if s else 0,
                "days": r["days"],
                "rows": r["total_rows"],
            })
        # 合计行
        total_s = sum(it["sales"] for it in items)
        total_p = sum(it["profit"] for it in items)
        return jsonify({
            "code": 0,
            "data": {
                "items": items,
                "total_sales": total_s,
                "total_profit": total_p,
                "total_margin_pct": round(total_p / total_s * 100, 2) if total_s else 0,
                "month_count": len(items),
            },
            "msg": "",
        })
    finally:
        conn.close()


@biz_bp.route("/category", methods=["GET"])
def api_biz_category():
    """品类销售排名与分析"""
    sid = _effective_store_id()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT COALESCE(category_large,'') AS cat,
                   ROUND(SUM(sale_amount),0) AS sales,
                   ROUND(SUM(COALESCE(gross_profit,0)),0) AS profit,
                   COUNT(*) AS sku_count
            FROM t_htma_sale
            WHERE store_id = %s
            GROUP BY cat ORDER BY sales DESC
        """, (sid,))
        rows = cur.fetchall()
        total_s = sum((_row_to_float(r, "sales") for r in rows), 0.0) if rows else 0
        items = []
        for r in rows:
            s = _row_to_float(r, "sales")
            p = _row_to_float(r, "profit")
            items.append({
                "name": r["cat"],
                "sales": s,
                "profit": p,
                "margin_pct": round(p / s * 100, 2) if s else 0,
                "share_pct": round(s / total_s * 100, 2) if total_s else 0,
                "sku_count": r["sku_count"],
            })
        # 找正/负毛利品类
        negative_margin = [it for it in items if it["margin_pct"] < 0]
        high_margin = [it for it in items if it["margin_pct"] >= 35 and it["sales"] > 50000]
        return jsonify({
            "code": 0,
            "data": {
                "items": items,
                "total_sales": total_s,
                "negative_margin_count": len(negative_margin),
                "negative_margin_items": negative_margin[:5],
                "high_margin_items": high_margin[:5],
            },
            "msg": "",
        })
    finally:
        conn.close()


@biz_bp.route("/inventory_alerts", methods=["GET"])
def api_biz_inventory_alerts():
    """库存预警分析"""
    sid = _effective_store_id()
    conn = get_conn()
    cur = conn.cursor()
    try:
        # 最新库存日期
        cur.execute(
            "SELECT MAX(data_date) AS mx FROM t_htma_stock WHERE store_id = %s",
            (sid,),
        )
        r = cur.fetchone()
        latest_date = str(r["mx"])[:10] if r and r.get("mx") else ""

        # 低库存SKU（库存量<10 且有动销的）
        cur.execute("""
            SELECT COUNT(DISTINCT s.sku_code) AS low_stock_sold
            FROM t_htma_stock st
            INNER JOIN t_htma_sale s ON st.sku_code = s.sku_code AND s.store_id = %s
            WHERE st.store_id = %s
              AND st.data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
              AND COALESCE(st.stock_qty, 0) < 10
              AND s.data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        """, (sid, sid, sid))
        low_stock_sold = int((cur.fetchone() or {}).get("low_stock_sold") or 0)

        # 高库存低周转（库存金额>5000 且近期销售为0）
        cur.execute("""
            SELECT COUNT(*) AS high_stock_no_sale
            FROM t_htma_stock st
            WHERE st.store_id = %s
              AND st.data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
              AND COALESCE(st.stock_amount, 0) > 5000
              AND st.sku_code NOT IN (
                  SELECT DISTINCT sku_code FROM t_htma_sale
                  WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
              )
        """, (sid, sid, sid))
        high_stock_no_sale = int((cur.fetchone() or {}).get("high_stock_no_sale") or 0)

        # 库存总览
        cur.execute("""
            SELECT COUNT(*) AS total_skus,
                   ROUND(SUM(COALESCE(stock_amount, 0)), 0) AS total_amount,
                   ROUND(SUM(COALESCE(stock_qty, 0)), 0) AS total_qty
            FROM t_htma_stock
            WHERE store_id = %s
              AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
        """, (sid, sid))
        r = cur.fetchone()

        return jsonify({
            "code": 0,
            "data": {
                "as_of_date": latest_date,
                "total_skus": int(r["total_skus"]) if r else 0,
                "total_amount": _row_to_float(r, "total_amount") if r else 0,
                "total_qty": _row_to_float(r, "total_qty") if r else 0,
                "low_stock_with_sales": low_stock_sold,
                "high_stock_no_sale": high_stock_no_sale,
            },
            "msg": "",
        })
    finally:
        conn.close()


@biz_bp.route("/category_matrix", methods=["GET"])
def api_biz_category_matrix():
    """品类利润贡献矩阵：毛利率 vs 销售额占比，四象限分析"""
    sid = _effective_store_id()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT COALESCE(category_large,'') AS cat,
                   ROUND(SUM(sale_amount),0) AS sales,
                   ROUND(SUM(COALESCE(gross_profit,0)),0) AS profit,
                   COUNT(DISTINCT sku_code) AS skus
            FROM t_htma_sale
            WHERE store_id = %s
            GROUP BY cat ORDER BY sales DESC
        """, (sid,))
        rows = cur.fetchall()
        total_s = sum(float(r.get("sales") or 0) for r in rows)
        items = []
        for r in rows:
            s = float(r.get("sales") or 0)
            p = float(r.get("profit") or 0)
            margin = round(p / s * 100, 1) if s else 0
            share = round(s / total_s * 100, 1) if total_s else 0
            items.append({
                "name": r["cat"],
                "sales": s,
                "profit": p,
                "margin_pct": margin,
                "share_pct": share,
                "skus": r["skus"],
            })
        # 计算中位数划分四象限
        margins = sorted([it["margin_pct"] for it in items])
        shares = sorted([it["share_pct"] for it in items])
        mid_margin = margins[len(margins)//2] if margins else 0
        mid_share = shares[len(shares)//2] if shares else 0
        quads = {"stars": [], "cash_cows": [], "question_marks": [], "dogs": []}
        for it in items:
            if it["margin_pct"] >= mid_margin and it["share_pct"] >= mid_share:
                quads["stars"].append(it)        # 高毛利高占比 → 明星
            elif it["margin_pct"] >= mid_margin and it["share_pct"] < mid_share:
                quads["cash_cows"].append(it)    # 高毛利低占比 → 金牛（可培育）
            elif it["margin_pct"] < mid_margin and it["share_pct"] >= mid_share:
                quads["question_marks"].append(it) # 低毛利高占比 → 问题（需优化）
            else:
                quads["dogs"].append(it)         # 低毛利低占比 → 瘦狗
        return jsonify({
            "code": 0,
            "data": {
                "items": items,
                "total_sales": total_s,
                "median_margin": mid_margin,
                "median_share": mid_share,
                "quadrants": quads,
            },
            "msg": "",
        })
    finally:
        conn.close()

@biz_bp.route("/slow_movers", methods=["GET"])
def api_biz_slow_movers():
    """滞销品TOP榜：高库存金额且长期无销售的SKU"""
    sid = _effective_store_id()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT st.sku_code, st.product_name, st.category_large, st.category,
                   ROUND(COALESCE(st.stock_qty,0),0) AS qty,
                   ROUND(COALESCE(st.stock_amount,0),0) AS amount,
                   COALESCE(st.last_change_date, '') AS last_change,
                   COALESCE(st.aging,0) AS aging_days
            FROM t_htma_stock st
            WHERE st.store_id = %s
              AND st.data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
              AND COALESCE(st.stock_amount, 0) > 3000
              AND st.sku_code NOT IN (
                  SELECT DISTINCT sku_code FROM t_htma_sale
                  WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
              )
              AND COALESCE(st.stock_qty, 0) > 0
            ORDER BY st.stock_amount DESC
            LIMIT 50
        """, (sid, sid, sid))
        items = []
        for r in cur.fetchall():
            items.append({
                "sku_code": r["sku_code"],
                "product_name": r["product_name"] or r["sku_code"],
                "category": r["category_large"] or r["category"] or "",
                "qty": float(r["qty"]) if r["qty"] else 0,
                "amount": float(r["amount"]) if r["amount"] else 0,
                "last_change": str(r["last_change"])[:10] if r["last_change"] else "",
                "aging_days": float(r["aging_days"]) if r["aging_days"] else 0,
            })
        return jsonify({"code": 0, "data": {"items": items, "count": len(items)}, "msg": ""})
    finally:
        conn.close()

@biz_bp.route("/summary", methods=["GET"])
def api_biz_summary():
    """经营管理综合摘要：KPI + 洞察 + 动销率 + 库存周转 + 经营净利润"""
    sid = _effective_store_id()
    conn = get_conn()
    cur = conn.cursor()
    try:
        today = date.today()
        month_start = today.replace(day=1)
        last_month_end = month_start - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        # 本月 vs 上月 销售/毛利
        cur.execute("""
            SELECT ROUND(SUM(sale_amount),0) AS sales, ROUND(SUM(COALESCE(gross_profit,0)),0) AS profit
            FROM t_htma_sale
            WHERE store_id = %s AND data_date >= %s AND data_date <= %s
        """, (sid, month_start.isoformat(), today.isoformat()))
        r = cur.fetchone()
        this_m_sales = _row_to_float(r, "sales")
        this_m_profit = _row_to_float(r, "profit")

        cur.execute("""
            SELECT ROUND(SUM(sale_amount),0) AS sales, ROUND(SUM(COALESCE(gross_profit,0)),0) AS profit
            FROM t_htma_sale
            WHERE store_id = %s AND data_date >= %s AND data_date <= %s
        """, (sid, last_month_start.isoformat(), last_month_end.isoformat()))
        r = cur.fetchone()
        last_m_sales = _row_to_float(r, "sales")
        last_m_profit = _row_to_float(r, "profit")

        sale_change = round((this_m_sales - last_m_sales) / last_m_sales * 100, 1) if last_m_sales else 0

        # 当日销售额
        cur.execute("""
            SELECT ROUND(SUM(sale_amount),0) AS sales FROM t_htma_sale
            WHERE store_id = %s AND data_date = %s
        """, (sid, today.isoformat()))
        r = cur.fetchone()
        today_sales = _row_to_float(r, "sales")

        # ── 动销率 ──
        cur.execute(
            """SELECT COUNT(DISTINCT sku_code) AS total_sku FROM t_htma_stock
               WHERE store_id = %s AND data_date=(SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)""",
            (sid, sid),
        )
        total_sku = int((cur.fetchone() or {}).get("total_sku") or 0)
        cur.execute(
            """SELECT COUNT(DISTINCT sku_code) AS sold_sku FROM t_htma_sale
               WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)""",
            (sid,),
        )
        sold_sku = int((cur.fetchone() or {}).get("sold_sku") or 0)
        turnover_rate = round(sold_sku / total_sku * 100, 1) if total_sku else 0

        # ── 库存周转天数 ──
        cur.execute("""
            SELECT COALESCE(SUM(COALESCE(stock_amount,0)),0) AS inv_amt
            FROM t_htma_stock
            WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
        """, (sid, sid))
        r = cur.fetchone()
        cur_inv = _row_to_float(r, "inv_amt")
        # 近30天日均销售成本 = 近30天销售总额 - 毛利
        cur.execute("""
            SELECT ROUND(SUM(sale_amount),0) AS s, ROUND(SUM(COALESCE(gross_profit,0)),0) AS p
            FROM t_htma_sale
            WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        """, (sid,))
        r = cur.fetchone()
        s30 = _row_to_float(r, "s")
        p30 = _row_to_float(r, "p")
        cost30 = s30 - p30
        daily_cost = cost30 / 30 if cost30 > 0 else 1
        inv_turnover_days = round(cur_inv / daily_cost, 1) if daily_cost > 0 else 0

        # ── 经营净利润（毛利 - 当月人力成本）──
        net_profit = this_m_profit
        try:
            month_str = today.strftime("%Y-%m")
            cur.execute("""
                SELECT ROUND(SUM(COALESCE(total_cost,0)),0) AS labor
                FROM t_htma_labor_cost WHERE report_month = %s AND store_id = %s
            """, (month_str, sid))
            r = cur.fetchone()
            labor_cost = _row_to_float(r, "labor")
            net_profit = round(this_m_profit - labor_cost, 2)
        except Exception:
            labor_cost = 0
            net_profit = this_m_profit

        # ── 库销比 ──
        # 月均销售额 = 近30天销售额
        avg_monthly_sales = s30
        stock_to_sales_ratio = round(cur_inv / avg_monthly_sales, 2) if avg_monthly_sales else 0

        # ── 滞销品数（近60天无销售的高库存>5000）──
        cur.execute("""
            SELECT COUNT(*) AS cnt
            FROM t_htma_stock st
            WHERE st.store_id = %s
              AND st.data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
              AND COALESCE(st.stock_amount, 0) > 5000
              AND st.sku_code NOT IN (
                  SELECT DISTINCT sku_code FROM t_htma_sale
                  WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
              )
        """, (sid, sid, sid))
        r = cur.fetchone()
        slow_mover_count = int((r or {}).get("cnt") or 0)

        # ── 库存健康（合并到summary，前端只需调1个接口）──
        cur.execute("""
            SELECT COUNT(DISTINCT s.sku_code) AS low_stock_sold
            FROM t_htma_stock st
            INNER JOIN t_htma_sale s ON st.sku_code = s.sku_code AND s.store_id = %s
            WHERE st.store_id = %s
              AND st.data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
              AND COALESCE(st.stock_qty, 0) < 10
              AND s.data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        """, (sid, sid, sid))
        low_stock_sold = int((cur.fetchone() or {}).get("low_stock_sold") or 0)

        cur.execute("""
            SELECT COUNT(*) AS high_stock_no_sale
            FROM t_htma_stock st
            WHERE st.store_id = %s
              AND st.data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
              AND COALESCE(st.stock_amount, 0) > 5000
              AND st.sku_code NOT IN (
                  SELECT DISTINCT sku_code FROM t_htma_sale
                  WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
              )
        """, (sid, sid, sid))
        high_stock_no_sale = int((cur.fetchone() or {}).get("high_stock_no_sale") or 0)

        return jsonify({
            "code": 0,
            "data": {
                "this_month": {
                    "sales": this_m_sales,
                    "profit": this_m_profit,
                    "margin_pct": round(this_m_profit / this_m_sales * 100, 1) if this_m_sales else 0,
                },
                "last_month": {
                    "sales": last_m_sales,
                    "profit": last_m_profit,
                    "margin_pct": round(last_m_profit / last_m_sales * 100, 1) if last_m_sales else 0,
                },
                "sale_mom_change_pct": sale_change,
                "today_sales": today_sales,
                "turnover_rate": turnover_rate,
                "turnover_rate_desc": f"在架{total_sku}个SKU，近30天{sold_sku}个有动销",
                "inv_turnover_days": inv_turnover_days,
                "net_profit": net_profit,
                "labor_cost": labor_cost,
                "stock_to_sales_ratio": stock_to_sales_ratio,
                "slow_mover_count": slow_mover_count,
                "current_inventory": round(cur_inv, 2),
                "low_stock_with_sales": low_stock_sold,
                "high_stock_no_sale": high_stock_no_sale,
                "as_of": today.isoformat(),
            },
            "msg": "",
        })
    finally:
        conn.close()


@biz_bp.route("/labor_efficiency", methods=["GET"])
def api_biz_labor_efficiency():
    """人力效能综合分析"""
    sid = _effective_store_id()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT report_month,
                   COUNT(*) AS total_people,
                   ROUND(SUM(total_cost), 2) AS total_cost,
                   SUM(CASE WHEN position_type IN ('leader','management') THEN 1 ELSE 0 END) AS mgmt_count,
                   ROUND(SUM(CASE WHEN position_type IN ('leader','management') THEN total_cost ELSE 0 END), 2) AS mgmt_cost,
                   SUM(CASE WHEN position_type IN ('fulltime') THEN 1 ELSE 0 END) AS ft_count,
                   ROUND(SUM(CASE WHEN position_type IN ('fulltime') THEN total_cost ELSE 0 END), 2) AS ft_cost
            FROM t_htma_labor_cost
            WHERE report_month >= '2025-11' AND store_id = %s
            GROUP BY report_month ORDER BY report_month
        """, (sid,))
        labor_by_month = {}
        for r in cur.fetchall():
            m = r["report_month"]
            labor_by_month[m] = {
                "people": r["total_people"], "cost": float(r["total_cost"] or 0),
                "mgmt_count": r["mgmt_count"], "mgmt_cost": float(r["mgmt_cost"] or 0),
                "ft_count": r["ft_count"], "ft_cost": float(r["ft_cost"] or 0),
            }
        cur.execute("""
            SELECT DATE_FORMAT(data_date, '%Y-%m') AS month,
                   ROUND(SUM(sale_amount), 0) AS sales,
                   ROUND(SUM(COALESCE(gross_profit, 0)), 0) AS profit
            FROM t_htma_sale
            WHERE store_id = %s AND data_date >= '2025-11-01'
            GROUP BY month ORDER BY month
        """, (sid,))
        sales_by_month = {}
        for r in cur.fetchall():
            sales_by_month[r["month"]] = {"sales": float(r["sales"] or 0), "profit": float(r["profit"] or 0)}
        all_months = sorted(set(list(labor_by_month.keys()) + list(sales_by_month.keys())))
        monthly_data = []
        for m in all_months:
            lab = labor_by_month.get(m, {})
            sal = sales_by_month.get(m, {})
            ppl = lab.get("people", 0); cost = lab.get("cost", 0)
            sales = sal.get("sales", 0); profit = sal.get("profit", 0)
            monthly_data.append({
                "month": m, "people": ppl, "cost": cost,
                "mgmt_count": lab.get("mgmt_count", 0), "mgmt_cost": lab.get("mgmt_cost", 0),
                "ft_count": lab.get("ft_count", 0), "ft_cost": lab.get("ft_cost", 0),
                "flex_cost": round(cost - lab.get("mgmt_cost", 0) - lab.get("ft_cost", 0), 2),
                "sales": sales, "profit": profit,
                "margin_pct": round(profit / sales * 100, 1) if sales else 0,
                "rev_per_person": round(sales / ppl, 2) if ppl else 0,
                "profit_per_person": round(profit / ppl, 2) if ppl else 0,
                "cost_to_rev_pct": round(cost / sales * 100, 2) if sales else 0,
                "cost_to_profit_pct": round(cost / profit * 100, 2) if profit else 0,
                "mgmt_pct": round(lab.get("mgmt_count", 0) / ppl * 100, 1) if ppl else 0,
                "mgmt_cost_pct": round(lab.get("mgmt_cost", 0) / cost * 100, 1) if cost else 0,
                "mgmt_span": round(lab.get("ft_count", 0) / max(lab.get("mgmt_count", 0), 1), 1),
            })
        # 岗位类型全览
        cur.execute("""
            SELECT position_type, COUNT(*) AS n,
                   ROUND(SUM(total_cost),2) AS total, ROUND(AVG(total_cost),2) AS avg_c
            FROM t_htma_labor_cost
            WHERE report_month >= '2025-11' AND store_id = %s
            GROUP BY position_type ORDER BY total DESC
        """, (sid,))
        type_overview = {}
        for r in cur.fetchall():
            type_overview[r["position_type"]] = {
                "entries": r["n"], "accum_cost": float(r["total"] or 0), "avg_cost": float(r["avg_c"] or 0)
            }
        # 按月×岗位明细
        cur.execute("""
            SELECT report_month, position_type,
                   COUNT(*) AS cnt, ROUND(SUM(total_cost),2) AS cost
            FROM t_htma_labor_cost
            WHERE report_month >= '2025-11' AND store_id = %s
            GROUP BY report_month, position_type ORDER BY report_month, position_type
        """, (sid,))
        type_detail = {}
        for r in cur.fetchall():
            m = r["report_month"]; pt = r["position_type"]
            if m not in type_detail: type_detail[m] = {}
            type_detail[m][pt] = {"cnt": r["cnt"], "cost": float(r["cost"] or 0)}
        # 诊断
        latest = monthly_data[-1] if monthly_data else {}
        prev = monthly_data[-2] if len(monthly_data) >= 2 else {}
        diag = []
        if latest and prev:
            if latest["cost"] > prev["cost"] and latest["sales"] < prev["sales"]:
                diag.append("⚠ 人力成本上升但收入下降，效率承压")
            elif latest["cost"] < prev["cost"] and latest["sales"] > prev["sales"]:
                diag.append("✓ 收入增长同时人力成本下降")
            if latest.get("mgmt_pct", 0) > 25:
                diag.append("⚠ 管理组占比" + str(latest["mgmt_pct"]) + "%，超过25%警戒线")
            if latest.get("mgmt_span", 0) < 3:
                diag.append("⚠ 管理幅度 " + str(latest["mgmt_span"]) + ":1，管理组偏多")
        return jsonify({
            "code": 0,
            "data": {"monthly": monthly_data, "type_overview": type_overview,
                     "type_detail": type_detail, "diagnosis": diag},
            "msg": ""
        })
    except Exception as e:
        return jsonify({"code": -1, "data": None, "msg": str(e)})
    finally:
        conn.close()
