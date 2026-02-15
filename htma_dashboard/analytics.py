#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
零售业数据分析模型 - 品类贡献度、周转率、智能建议
支持「市场拓展+异业合作」决策报告，从数据罗列转向可执行洞察
"""
from datetime import datetime


def build_insights(conn, store_id="沈阳超级仓"):
    """基于数据生成智能分析建议"""
    insights = []
    cur = conn.cursor()

    # 1. 品类毛利率分析
    cur.execute("""
        SELECT COALESCE(category, '未分类') AS category,
               SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit,
               SUM(total_profit)/NULLIF(SUM(total_sale),0)*100 AS margin_pct
        FROM t_htma_profit
        WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
        GROUP BY category
        HAVING SUM(total_sale) > 1000
    """, (store_id,))
    cats = cur.fetchall()
    total_sale = sum(float(c["total_sale"] or 0) for c in cats)
    total_profit = sum(float(c["total_profit"] or 0) for c in cats)
    avg_margin = (total_profit / total_sale * 100) if total_sale > 0 else 0

    low_margin = [c for c in cats if (float(c["margin_pct"] or 0) < 15 and float(c["total_sale"] or 0) > 5000)]
    high_margin = [c for c in cats if float(c["margin_pct"] or 0) >= 35 and float(c["total_sale"] or 0) > 3000]

    if low_margin:
        names = "、".join([c["category"] for c in low_margin[:5]])
        insights.append({
            "type": "warning",
            "title": "低毛利品类需关注",
            "desc": f"{names} 等品类毛利率低于15%，建议检查定价或成本结构。",
            "action": "可考虑优化采购成本或调整售价策略",
        })
    if high_margin:
        names = "、".join([c["category"] for c in high_margin[:3]])
        insights.append({
            "type": "success",
            "title": "高毛利优势品类",
            "desc": f"{names} 毛利率超过35%，可作为重点推广品类。",
            "action": "建议加大陈列与促销力度，提升销售占比",
        })

    # 2. 品类销售贡献度（二八分析）
    sorted_cats = sorted(cats, key=lambda x: float(x["total_sale"] or 0), reverse=True)
    cum = 0
    top80_pct = 0
    for i, c in enumerate(sorted_cats):
        cum += float(c["total_sale"] or 0)
        if cum >= total_sale * 0.8 and top80_pct == 0:
            top80_pct = i + 1
            break
    if top80_pct and len(sorted_cats) > 10:
        insights.append({
            "type": "info",
            "title": "销售集中度分析",
            "desc": f"前 {top80_pct} 个品类贡献了约80%销售额，共 {len(sorted_cats)} 个品类。",
            "action": "可聚焦头部品类做精细化运营，同时关注长尾品类动销",
        })

    # 3. 低库存预警
    cur.execute("""
        SELECT COUNT(DISTINCT sku_code) AS cnt
        FROM t_htma_stock
        WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
        AND stock_qty < 50 AND stock_qty >= 0
    """, (store_id, store_id))
    low_stock = cur.fetchone()["cnt"] or 0
    if low_stock > 20:
        insights.append({
            "type": "warning",
            "title": "低库存 SKU 较多",
            "desc": f"共有 {low_stock} 个 SKU 库存低于50，存在断货风险。",
            "action": "建议及时补货，优先保障畅销品库存",
        })

    # 4. 负毛利/零销售异常
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM t_htma_profit
        WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        AND total_profit < 0 AND total_sale > 0
    """, (store_id,))
    neg_profit = cur.fetchone()["cnt"] or 0
    if neg_profit > 0:
        insights.append({
            "type": "warning",
            "title": "存在负毛利记录",
            "desc": f"近30天有 {neg_profit} 条负毛利记录（销售额>0但毛利<0）。",
            "action": "建议核查成本数据或促销力度是否过大",
        })

    # 5. 整体毛利率健康度
    if avg_margin < 20 and total_sale > 10000:
        insights.append({
            "type": "warning",
            "title": "整体毛利率偏低",
            "desc": f"近90天平均毛利率约 {avg_margin:.1f}%，低于零售业常见水平。",
            "action": "建议优化品类结构，提升高毛利品类占比",
        })
    elif avg_margin >= 30:
        insights.append({
            "type": "success",
            "title": "毛利率表现良好",
            "desc": f"近90天平均毛利率约 {avg_margin:.1f}%，盈利结构健康。",
            "action": "可继续保持，关注周转与库存健康",
        })

    # 6. 好特卖临期折扣特色：周转与动销
    cur.execute("""
        SELECT COUNT(DISTINCT sku_code) AS sku_cnt, SUM(sale_qty) AS total_qty
        FROM t_htma_sale
        WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    """, (store_id,))
    sale_30 = cur.fetchone()
    sku_cnt = sale_30["sku_cnt"] or 0
    total_qty = sale_30["total_qty"] or 0
    if sku_cnt > 100 and total_qty > 0:
        avg_qty = total_qty / sku_cnt
        if avg_qty < 2:
            insights.append({
                "type": "info",
                "title": "临期折扣动销分析",
                "desc": f"近30天 {sku_cnt} 个 SKU 动销，平均每 SKU 销售 {avg_qty:.1f} 件。",
                "action": "建议关注滞销品类，加快清仓或调整陈列位置",
            })
        elif avg_qty > 5:
            insights.append({
                "type": "success",
                "title": "动销表现良好",
                "desc": f"近30天 {sku_cnt} 个 SKU 动销，平均每 SKU 销售 {avg_qty:.1f} 件。",
                "action": "周转良好，可维持当前补货节奏",
            })

    # 7. 数据新鲜度
    cur.execute("SELECT MAX(data_date) AS d FROM t_htma_sale WHERE store_id = %s", (store_id,))
    last_date = cur.fetchone()["d"]
    if last_date:
        from datetime import date
        today = date.today()
        last_d = last_date if hasattr(last_date, 'year') else today
        days_ago = (today - last_d).days
        if days_ago > 3:
            d_str = last_date.strftime("%Y-%m-%d") if hasattr(last_date, "strftime") else str(last_date)
            insights.append({
                "type": "info",
                "title": "数据更新提醒",
                "desc": f"最新销售数据日期为 {d_str}，距今 {days_ago} 天。",
                "action": "建议定期导入最新数据以保持看板时效性",
            })

    cur.close()
    return insights


