# -*- coding: utf-8 -*-
"""AI 对话与高级搜索 — analyze/ai_chat"""

from datetime import datetime

def _ai_fetch_context(conn, store_id="沈阳超级仓", days=30, include_monthly=False):
    """拉取 AI 对话所需的数据上下文。include_monthly=True 时拉取近3个月按月毛利"""
    cur = conn.cursor()
    date_cond = "data_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"
    s_date_cond = "s.data_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"
    exc_sale_cond, exc_sale_params = _excluded_cond_sale()
    ctx = {}

    # 基础：销售额、毛利、毛利率
    cur.execute(f"""
        SELECT COALESCE(SUM(sale_amount), 0) AS total_sale, COALESCE(SUM(gross_profit), 0) AS total_profit,
               COUNT(DISTINCT sku_code) AS sku_cnt
        FROM t_htma_sale WHERE store_id = %s AND {date_cond}
    """, (store_id, days))
    row = cur.fetchone()
    ctx["total_sale"] = float(row["total_sale"] or 0)
    ctx["total_profit"] = float(row["total_profit"] or 0)
    ctx["sku_cnt"] = int(row["sku_cnt"] or 0)
    ctx["avg_margin"] = (ctx["total_profit"] / ctx["total_sale"] * 100) if ctx["total_sale"] > 0 else 0

    # 负毛利：数量、总损失、Top 商品
    cur.execute(f"""
        SELECT s.sku_code, COALESCE(st.product_name, s.sku_code) AS name, s.category,
               SUM(s.sale_amount) AS sale, SUM(s.gross_profit) AS profit
        FROM t_htma_sale s
        LEFT JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s AND {s_date_cond} AND {exc_sale_cond}
        GROUP BY s.sku_code, st.product_name, s.category
        HAVING SUM(s.sale_amount) > 500 AND SUM(s.gross_profit) < 0
        ORDER BY SUM(s.gross_profit) ASC
        LIMIT 5
    """, (store_id, store_id, days) + tuple(exc_sale_params))
    neg_rows = cur.fetchall()
    ctx["neg_count"] = len(neg_rows)
    ctx["neg_loss"] = sum(abs(float(r.get("profit") or 0)) for r in neg_rows)
    ctx["neg_top"] = neg_rows

    # 高毛利品类（毛利率>35% 且销售额>3000）
    cur.execute(f"""
        SELECT COALESCE(category, '未分类') AS cat,
               SUM(total_sale) AS sale, SUM(total_profit) AS profit,
               SUM(total_profit)/NULLIF(SUM(total_sale),0)*100 AS margin_pct
        FROM t_htma_profit
        WHERE store_id = %s AND {date_cond}
          AND COALESCE(category,'') NOT LIKE %s AND COALESCE(category,'') NOT LIKE %s AND COALESCE(category,'') NOT LIKE %s
        GROUP BY category
        HAVING SUM(total_sale) > 3000 AND SUM(total_profit)/NULLIF(SUM(total_sale),0)*100 >= 35
        ORDER BY SUM(total_profit) DESC
        LIMIT 5
    """, (store_id, days) + tuple(f"%{kw}%" for kw in _EXCLUDED_CATEGORY_KEYWORDS))
    ctx["high_margin_cats"] = cur.fetchall()

    # 动销 Top 品类（引流爆品）
    cur.execute(f"""
        SELECT s.category, SUM(s.sale_qty) AS qty, SUM(s.sale_amount) AS sale
        FROM t_htma_sale s
        LEFT JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s AND {s_date_cond} AND {exc_sale_cond}
        GROUP BY s.category
        HAVING SUM(s.sale_qty) > 0 AND SUM(s.sale_amount)/NULLIF(SUM(s.sale_qty),0) >= {_MIN_UNIT_PRICE}
        ORDER BY SUM(s.sale_qty) DESC
        LIMIT 8
    """, (store_id, store_id, days) + tuple(exc_sale_params))
    ctx["top_sale_cats"] = cur.fetchall()

    # 低库存畅销（断货风险）
    cur.execute(f"""
        SELECT s.category, SUM(s.sale_qty) AS sale_qty, SUM(s.sale_amount) AS sale_amt
        FROM t_htma_sale s
        INNER JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s AND {s_date_cond} AND {exc_sale_cond}
          AND st.stock_qty < 50 AND st.stock_qty >= 0
        GROUP BY s.category
        HAVING SUM(s.sale_qty) >= 5 AND SUM(s.sale_amount)/NULLIF(SUM(s.sale_qty),0) >= {_MIN_UNIT_PRICE}
        ORDER BY SUM(s.sale_qty) DESC
        LIMIT 5
    """, (store_id, store_id, days) + tuple(exc_sale_params))
    ctx["low_stock_cats"] = cur.fetchall()

    # 性价比货品（SKU 级：高毛利+有动销+合理单价，用于比价/性价比类问题）
    cur.execute(f"""
        SELECT s.sku_code, COALESCE(st.product_name, s.sku_code) AS name, s.category,
               SUM(s.sale_qty) AS qty, SUM(s.sale_amount) AS sale, SUM(s.gross_profit) AS profit,
               SUM(s.gross_profit)/NULLIF(SUM(s.sale_amount),0)*100 AS margin_pct,
               SUM(s.sale_amount)/NULLIF(SUM(s.sale_qty),0) AS unit_price
        FROM t_htma_sale s
        LEFT JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s AND {s_date_cond} AND {exc_sale_cond}
        GROUP BY s.sku_code, st.product_name, s.category
        HAVING SUM(s.sale_amount) > 500 AND SUM(s.sale_qty) >= 5
          AND SUM(s.gross_profit) > 0
          AND SUM(s.sale_amount)/NULLIF(SUM(s.sale_qty),0) BETWEEN 3 AND 200
        ORDER BY (SUM(s.gross_profit)/NULLIF(SUM(s.sale_amount),0)*100) * LOG10(1+SUM(s.sale_qty)) DESC
        LIMIT 15
    """, (store_id, store_id, days) + tuple(exc_sale_params))
    ctx["value_skus"] = cur.fetchall()

    # 退货/赠送（精细化：损耗与赠品）
    cur.execute(f"""
        SELECT COALESCE(SUM(sale_amount), 0) AS total_sale, COALESCE(SUM(return_amount), 0) AS return_amt,
               COALESCE(SUM(gift_amount), 0) AS gift_amt
        FROM t_htma_sale WHERE store_id = %s AND {date_cond}
    """, (store_id, days))
    rg = cur.fetchone()
    ctx["return_amt"] = float(rg["return_amt"] or 0)
    ctx["gift_amt"] = float(rg["gift_amt"] or 0)
    ctx["return_ratio_pct"] = (ctx["return_amt"] / ctx["total_sale"] * 100) if ctx["total_sale"] > 0 else 0
    ctx["gift_ratio_pct"] = (ctx["gift_amt"] / ctx["total_sale"] * 100) if ctx["total_sale"] > 0 else 0

    # 品牌/供应商 Top（精细化：供应链结构）
    cur.execute(f"""
        SELECT COALESCE(NULLIF(TRIM(brand_name), ''), '未填') AS brand_name, SUM(sale_amount) AS sale
        FROM t_htma_sale WHERE store_id = %s AND {date_cond}
        GROUP BY brand_name HAVING SUM(sale_amount) > 0 ORDER BY SUM(sale_amount) DESC LIMIT 5
    """, (store_id, days))
    ctx["top_brands"] = cur.fetchall()
    cur.execute(f"""
        SELECT COALESCE(NULLIF(TRIM(supplier_name), ''), '未填') AS supplier_name, SUM(sale_amount) AS sale
        FROM t_htma_sale WHERE store_id = %s AND {date_cond}
        GROUP BY supplier_name HAVING SUM(sale_amount) > 0 ORDER BY SUM(sale_amount) DESC LIMIT 5
    """, (store_id, days))
    ctx["top_suppliers"] = cur.fetchall()

    # 库存周转天数（按近 period 销速估算）
    cur.execute("""
        SELECT COALESCE(SUM(stock_amount), 0) AS total_stock
        FROM t_htma_stock WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
    """, (store_id, store_id))
    total_stock = float(cur.fetchone()["total_stock"] or 0)
    cur.execute(f"""
        SELECT COALESCE(SUM(sale_cost), 0) AS cost FROM t_htma_sale WHERE store_id = %s AND {date_cond}
    """, (store_id, days))
    cost_in_period = float(cur.fetchone()["cost"] or 0)
    daily_cost = cost_in_period / days if cost_in_period > 0 else 0
    ctx["inventory_turnover_days"] = (total_stock / daily_cost) if daily_cost > 0 else None
    ctx["total_stock_amount"] = total_stock

    # 数据质量（缺失成本/售价、同 SKU 多品类）
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM t_htma_sale
        WHERE store_id = %s AND (sale_cost IS NULL OR sale_cost = 0) AND sale_amount > 0
    """, (store_id,))
    ctx["missing_cost_rows"] = cur.fetchone()["cnt"] or 0
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM t_htma_sale
        WHERE store_id = %s AND (sale_price IS NULL OR sale_price = 0) AND sale_qty > 0
    """, (store_id,))
    ctx["missing_price_rows"] = cur.fetchone()["cnt"] or 0
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM (
            SELECT sku_code FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code HAVING COUNT(DISTINCT COALESCE(category, '')) > 1
        ) t
    """, (store_id,))
    ctx["inconsistent_sku_count"] = cur.fetchone()["cnt"] or 0

    # 本月至今（用于与「月目标」同口径对比）
    cur.execute("""
        SELECT COALESCE(SUM(sale_amount), 0) AS sale, COALESCE(SUM(gross_profit), 0) AS profit
        FROM t_htma_sale
        WHERE store_id = %s AND data_date >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01')
    """, (store_id,))
    row_m = cur.fetchone()
    ctx["month_sale"] = float(row_m["sale"] or 0)
    ctx["month_profit"] = float(row_m["profit"] or 0)

    # 近几个月按月毛利（用于「结合前面几个月」类问题）
    if include_monthly:
        cur.execute("""
            SELECT DATE_FORMAT(data_date, '%%Y-%%m') AS ym,
                   SUM(sale_amount) AS sale, SUM(gross_profit) AS profit
            FROM t_htma_sale
            WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
            GROUP BY DATE_FORMAT(data_date, '%%Y-%%m')
            ORDER BY ym DESC
            LIMIT 4
        """, (store_id,))
        ctx["monthly"] = cur.fetchall()
        # 上月各品类毛利占比（用于品类预测）
        cur.execute("""
            SELECT COALESCE(category, '未分类') AS cat,
                   SUM(total_profit) AS profit, SUM(total_sale) AS sale
            FROM t_htma_profit
            WHERE store_id = %s AND data_date >= DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 1 MONTH), '%%Y-%%m-01')
              AND data_date < DATE_FORMAT(CURDATE(), '%%Y-%%m-01')
              AND COALESCE(category,'') NOT LIKE %s AND COALESCE(category,'') NOT LIKE %s AND COALESCE(category,'') NOT LIKE %s
            GROUP BY category
            HAVING SUM(total_profit) > 0
            ORDER BY SUM(total_profit) DESC
            LIMIT 12
        """, (store_id,) + tuple(f"%{kw}%" for kw in _EXCLUDED_CATEGORY_KEYWORDS))
        ctx["last_month_cat_profit"] = cur.fetchall()
    else:
        ctx["monthly"] = []
        ctx["last_month_cat_profit"] = []

    cur.close()
    return ctx


def _format_drill_prefix(current_drill_summary):
    """根据 current_drill 生成回复顶部的下钻摘要（品类/品牌/款式 + Top 列表）。"""
    if not current_drill_summary:
        return ""
    parts = []
    cat = (current_drill_summary.get("category") or "").strip()
    br = (current_drill_summary.get("brand") or "").strip()
    pn = (current_drill_summary.get("product_name") or "").strip()
    if cat:
        parts.append(f"品类：{cat}")
    if br:
        parts.append(f"品牌：{br}")
    if pn:
        parts.append(f"款式：{pn}")
    if not parts:
        return ""
    line1 = "【当前下钻】" + "；".join(parts) + "。"
    lines = [line1]
    drill_brands = current_drill_summary.get("drill_brands") or []
    drill_styles = current_drill_summary.get("drill_styles") or []
    drill_sku_rank = current_drill_summary.get("drill_sku_rank") or []
    if drill_brands and not drill_styles and not drill_sku_rank:
        top = [b.get("brand") or "未填" for b in drill_brands[:5]]
        lines.append("本维度下品牌 Top5： " + "、".join(top[:5]))
    elif drill_styles and not drill_sku_rank:
        top = [s.get("product_name") or "未填" for s in drill_styles[:5]]
        lines.append("本维度下款式 Top5： " + "、".join(top[:5]))
    elif drill_sku_rank:
        top = [s.get("sku_code") or s.get("product_name") or "-" for s in drill_sku_rank[:5]]
        lines.append("本维度下货号 Top5： " + "、".join(top[:5]))
    return "\n".join(lines)


def _with_drill(reply, drill_prefix):
    """在回复前附加下钻摘要（若有）。"""
    if not drill_prefix or not (reply or "").strip():
        return reply or ""
    return (drill_prefix + "\n\n" + reply).strip()


def ai_chat_response(conn, user_message, report_summary=None, current_drill_summary=None):
    """基于真实数据返回可操作的 AI 回复，避免模板式空泛建议。
    current_drill_summary: 可选，来自消费洞察下钻的 {category, brand, product_name, drill_brands, drill_styles, drill_sku_rank}，回复中会引用。"""
    import re
    msg = (user_message or "").strip()
    msg_lower = msg.lower()
    drill_prefix = _format_drill_prefix(current_drill_summary) if current_drill_summary else ""

    # 是否拉取多月数据（用户提到「几个月」「结合」「预测」「品类」等）
    need_monthly = any(k in msg for k in ["几个月", "前几个月", "结合", "销售情况", "历史", "3月", "2月", "1月", "预测", "品类"])

    try:
        ctx = _ai_fetch_context(conn, days=30, include_monthly=need_monthly)
    except Exception:
        ctx = {
            "total_sale": 0, "total_profit": 0, "sku_cnt": 0, "avg_margin": 0,
            "neg_count": 0, "neg_loss": 0, "neg_top": [],
            "high_margin_cats": [], "top_sale_cats": [], "low_stock_cats": [],
            "value_skus": [], "monthly": [],
            "return_amt": 0, "gift_amt": 0, "return_ratio_pct": 0, "gift_ratio_pct": 0,
            "top_brands": [], "top_suppliers": [], "inventory_turnover_days": None, "total_stock_amount": 0,
            "missing_cost_rows": 0, "missing_price_rows": 0, "inconsistent_sku_count": 0,
        }

    profit_wan = ctx["total_profit"] / 10000
    sale_wan = ctx["total_sale"] / 10000

    # 解析目标数字
    target_match = re.search(r"(\d+)\s*万", msg)
    target_wan = int(target_match.group(1)) if target_match else None
    if target_wan is None and any(k in msg for k in ["提高", "提升", "达到", "做到", "目标", "突破"]):
        m = re.search(r"(\d+)", msg)
        target_wan = int(m.group(1)) if m and int(m.group(1)) > 10 else None

    # 区分：销售额目标 vs 毛利目标（关键！）
    is_sales_goal = target_wan and any(k in msg for k in ["销售", "销售额", "营收", "突破"]) and "毛利" not in msg
    is_sales_goal = is_sales_goal or (target_wan and "营销" in msg and "毛利" not in msg)
    is_profit_goal = (
        (target_wan and ("毛利" in msg or "利润" in msg)) or
        any(k in msg for k in ["提高毛利", "提升毛利", "毛利目标", "做到多少"]) or
        ("毛利" in msg and any(k in msg for k in ["建议", "方案", "提高", "提升", "达到", "做到"]))
    )
    # 仅有数字万、无明确销售/毛利时，默认按毛利（兼容旧问法）
    is_profit_goal = is_profit_goal or (target_wan and not is_sales_goal and any(k in msg for k in ["建议", "方案", "提高", "提升", "达到", "做到", "目标"]))

    # 1a. 销售额目标：销售突破 X 万、营销动作
    if is_sales_goal:
        target_sale = target_wan * 10000
        gap_sale = target_sale - ctx["total_sale"]
        actions = []
        if ctx.get("monthly"):
            actions.append("【近几个月销售走势】")
            for r in ctx["monthly"][:4]:
                s = float(r.get("sale") or 0) / 10000
                p = float(r.get("profit") or 0) / 10000
                actions.append(f"  {r.get('ym','')} 销售额{s:.1f}万 毛利{p:.1f}万")
            actions.append("")
        if gap_sale <= 0:
            actions.append(f"当前近30天销售额约 {sale_wan:.1f}万，已超过目标。建议：① 巩固爆品陈列 ② 加大促销力度 ③ 异业合作持续引流")
        else:
            actions.append(f"【现状】近30天销售额 {sale_wan:.1f}万，目标 {target_wan}万，缺口约 {gap_sale/10000:.1f}万")
            actions.append("【营销可执行动作】")
            if ctx["top_sale_cats"]:
                cats = "、".join([r["category"][:6] for r in ctx["top_sale_cats"][:5]])
                actions.append(f"① 引流爆品：{cats} 等动销 Top，做堆头/端架、小红书种草，拉新客进店")
            if ctx["low_stock_cats"]:
                cats = "、".join([r["category"][:6] for r in ctx["low_stock_cats"][:3]])
                actions.append(f"② 断货补货：{cats} 等畅销但库存不足，补满后避免流失、抓住每一单")
            actions.append("③ 促销活动：满减/第二件半价/限时折扣，拉升客单价与连带")
            actions.append("④ 异业合作：移动办套餐送券、满额赠话费，零成本拉新、放大到店客流")
            actions.append("⑤ 3月节点：妇女节、春游季做主题陈列与促销，抓住节日消费")
        return _with_drill("\n".join(actions), drill_prefix)

    # 1b. 毛利目标：提高毛利到 X 万（与「月毛利」同口径：用本月至今对比目标）
    if is_profit_goal:
        target = (target_wan or 200) * 10000
        month_profit = ctx.get("month_profit") or 0
        month_profit_wan = month_profit / 10000
        gap = target - month_profit  # 缺口以本月至今为口径，与「月目标」一致
        actions = []
        # 若用户提到「几个月」「结合」「预测」等，展示近几个月走势
        if ctx.get("monthly"):
            actions.append("【近几个月毛利走势】")
            for r in ctx["monthly"][:4]:
                p = float(r.get("profit") or 0) / 10000
                s = float(r.get("sale") or 0) / 10000
                actions.append(f"  {r.get('ym','')} 销售额{s:.1f}万 毛利{p:.1f}万")
            actions.append("")
        if gap <= 0:
            actions.append(f"【现状】本月至今毛利约 {month_profit_wan:.1f}万，已达成目标 {target/10000:.0f}万。（近30天毛利约 {profit_wan:.1f}万，供参考）")
            actions.append("建议：① 巩固高毛利品类占比 ② 控制负毛利品 ③ 保持断货预警机制")
        else:
            actions.append(f"【现状】本月至今毛利 {month_profit_wan:.1f}万，目标 {target/10000:.0f}万（月口径），缺口约 {gap/10000:.1f}万。（近30天毛利 {profit_wan:.1f}万，供参考）")
            if ctx["neg_loss"] > 0:
                actions.append(f"① 负毛利止损：当前负毛利损失约 {_fmt_money(ctx['neg_loss'])}，修复后可直接增加利润")
            if ctx["neg_top"]:
                names = "、".join([(r.get("name") or r["sku_code"])[:8] for r in ctx["neg_top"][:3]])
                actions.append(f"   优先处理：{names} 等，核查进价或限期清仓")
            if ctx["high_margin_cats"]:
                cats = "、".join([r["cat"][:6] for r in ctx["high_margin_cats"][:3]])
                actions.append(f"② 放大高毛利品类：{cats} 等毛利率>35%，加大陈列与促销可拉升整体毛利")
            if ctx["low_stock_cats"]:
                cats = "、".join([r["category"][:6] for r in ctx["low_stock_cats"][:3]])
                actions.append(f"③ 断货补货：{cats} 等畅销但库存不足，补满后可减少流失、提升销售额与毛利")
            actions.append("④ 异业合作：移动办套餐送券可定向核销高毛利区，零成本拉新、放大黄金品类销售")
        # 品类销售预测：若用户提到预测/品类，按上月占比推算本月达目标时各品类约数
        need_forecast = any(k in msg for k in ["预测", "品类", "销售情况", "各品类"])
        if need_forecast and ctx.get("last_month_cat_profit") and target > 0:
            total_last = sum(float(r.get("profit") or 0) for r in ctx["last_month_cat_profit"])
            if total_last > 0:
                actions.append("")
                actions.append("【品类销售预测】若本月毛利达目标，按上月各品类毛利占比推算约：")
                for r in ctx["last_month_cat_profit"][:8]:
                    cat = (r.get("cat") or "未分类")[:10]
                    pct = float(r.get("profit") or 0) / total_last * 100
                    pred_wan = target / 10000 * (float(r.get("profit") or 0) / total_last)
                    actions.append(f"  · {cat} 占比{pct:.0f}% → 本月约 {pred_wan:.1f}万")
                actions.append("（以上为按上月结构静态推算，实际需结合断货补货与促销节奏）")
        return _with_drill("\n".join(actions), drill_prefix)

    # 2a. 退货 / 赠送 / 损耗（精细化）
    if "退货" in msg or "赠送" in msg or "损耗" in msg:
        return_amt = ctx.get("return_amt") or 0
        gift_amt = ctx.get("gift_amt") or 0
        rr = ctx.get("return_ratio_pct") or 0
        gr = ctx.get("gift_ratio_pct") or 0
        lines = ["【退货与赠送概况】近30天数据："]
        lines.append(f"  退货金额 {_fmt_money(return_amt)}，占销售额 {rr:.1f}%；赠送金额 {_fmt_money(gift_amt)}，占销售额 {gr:.1f}%")
        if rr > 5:
            lines.append("退货占比偏高，建议：① 排查高退货品类与供应商质量 ② 优化验收与陈列 ③ 在「经营分析-退货/赠送」看明细做精细化管控")
        elif rr > 0 or gr > 0:
            lines.append("建议：在「经营分析」查看退货/赠送明细，按品类与供应商做精细化管控；赠送可结合毛利与复购评估 ROI。")
        else:
            lines.append("当前退货/赠送占比较低。建议定期查看经营分析中的退货与赠送报表，做好事前管控。")
        return _with_drill("\n".join(lines), drill_prefix)

    # 2b. 品牌 / 供应商（精细化）
    if "品牌" in msg and ("集中" in msg or "哪些" in msg or "占比" in msg or "排行" in msg):
        brands = ctx.get("top_brands") or []
        if not brands or not ctx["total_sale"]:
            return _with_drill("【品牌】暂无品牌销售数据或销售额为 0。建议在导入数据时补全 brand_name 字段。", drill_prefix)
        total = ctx["total_sale"]
        lines = ["【品牌销售占比】近30天前5品牌："]
        for r in brands[:5]:
            s = float(r.get("sale") or 0)
            pct = (s / total * 100) if total > 0 else 0
            lines.append(f"  · {(r.get('brand_name') or '未填')[:12]} 销售额 {_fmt_money(s)} 占比 {pct:.1f}%")
        lines.append("建议：可做品牌级毛利与周转分析，优化采购与陈列资源；在「经营分析-品牌分析」查看明细。")
        return _with_drill("\n".join(lines), drill_prefix)
    if "供应商" in msg and ("集中" in msg or "哪些" in msg or "占比" in msg or "排行" in msg):
        suppliers = ctx.get("top_suppliers") or []
        if not suppliers or not ctx["total_sale"]:
            return _with_drill("【供应商】暂无供应商销售数据或销售额为 0。建议在导入数据时补全 supplier_name 字段。", drill_prefix)
        total = ctx["total_sale"]
        lines = ["【供应商销售占比】近30天前5供应商："]
        for r in suppliers[:5]:
            s = float(r.get("sale") or 0)
            pct = (s / total * 100) if total > 0 else 0
            lines.append(f"  · {(r.get('supplier_name') or '未填')[:12]} 销售额 {_fmt_money(s)} 占比 {pct:.1f}%")
        lines.append("建议：结合毛利与周转做供应商评估，在「经营分析」查看供应商明细。")
        return _with_drill("\n".join(lines), drill_prefix)

    # 2c. 周转 / 库存周转（精细化）
    if "周转" in msg or "库存周转" in msg:
        days_val = ctx.get("inventory_turnover_days")
        stock_amt = ctx.get("total_stock_amount") or 0
        if days_val is None or stock_amt <= 0:
            return _with_drill("【库存周转】当前无法估算周转天数（需有库存金额与近30天销售成本）。请在「经营分析-库存周转」查看明细。", drill_prefix)
        lines = [f"【库存周转】按近30天销速估算，当前库存金额约 {_fmt_money(stock_amt)}，周转天数约 {days_val:.0f} 天。"]
        if days_val > 60:
            lines.append("周转偏慢，建议：压缩滞销品、加快促销与清仓，提升周转。")
        elif days_val < 30:
            lines.append("周转表现较好，建议保持补货与动销监控，避免断货。")
        else:
            lines.append("建议结合品类做周转分析，在「经营分析-库存周转」查看各品类/品牌明细。")
        return _with_drill("\n".join(lines), drill_prefix)

    # 2d. 数据质量 / 精细化（数据可信度）
    if "数据质量" in msg or ("精细化" in msg and ("管理" in msg or "数据" in msg or "经营" in msg)):
        mc = ctx.get("missing_cost_rows") or 0
        mp = ctx.get("missing_price_rows") or 0
        inc = ctx.get("inconsistent_sku_count") or 0
        lines = ["【数据质量与精细化】"]
        if mc > 100 or mp > 100 or inc > 50:
            parts = []
            if mc > 100:
                parts.append(f"成本缺失 {mc} 条")
            if mp > 100:
                parts.append(f"售价缺失 {mp} 条")
            if inc > 50:
                parts.append(f"同 SKU 多品类 {inc} 个")
            lines.append("当前存在：" + "、".join(parts) + "，可能影响毛利与经营分析准确性。")
            lines.append("建议：在「经营分析-数据质量」查看明细，优先补全成本与售价；同 SKU 多品类可统一归类便于分析。")
        else:
            lines.append("当前数据质量尚可。建议：① 定期在「经营分析-数据质量」巡检 ② 退货/赠送、品牌/供应商、周转等维度已支持，可做精细化管控。")
        return _with_drill("\n".join(lines), drill_prefix)

    # 2. 负毛利 / 亏损
    if "负毛利" in msg or "亏损" in msg:
        if ctx["neg_count"] == 0:
            return _with_drill("【负毛利】近30天暂无负毛利商品，数据健康。建议保持成本与售价监控，新上架品重点核查。", drill_prefix)
        lines = [f"【负毛利诊断】近30天共 {ctx['neg_count']} 个商品负毛利，总损失约 {_fmt_money(ctx['neg_loss'])}"]
        for r in ctx["neg_top"][:3]:
            name = (r.get("name") or r["sku_code"])[:12]
            diag = _neg_diagnosis_hint(name, r["sale"], r["profit"])
            lines.append(f"  · {name} | 销售额{_fmt_money(r['sale'])} 毛利{_fmt_money(r['profit'])} → {diag}")
        lines.append("建议：① 核查参考进价 ② 确认是否清仓 ③ 设计7天后自动复验闭环")
        return _with_drill("\n".join(lines), drill_prefix)

    # 3. 高毛利 / 烘焙
    if "高毛利" in msg or "烘焙" in msg:
        if not ctx["high_margin_cats"]:
            return _with_drill("【高毛利】当前数据中暂无毛利率>35%且销售额>3000的品类。建议：① 核查成本录入 ② 识别加工品/自有品牌等高毛利品 ③ 设「移动新客专享区」紧邻移动点位", drill_prefix)
        cats = ctx["high_margin_cats"]
        lines = ["【高毛利运营 SOP】基于数据的高毛利品类："]
        for r in cats[:5]:
            lines.append(f"  · {r['cat'][:10]} | 毛利率{float(r['margin_pct'] or 0):.0f}% 毛利{_fmt_money(r['profit'])}")
        lines.append("可执行动作：① 设「移动新客专享区」紧邻移动点位 ② 输出小红书推广大纲/陈列视觉提示词 ③ 做「高毛利爆品运营 SOP」标准化")
        return _with_drill("\n".join(lines), drill_prefix)

    # 4. 补货 / 断货
    if "补货" in msg or "断货" in msg:
        if not ctx["low_stock_cats"]:
            return _with_drill("【断货】当前无低库存畅销品类。建议：① 设自动巡检机制 ② 浆果/烘焙/水饮等引流爆品优先保障库存", drill_prefix)
        cats = [r["category"][:8] for r in ctx["low_stock_cats"][:5]]
        top = [r["category"][:8] for r in ctx["top_sale_cats"][:5]]
        return _with_drill(f"【断货优先级】畅销但库存不足：{', '.join(cats)}\n动销 Top：{', '.join(top)}\n建议：① 设自动巡检机制 ② 补货后放在移动点位旁做首单转化", drill_prefix)

    # 5. 移动 / 异业
    if "移动" in msg or "异业" in msg or "合作" in msg:
        high = [r["cat"][:6] for r in ctx["high_margin_cats"][:3]] if ctx["high_margin_cats"] else ["服装", "烘焙", "鞋"]
        return _with_drill(f"【中国移动联动】① 满额赠话费匹配客单价（建议满99/199）② 办套餐送券定向核销高毛利区（{', '.join(high)}）③ 设点放在引流爆品+烘焙旁 ④ 零成本零对接，适合总部审批", drill_prefix)

    # 6. 验证 / 闭环
    if "验证" in msg or "闭环" in msg:
        neg_cnt = ctx["neg_count"]
        if neg_cnt > 0:
            return _with_drill(f"【验证闭环】当前有 {neg_cnt} 个负毛利商品，建议：① 生成3组调价实验方案 ② 7天后自动拉取数据验证 ③ 小步快跑、暴力迭代。没经过验证的数据只是噪音。", drill_prefix)
        return _with_drill("【验证闭环】建议：对高毛利爆品、断货补货效果做 A/B 实验，7天后自动拉取数据验证。小步快跑、暴力迭代。", drill_prefix)

    # 7. 市场 / 拓展
    if "市场" in msg or "拓展" in msg:
        return _with_drill(f"【市场拓展】报告已按「市场引流区、利润收割区、问题清仓区、移动联动区」重构。当前近30天销售额{_fmt_money(ctx['total_sale'])}、毛利{_fmt_money(ctx['total_profit'])}、毛利率{ctx['avg_margin']:.1f}%。从「只看货卖得怎么样」变成「怎么拉来人、怎么留住人、怎么用移动合作把货卖得更贵更稳」。", drill_prefix)

    # 8. 性价比 / 比价 / 百度识货 → 4 阶段货盘价格对比
    if any(k in msg for k in ["性价比", "比价", "价格对比", "百度识货", "百度skill", "识货", "划算", "货品价格"]):
        try:
            from price_compare import run_full_pipeline, format_report
            result = run_full_pipeline(conn, store_id="沈阳超级仓", days=30, use_mock_fetcher=True)
            return _with_drill(format_report(result), drill_prefix)
        except Exception as e:
            if not ctx.get("value_skus"):
                return _with_drill(f"【货盘分析】执行失败: {e}。可尝试运行 scripts/openclaw_price_compare.sh 生成完整报告。", drill_prefix)
            lines = [
                "【性价比货品排行】货盘 4 阶段分析暂不可用，基于内部数据的高性价比货品：",
                ""
            ]
            for i, r in enumerate(ctx["value_skus"][:10], 1):
                name = (r.get("name") or r["sku_code"])[:14]
                margin = float(r.get("margin_pct") or 0)
                up = float(r.get("unit_price") or 0)
                sale = float(r.get("sale") or 0)
                lines.append(f"  {i}. {name} | 单价{up:.1f}元 毛利率{margin:.0f}% 销售额{_fmt_money(sale)}")
            lines.append("")
            lines.append("完整货盘分析请执行: bash scripts/openclaw_price_compare.sh")
            return _with_drill("\n".join(lines), drill_prefix)

    # 9. 通用 / 无匹配：基于数据给综合建议（含退货/周转/数据质量等精细化维度）
    lines = [f"【综合建议】基于近30天数据：销售额{_fmt_money(ctx['total_sale'])}、毛利{_fmt_money(ctx['total_profit'])}、毛利率{ctx['avg_margin']:.1f}%"]
    if ctx["neg_count"] > 0:
        lines.append(f"① 负毛利：{ctx['neg_count']} 个商品损失约{_fmt_money(ctx['neg_loss'])}，优先核查或清仓")
    rr = ctx.get("return_ratio_pct") or 0
    gr = ctx.get("gift_ratio_pct") or 0
    if rr > 0 or gr > 0:
        lines.append(f"② 退货占比 {rr:.1f}%、赠送占比 {gr:.1f}%，可在「经营分析」看退货/赠送明细做精细化管控")
    if ctx["high_margin_cats"]:
        cats = "、".join([r["cat"][:6] for r in ctx["high_margin_cats"][:3]])
        lines.append(f"③ 高毛利品类（{cats}）可加大陈列与促销")
    if ctx["low_stock_cats"]:
        cats = "、".join([r["category"][:6] for r in ctx["low_stock_cats"][:3]])
        lines.append(f"④ 断货风险：{cats} 等需优先补货")
    turn = ctx.get("inventory_turnover_days")
    if turn is not None and turn > 0:
        if turn > 60:
            lines.append(f"⑤ 库存周转约 {turn:.0f} 天偏慢，建议压缩滞销、加快清仓")
        else:
            lines.append(f"⑤ 库存周转约 {turn:.0f} 天，可结合「经营分析-库存周转」做品类优化")
    dq = (ctx.get("missing_cost_rows") or 0) + (ctx.get("missing_price_rows") or 0)
    if dq > 100:
        lines.append("⑥ 数据质量：存在成本/售价缺失，建议在「经营分析-数据质量」补全以提升分析准确性")
    if not any("移动" in ln or "异业" in ln for ln in lines):
        lines.append("⑦ 移动异业合作可零成本拉新、放大黄金品类销售")
    return _with_drill("\n".join(lines), drill_prefix)


def advanced_search_consumer_insight(
    conn,
    store_id="沈阳超级仓",
    period="recent30",
    start_date=None,
    end_date=None,
    min_price=None,
    max_price=None,
    brands=None,
    suppliers=None,
    categories=None,
    stock_status=None,
    page=1,
    page_size=20,
    sort_by="sales_amount",
    sort_order="desc",
    range_days=30,
):
    """
    消费洞察高级查询：按价格区间、品牌、供应商、品类、库存状态筛选，返回 SKU 级销售与库存。
    返回 {"total": int, "items": [{"sku_code", "product_name", "brand", "category", "supplier",
          "avg_unit_price", "total_qty", "total_sales", "stock_qty", "stock_turnover_days"}, ...]}
    """
    if _date_condition is None:
        return {"total": 0, "items": []}
    date_cond, date_params = _date_condition(period, start_date, end_date)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 100)
    offset = (page - 1) * page_size

    sort_column_map = {
        "sales_amount": "s.total_sales",
        "avg_price": "s.avg_unit_price",
        "stock_qty": "COALESCE(st.stock_qty, 0)",
        "total_qty": "s.total_qty",
    }
    sort_col = sort_column_map.get(sort_by, "s.total_sales")
    order = "DESC" if (sort_order or "desc").lower() == "desc" else "ASC"

    sale_subquery = """
        SELECT
            sku_code,
            MAX(category) AS category,
            SUM(sale_qty) AS total_qty,
            SUM(sale_amount) AS total_sales,
            SUM(sale_amount) / NULLIF(SUM(sale_qty), 0) AS avg_unit_price
        FROM t_htma_sale
        WHERE store_id = %s AND """ + date_cond + """
        GROUP BY sku_code
    """
    stock_subquery = """
        SELECT sku_code, stock_qty
        FROM t_htma_stock
        WHERE store_id = %s AND data_date = (
            SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
        )
    """
    base_params = [store_id] + list(date_params)
    where_parts = ["1=1"]
    filter_params = []

    if min_price is not None and str(min_price).strip() != "":
        try:
            where_parts.append("s.avg_unit_price >= %s")
            filter_params.append(float(min_price))
        except (ValueError, TypeError):
            pass
    if max_price is not None and str(max_price).strip() != "":
        try:
            where_parts.append("s.avg_unit_price <= %s")
            filter_params.append(float(max_price))
        except (ValueError, TypeError):
            pass
    if brands:
        brand_list = [b.strip() for b in (brands if isinstance(brands, list) else brands.split(",")) if b.strip()]
        if brand_list:
            placeholders = ",".join(["%s"] * len(brand_list))
            where_parts.append("COALESCE(TRIM(p.brand_name), '') IN (" + placeholders + ")")
            filter_params.extend(brand_list)
    if suppliers:
        sup_list = [s.strip() for s in (suppliers if isinstance(suppliers, list) else suppliers.split(",")) if s.strip()]
        if sup_list:
            placeholders = ",".join(["%s"] * len(sup_list))
            where_parts.append("COALESCE(TRIM(p.supplier_name), '') IN (" + placeholders + ")")
            filter_params.extend(sup_list)
    if categories:
        cat_list = [c.strip() for c in (categories if isinstance(categories, list) else categories.split(",")) if c.strip()]
        if cat_list:
            placeholders = ",".join(["%s"] * len(cat_list))
            where_parts.append("COALESCE(TRIM(p.category_name), '') IN (" + placeholders + ")")
            filter_params.extend(cat_list)
    if stock_status == "in_stock":
        where_parts.append("COALESCE(st.stock_qty, 0) > 0")
    elif stock_status == "out_stock":
        where_parts.append("COALESCE(st.stock_qty, 0) = 0")
    elif stock_status == "low_stock":
        where_parts.append("COALESCE(st.stock_qty, 0) < 10")

    where_sql = " AND ".join(where_parts)
    # 参数顺序：sale 子查询(base_params) + p.store_id + stock 子查询(store_id*2) + 筛选 + CASE 中 range_days*2 + LIMIT/OFFSET
    all_params = base_params + [store_id] + [store_id, store_id] + filter_params
    query_params = all_params + [range_days, range_days, page_size, offset]
    count_params = base_params + [store_id] + [store_id, store_id] + filter_params

    sql = """
        SELECT
            s.sku_code,
            COALESCE(p.product_name, '') AS product_name,
            COALESCE(p.brand_name, '') AS brand,
            COALESCE(NULLIF(TRIM(p.category_name), ''), NULLIF(TRIM(s.category), ''), '') AS category,
            COALESCE(p.supplier_name, '') AS supplier,
            s.avg_unit_price,
            s.total_qty,
            s.total_sales,
            COALESCE(st.stock_qty, 0) AS stock_qty,
            CASE WHEN s.total_qty > 0 AND COALESCE(st.stock_qty, 0) > 0 AND %s > 0
                 THEN ROUND(COALESCE(st.stock_qty, 0) / (s.total_qty / %s), 1)
                 ELSE NULL END AS stock_turnover_days
        FROM (""" + sale_subquery + """) s
        LEFT JOIN t_htma_product_master p ON p.sku_code = s.sku_code AND p.store_id = %s
        LEFT JOIN (""" + stock_subquery + """) st ON st.sku_code = s.sku_code
        WHERE """ + where_sql + """
        ORDER BY """ + sort_col + " " + order + """
        LIMIT %s OFFSET %s
    """
    count_sql = """
        SELECT COUNT(*) AS total
        FROM (""" + sale_subquery + """) s
        LEFT JOIN t_htma_product_master p ON p.sku_code = s.sku_code AND p.store_id = %s
        LEFT JOIN (""" + stock_subquery + """) st ON st.sku_code = s.sku_code
        WHERE """ + where_sql

    cur = conn.cursor()
    try:
        cur.execute(count_sql, count_params)
        total = (cur.fetchone() or {}).get("total") or 0
        cur.execute(sql, query_params)
        rows = cur.fetchall()
        items = []
        for r in rows:
            items.append({
                "sku_code": r.get("sku_code"),
                "product_name": r.get("product_name") or "",
                "brand": r.get("brand") or "",
                "category": r.get("category") or "",
                "supplier": r.get("supplier") or "",
                "avg_unit_price": float(r["avg_unit_price"]) if r.get("avg_unit_price") is not None else None,
                "total_qty": float(r["total_qty"]) if r.get("total_qty") is not None else 0,
                "total_sales": float(r["total_sales"]) if r.get("total_sales") is not None else 0,
                "stock_qty": float(r["stock_qty"]) if r.get("stock_qty") is not None else 0,
                "stock_turnover_days": float(r["stock_turnover_days"]) if r.get("stock_turnover_days") is not None else None,
            })
        return {"total": total, "items": items}
    finally:
        cur.close()