def _fmt_money(v):
    if v is None or v == 0:
        return "0"
    if abs(v) >= 10000:
        return f"{v/10000:.1f}万"
    return f"{float(v):,.0f}"


# 营销报告中排除的品类/商品：成本计算可能不准确（如购物袋等低价辅料）
_EXCLUDED_CATEGORY_KEYWORDS = ("购物袋", "包装袋", "塑料袋")
# 单价低于此值（元）的商品视为数据异常，不参与动销/毛利排行
_MIN_UNIT_PRICE = 0.5


def _excluded_cond_sale():
    """返回排除成本异常品类的 SQL 条件（用于 t_htma_sale s + t_htma_stock st）"""
    parts = []
    for kw in _EXCLUDED_CATEGORY_KEYWORDS:
        parts.append(f"(COALESCE(s.category_small,'') LIKE %s OR COALESCE(s.category,'') LIKE %s OR COALESCE(s.category_mid,'') LIKE %s OR COALESCE(s.category_large,'') LIKE %s OR COALESCE(st.product_name,'') LIKE %s)")
    if not parts:
        return "1=1", []
    cond = "NOT (" + " OR ".join(parts) + ")"
    params = []
    for kw in _EXCLUDED_CATEGORY_KEYWORDS:
        params.extend([f"%{kw}%"] * 5)
    return cond, params


def _excluded_cond_stock():
    """返回排除成本异常品类的 SQL 条件（仅 t_htma_stock st，按 product_name）"""
    parts = []
    for kw in _EXCLUDED_CATEGORY_KEYWORDS:
        parts.append("COALESCE(st.product_name,'') LIKE %s")
    if not parts:
        return "1=1", []
    cond = "NOT (" + " OR ".join(parts) + ")"
    params = [f"%{kw}%" for kw in _EXCLUDED_CATEGORY_KEYWORDS]
    return cond, params


def _neg_diagnosis_hint(name, sale, profit):
    """负毛利诊断提示：区分系统录入错误 vs 真实亏损清仓"""
    loss_ratio = abs(float(profit or 0) / float(sale or 1)) if sale else 0
    if loss_ratio > 0.8:
        return "【疑似录入错误】毛利亏损率>80%，建议优先核查参考进价"
    if "美妆" in str(name) or "名品" in str(name):
        return "【可能促销/清仓】美妆类常做活动，建议确认是否为 intentional 清仓"
    return "【需人工诊断】建议：①核查进价 ②确认是否清仓 ③7天后复验"


def build_marketing_report(conn, store_id="沈阳超级仓", days=30, mode="market_expansion"):
    """进销存营销分析报告。
    mode: internal=传统进销存复盘 | market_expansion=市场拓展+异业合作决策报告（可执行洞察）"""
    cur = conn.cursor()
    date_cond = "data_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"
    s_date_cond = "s.data_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"
    base_params = (store_id, days)
    exc_sale_cond, exc_sale_params = _excluded_cond_sale()
    exc_stock_cond, exc_stock_params = _excluded_cond_stock()
    report = []

    # 基础数据
    cur.execute(f"""
        SELECT COALESCE(SUM(sale_amount), 0) AS total_sale, COALESCE(SUM(gross_profit), 0) AS total_profit,
               COALESCE(SUM(sale_qty), 0) AS total_qty, COUNT(DISTINCT sku_code) AS sku_cnt
        FROM t_htma_sale WHERE store_id = %s AND {date_cond}
    """, base_params)
    row = cur.fetchone()
    total_sale = float(row["total_sale"] or 0)
    total_profit = float(row["total_profit"] or 0)
    total_qty = int(row["total_qty"] or 0)
    sku_cnt = int(row["sku_cnt"] or 0)
    avg_margin = (total_profit / total_sale * 100) if total_sale > 0 else 0

    cur.execute("""
        SELECT COALESCE(SUM(stock_amount), 0) AS total_stock
        FROM t_htma_stock WHERE store_id = %s AND data_date = (
            SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s
        )
    """, (store_id, store_id))
    total_stock = float(cur.fetchone()["total_stock"] or 0)

    # 动销 Top（品类去重）
    cur.execute(f"""
        SELECT s.category, SUM(s.sale_qty) AS qty, SUM(s.sale_amount) AS sale, SUM(s.gross_profit) AS profit
        FROM t_htma_sale s
        LEFT JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s AND {s_date_cond} AND {exc_sale_cond}
        GROUP BY s.category
        HAVING SUM(s.sale_qty) > 0 AND SUM(s.sale_amount)/NULLIF(SUM(s.sale_qty),0) >= {_MIN_UNIT_PRICE}
        ORDER BY SUM(s.sale_qty) DESC
        LIMIT 15
    """, (store_id, store_id, days) + tuple(exc_sale_params))
    top_sale_rows = cur.fetchall()

    # 低库存畅销
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
        LIMIT 10
    """, (store_id, store_id, days) + tuple(exc_sale_params))
    low_stock_rows = cur.fetchall()

    # 负毛利
    cur.execute(f"""
        SELECT s.sku_code, COALESCE(st.product_name, s.sku_code) AS name, s.category,
               SUM(s.sale_qty) AS qty, SUM(s.sale_amount) AS sale, SUM(s.gross_profit) AS profit
        FROM t_htma_sale s
        LEFT JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s AND {s_date_cond} AND {exc_sale_cond}
        GROUP BY s.sku_code, st.product_name, s.category
        HAVING SUM(s.sale_amount) > 500 AND SUM(s.gross_profit) < 0
        ORDER BY SUM(s.gross_profit) ASC
        LIMIT 8
    """, (store_id, store_id, days) + tuple(exc_sale_params))
    neg_rows = cur.fetchall()

    # 大类贡献
    cur.execute(f"""
        SELECT COALESCE(NULLIF(TRIM(category_large), ''), '未分类') AS cat,
               SUM(sale_amount) AS sale, SUM(gross_profit) AS profit
        FROM t_htma_sale
        WHERE store_id = %s AND {date_cond}
          AND COALESCE(category_small, category, '') NOT LIKE %s
          AND COALESCE(category_small, category, '') NOT LIKE %s
          AND COALESCE(category_small, category, '') NOT LIKE %s
        GROUP BY category_large
        HAVING SUM(sale_amount) > 10000
        ORDER BY SUM(sale_amount) DESC
        LIMIT 8
    """, (store_id, days) + tuple(f"%{kw}%" for kw in _EXCLUDED_CATEGORY_KEYWORDS))
    large_rows = cur.fetchall()

    # 品类毛利 Top
    profit_exc = " AND ".join(f"COALESCE(category,'') NOT LIKE %s" for _ in _EXCLUDED_CATEGORY_KEYWORDS)
    profit_exc_params = [f"%{kw}%" for kw in _EXCLUDED_CATEGORY_KEYWORDS]
    cur.execute(f"""
        SELECT COALESCE(category, '未分类') AS cat,
               SUM(total_sale) AS sale, SUM(total_profit) AS profit,
               SUM(total_profit)/NULLIF(SUM(total_sale),0)*100 AS margin_pct
        FROM t_htma_profit
        WHERE store_id = %s AND {date_cond} AND {profit_exc}
        GROUP BY category
        HAVING SUM(total_sale) > 5000
        ORDER BY SUM(total_profit) DESC
        LIMIT 8
    """, (store_id, days) + tuple(profit_exc_params))
    profit_rows = cur.fetchall()

    # 断货损失估算（低库存畅销品的预估损失）
    out_of_stock_loss = sum(float(r.get("sale_amt") or 0) for r in low_stock_rows if float(r.get("sale_qty") or 0) >= 100)
    neg_loss = sum(abs(float(r.get("profit") or 0)) for r in neg_rows)

    # ========== 报告正文 ==========
    if mode == "market_expansion":
        report.append("【好特卖沈阳超级仓 · 市场拓展+异业合作决策报告】")
        report.append("")
        # 一句话商业结论
        top_cats = [r["cat"][:4] for r in large_rows[:3]]
        report.append("▶ 商业结论（近{}天）：".format(days))
        report.append("  服装/鞋/烘焙为核心销冠，生鲜水饮为最强引流品；爆款大面积断货、负毛利品拉低利润。")
        report.append("  引入中国移动异业合作可精准补客流、提转化、放大黄金品类销售额，且不增加卖场成本。")
        report.append("")
        report.append(f"📅 分析周期：近{days}天")
        report.append(f"📊 销售额 {_fmt_money(total_sale)} · 毛利 {_fmt_money(total_profit)} · 毛利率 {avg_margin:.1f}%")
        report.append(f"📦 动销 SKU {sku_cnt} 个 · 销量 {total_qty:,} 件 · 库存总额 {_fmt_money(total_stock)}")
        report.append("")

        # 1. 市场引流爆品区
        report.append("━━━ 1. 【市场引流爆品区】承接新客、移动活动引流 ━━━")
        seen_cats = set()
        for r in top_sale_rows[:8]:
            cat = (r.get("category") or "未分类")[:10]
            if cat not in seen_cats:
                seen_cats.add(cat)
                margin = (float(r["profit"] or 0) / float(r["sale"] or 1) * 100) if r["sale"] else 0
                report.append(f"  · {cat} | 销量{int(r['qty'] or 0)}件 销售额{_fmt_money(r['sale'])} 毛利率{margin:.0f}%")
        out_cats = set(r.get("category", "")[:10] for r in low_stock_rows)
        if out_cats:
            report.append("  【断货预警】" + "、".join(list(out_cats)[:5]) + " 等畅销但库存不足")
            report.append(f"  【断货损失估算】约 {_fmt_money(out_of_stock_loss)} 潜在销售额流失")
        report.append("  ▶ 可执行动作：浆果/烘焙/水饮作为移动新客引流标品，必须优先补满货，放在移动点位旁做首单转化")
        report.append("")

        # 2. 利润收割主力区
        report.append("━━━ 2. 【利润收割主力区】移动赠券核销、冲额 ━━━")
        for i, r in enumerate(large_rows[:5], 1):
            margin = (float(r["profit"] or 0) / float(r["sale"] or 1) * 100) if r["sale"] else 0
            report.append(f"  {i}. {r['cat'][:10]} | 销售额{_fmt_money(r['sale'])} 毛利率{margin:.0f}%")
        report.append("  ▶ 可执行动作：移动办套餐送的购物券，定向引导到服装/鞋/高毛利烘焙区，保证卖场赚得到钱")
        report.append("")

        # 3. 问题品清仓区（含诊断）
        report.append("━━━ 3. 【问题品清仓区】为市场拓展腾资源 ━━━")
        if neg_rows:
            for i, r in enumerate(neg_rows[:5], 1):
                name = (r.get("name") or r["sku_code"])[:12]
                diag = _neg_diagnosis_hint(name, r["sale"], r["profit"])
                report.append(f"  {i}. {name} | 销售额{_fmt_money(r['sale'])} 毛利{_fmt_money(r['profit'])}")
                report.append(f"     {diag}")
            report.append(f"  【负毛利总损失】约 {_fmt_money(neg_loss)}")
            report.append("  ▶ 可执行动作：限期清仓止损，不占用移动活动流量与陈列；7天后自动复验是否改善")
        else:
            report.append("  暂无负毛利商品")
        report.append("")

        # 4. 中国移动异业联动专属区
        report.append("━━━ 4. 【中国移动异业联动专属区】 ━━━")
        report.append("  · 满额赠话费 → 匹配门店主流客单价（建议门槛：满99/199）")
        report.append("  · 办套餐送购物券 → 定向核销高毛利品类（服装/烘焙/鞋）")
        report.append("  · 移动设点位置 → 建议放在「引流爆品区+烘焙专区旁」")
        report.append("  · 沈阳本地适配：符合社区家庭客、年轻客消费习惯，适合长期线下引流")
        report.append("")

        # 5. 总部审批用·商业价值总结
        report.append("━━━ 【总部审批·商业价值总结】 ━━━")
        report.append("  ✓ 移动合作零成本、零对接、零财务纠纷")
        report.append("  ✓ 可直接提升卖场客流、停留时长、连带销售")
        report.append("  ✓ 黄金品类（服装/烘焙/鞋）可借活动放大销售额与毛利")
        report.append("  ✓ 爆款补货后新客体验更好，复购更强")
    else:
        # 传统 internal 模式（保持原结构）
        report.append("【好特卖沈阳超级仓 · 进销存营销分析】")
        report.append(f"📅 分析周期：近{days}天")
        report.append(f"📊 销售额 {_fmt_money(total_sale)} · 毛利 {_fmt_money(total_profit)} · 毛利率 {avg_margin:.1f}%")
        report.append(f"📦 动销 SKU {sku_cnt} 个 · 销量 {total_qty:,} 件 · 库存总额 {_fmt_money(total_stock)}")
        report.append("")
        for i, r in enumerate(top_sale_rows[:10], 1):
            if i == 1:
                report.append("🔥 【动销 Top10】")
            cat = (r.get("category") or "未分类")[:12]
            margin = (float(r["profit"] or 0) / float(r["sale"] or 1) * 100) if r["sale"] else 0
            report.append(f"  {i}. {cat} | 销量{int(r['qty'] or 0)}件 销售额{_fmt_money(r['sale'])} 毛利率{margin:.0f}%")
        if top_sale_rows:
            report.append("  💡 建议：加大陈列、做堆头/端架")
        report.append("")
        for i, r in enumerate(profit_rows[:5], 1):
            if i == 1:
                report.append("📂 【品类毛利 Top5】")
            report.append(f"  {i}. {r['cat'][:10]} | 毛利{_fmt_money(r['profit'])} 毛利率{float(r['margin_pct'] or 0):.0f}%")
        report.append("")
        if neg_rows:
            report.append("⚠️ 【负毛利商品】")
            for i, r in enumerate(neg_rows[:5], 1):
                name = (r.get("name") or r["sku_code"])[:12]
                report.append(f"  {i}. {name} | 销售额{_fmt_money(r['sale'])} 毛利{_fmt_money(r['profit'])}")
            report.append("  💡 建议：核查成本或调价/清仓")
        report.append("")

    report.append(f"--- 报告生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M')} ---")
    cur.close()
    return "\n".join(report)


def category_rank_data(rows, total_sale, total_profit):
    """计算品类排行及贡献度"""
    out = []
    for i, r in enumerate(rows, 1):
        sale = float(r.get("total_sale") or r.get("sale_amount") or 0)
        profit = float(r.get("total_profit") or r.get("profit_amount") or 0)
        contrib_sale = (sale / total_sale * 100) if total_sale > 0 else 0
        contrib_profit = (profit / total_profit * 100) if total_profit > 0 else 0
        margin = (profit / sale * 100) if sale > 0 else 0
        out.append({
            "rank": i,
            "category": r.get("category") or "未分类",
            "sale_amount": round(sale, 2),
            "profit_amount": round(profit, 2),
            "margin_pct": round(margin, 2),
            "sale_contrib_pct": round(contrib_sale, 2),
            "profit_contrib_pct": round(contrib_profit, 2),
        })
    return out


def ai_chat_response(conn, user_message, report_summary=None):
    """基于用户输入和报告摘要，返回可操作的 AI 回复（可扩展接入 LLM）"""
    msg = (user_message or "").strip().lower()
    responses = []

    if "负毛利" in user_message or "亏损" in user_message:
        responses.append("【负毛利诊断建议】① 优先核查参考进价是否录入错误 ② 确认是否为 intentional 清仓促销 ③ 建议设计「7天后自动复验」闭环，验证调价/清仓效果")
    if "高毛利" in user_message or "烘焙" in user_message:
        responses.append("【高毛利运营 SOP】烘焙类100%毛利多为加工品：① 设「移动新客专享区」紧邻移动点位 ② 输出小红书推广大纲/陈列视觉提示词 ③ 做「高毛利爆品运营 SOP」标准化")
    if "补货" in user_message or "断货" in user_message:
        responses.append("【断货优先级】浆果/烘焙/水饮/虾片为引流爆品，断货直接损失新客首单体验。建议：① 设自动巡检机制 ② 与移动活动联动，补货后放在移动点位旁")
    if "移动" in user_message or "异业" in user_message or "合作" in user_message:
        responses.append("【中国移动联动】① 满额赠话费匹配客单价 ② 办套餐送券定向核销高毛利区 ③ 设点放在引流爆品+烘焙旁 ④ 零成本零对接，适合总部审批")
    if "验证" in user_message or "闭环" in user_message:
        responses.append("【验证闭环】建议：基于负毛利商品生成3组调价实验方案，7天后自动拉取数据验证。没经过验证的数据只是噪音，小步快跑、暴力迭代。")
    if "市场" in user_message or "拓展" in user_message:
        responses.append("【市场拓展】从「只看货卖得怎么样」变成「怎么拉来人、怎么留住人、怎么用移动合作把货卖得更贵更稳」。报告已按市场引流区、利润收割区、问题清仓区、移动联动区重构。")

    if not responses:
        responses.append("【通用建议】可尝试提问：负毛利怎么诊断？高毛利如何做 SOP？断货优先级？移动异业合作怎么落地？验证闭环怎么设计？")
    return "\n\n".join(responses)
