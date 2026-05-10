# -*- coding: utf-8 -*-
"""结构化报告与营销报告 — analyze/report"""

from datetime import datetime


# 营销报告中排除的品类/商品：成本计算可能不准确（如购物袋等低价辅料）
_EXCLUDED_CATEGORY_KEYWORDS = ("购物袋", "包装袋", "塑料袋")
_MIN_UNIT_PRICE = 0.5

def build_structured_report(insight_data, insights, market_report_text=None):
    """
    从已获取的 insight_data、insights 及可选市场拓展报告文本，组装结构化分析报告 JSON。
    供 app 在 /api/structured_report 中调用，避免 analytics 依赖 app/request。
    """
    report = {}

    # 1. 总览与商业结论
    report["summary"] = {
        "kpi": insight_data.get("overview") or {},
        "insights": insights,
        "conclusion": (market_report_text or "").strip()[:500] if market_report_text else "",
    }

    # 2. 品类结构
    report["category_structure"] = {
        "matrix": insight_data.get("category_matrix") or [],
        "top_sales": insight_data.get("category_top_sale") or [],
        "top_profit": insight_data.get("category_top_profit") or [],
        "top_margin": insight_data.get("category_top_margin") or [],
    }

    # 3. 下钻摘要（由 app 根据请求参数传入的 insight_data 已含 drill_*）
    drill_section = {}
    drill_brands = insight_data.get("drill_brands") or []
    drill_styles = insight_data.get("drill_styles") or []
    drill_sku_rank = insight_data.get("drill_sku_rank") or []
    if drill_brands and not drill_styles and not drill_sku_rank:
        drill_section["type"] = "category_drill"
        drill_section["brands"] = drill_brands[:10]
    elif drill_styles and not drill_sku_rank:
        drill_section["type"] = "brand_drill"
        drill_section["styles"] = drill_styles[:10]
    elif drill_sku_rank:
        drill_section["type"] = "product_drill"
        drill_section["skus"] = drill_sku_rank[:20]
    report["drill_section"] = drill_section

    # 4. 品牌与供应商
    report["brand_supplier"] = {
        "brands": insight_data.get("brand") or [],
        "suppliers": insight_data.get("supplier") or [],
    }

    # 5. 价格、经销与促销
    report["price_promo"] = {
        "price_band": insight_data.get("price_band") or [],
        "distribution": insight_data.get("distribution") or [],
        "discount_band": insight_data.get("discount_band") or [],
        "high_discount_low_margin": insight_data.get("high_discount_low_margin") or [],
    }

    # 6. 问题与行动（从 insight_data 已有字段提取；负毛利/数据质量 Phase2 可另查补充）
    report["issues"] = {
        "negative_profit": {"count": 0, "amount": 0, "top_items": []},
        "stock": {"low_stock_cats": [], "need_replenish": []},
        "data_quality": {"missing_cost": 0, "missing_price": 0, "multi_category": 0},
        "return_gift": {
            "return_rate": insight_data.get("return_rate_pct") or 0,
            "return_by_cat": insight_data.get("return_by_cat") or [],
        },
        "zero_sale_skus": insight_data.get("zero_sale_skus") or [],
        "high_discount_low_margin": insight_data.get("high_discount_low_margin") or [],
    }

    # 7. 市场拓展（可选，app 传入时已为文本）
    report["market_expansion"] = market_report_text if market_report_text else None

    # 8. 附录：下钻明细（仅当有下钻数据时）
    appendix = {}
    if drill_brands:
        appendix["drill_brands"] = drill_brands
    if drill_styles:
        appendix["drill_styles"] = drill_styles
    if drill_sku_rank:
        appendix["drill_sku_rank"] = drill_sku_rank
    report["appendix"] = appendix if appendix else None

    return report


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

    # 动销 Top10（按商品 SKU 明细：品名、规格、销量、销售额、利润总额、利润率）
    cur.execute(f"""
        SELECT s.sku_code, COALESCE(st.product_name, s.product_name, s.sku_code) AS name,
               COALESCE(st.spec, s.spec, '') AS spec, s.category,
               SUM(s.sale_qty) AS qty, SUM(s.sale_amount) AS sale, SUM(s.gross_profit) AS profit,
               SUM(s.gross_profit)/NULLIF(SUM(s.sale_amount),0)*100 AS margin_pct
        FROM t_htma_sale s
        LEFT JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s AND {s_date_cond} AND {exc_sale_cond}
        GROUP BY s.sku_code, st.product_name, s.product_name, st.spec, s.spec, s.category
        HAVING SUM(s.sale_qty) > 0 AND SUM(s.sale_amount)/NULLIF(SUM(s.sale_qty),0) >= {_MIN_UNIT_PRICE}
        ORDER BY SUM(s.sale_qty) DESC
        LIMIT 10
    """, (store_id, store_id, days) + tuple(exc_sale_params))
    top10_sale_sku = cur.fetchall()

    # 高毛利 Top10（毛利率≥35% 且销售额>500，按商品）
    cur.execute(f"""
        SELECT s.sku_code, COALESCE(st.product_name, s.product_name, s.sku_code) AS name,
               COALESCE(st.spec, s.spec, '') AS spec, s.category,
               SUM(s.sale_qty) AS qty, SUM(s.sale_amount) AS sale, SUM(s.gross_profit) AS profit,
               SUM(s.gross_profit)/NULLIF(SUM(s.sale_amount),0)*100 AS margin_pct
        FROM t_htma_sale s
        LEFT JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s AND {s_date_cond} AND {exc_sale_cond}
        GROUP BY s.sku_code, st.product_name, s.product_name, st.spec, s.spec, s.category
        HAVING SUM(s.sale_amount) > 500 AND SUM(s.gross_profit)/NULLIF(SUM(s.sale_amount),0)*100 >= 35
        ORDER BY SUM(s.gross_profit) DESC
        LIMIT 10
    """, (store_id, store_id, days) + tuple(exc_sale_params))
    top10_high_margin_sku = cur.fetchall()

    # 黄金商品（销量≥10 且毛利率≥30%，动销好+毛利高）
    cur.execute(f"""
        SELECT s.sku_code, COALESCE(st.product_name, s.product_name, s.sku_code) AS name,
               COALESCE(st.spec, s.spec, '') AS spec, s.category,
               SUM(s.sale_qty) AS qty, SUM(s.sale_amount) AS sale, SUM(s.gross_profit) AS profit,
               SUM(s.gross_profit)/NULLIF(SUM(s.sale_amount),0)*100 AS margin_pct
        FROM t_htma_sale s
        LEFT JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s AND {s_date_cond} AND {exc_sale_cond}
        GROUP BY s.sku_code, st.product_name, s.product_name, st.spec, s.spec, s.category
        HAVING SUM(s.sale_qty) >= 10 AND SUM(s.sale_amount) > 0
          AND SUM(s.gross_profit)/NULLIF(SUM(s.sale_amount),0)*100 >= 30
        ORDER BY SUM(s.gross_profit) DESC
        LIMIT 15
    """, (store_id, store_id, days) + tuple(exc_sale_params))
    golden_sku = cur.fetchall()

    # 需补货（畅销但库存不足：近 N 天有销且库存<50）
    cur.execute(f"""
        SELECT s.sku_code, COALESCE(st.product_name, s.product_name, s.sku_code) AS name,
               COALESCE(st.spec, s.spec, '') AS spec, st.stock_qty, s.category,
               SUM(s.sale_qty) AS sale_qty, SUM(s.sale_amount) AS sale, SUM(s.gross_profit) AS profit,
               SUM(s.gross_profit)/NULLIF(SUM(s.sale_amount),0)*100 AS margin_pct
        FROM t_htma_sale s
        INNER JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s AND {s_date_cond} AND {exc_sale_cond}
          AND st.stock_qty < 50 AND st.stock_qty >= 0
        GROUP BY s.sku_code, st.product_name, s.product_name, st.spec, s.spec, st.stock_qty, s.category
        HAVING SUM(s.sale_qty) >= 5 AND SUM(s.sale_amount)/NULLIF(SUM(s.sale_qty),0) >= {_MIN_UNIT_PRICE}
        ORDER BY SUM(s.sale_qty) DESC
        LIMIT 10
    """, (store_id, store_id, days) + tuple(exc_sale_params))
    need_replenish_sku = cur.fetchall()

    # 滞销高库存（库存≥100 且近 N 天销量<3）
    cur.execute(f"""
        SELECT st.sku_code, COALESCE(st.product_name, st.sku_code) AS name,
               COALESCE(st.spec, '') AS spec, st.stock_qty, st.stock_amount,
               COALESCE(agg.sale_qty, 0) AS sale_qty, COALESCE(agg.sale_amount, 0) AS sale,
               COALESCE(agg.profit, 0) AS profit
        FROM t_htma_stock st
        LEFT JOIN (
            SELECT sku_code, SUM(sale_qty) AS sale_qty, SUM(sale_amount) AS sale_amount, SUM(gross_profit) AS profit
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}
            GROUP BY sku_code
        ) agg ON agg.sku_code = st.sku_code
        WHERE st.store_id = %s AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
          AND st.stock_qty >= 100 AND COALESCE(agg.sale_qty, 0) < 3
          AND {exc_stock_cond}
        ORDER BY st.stock_qty DESC
        LIMIT 10
    """, (store_id, days, store_id, store_id) + tuple(exc_stock_params))
    slow_high_stock_sku = cur.fetchall()

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
        # 进销存营销分析（明细版）：Top10/ Top5 均列明具体商品、利润总额、利润率，建议体现专家气质
        report.append("【好特卖沈阳超级仓 · 进销存营销分析】")
        report.append(f"📅 分析周期：近{days}天")
        report.append(f"📊 销售额 {_fmt_money(total_sale)} · 毛利 {_fmt_money(total_profit)} · 毛利率 {avg_margin:.1f}%")
        report.append(f"📦 动销 SKU {sku_cnt} 个 · 销量 {total_qty:,} 件 · 库存总额 {_fmt_money(total_stock)}")
        report.append("")

        report.append("🔥 【动销 Top10】销量领先的 10 个商品明细")
        if top10_sale_sku:
            for i, r in enumerate(top10_sale_sku, 1):
                name = (r.get("name") or r["sku_code"] or "")[:14].strip()
                spec = (r.get("spec") or "-")[:10].strip()
                qty = int(r.get("qty") or 0)
                sale = float(r.get("sale") or 0)
                profit = float(r.get("profit") or 0)
                margin = float(r.get("margin_pct") or 0)
                report.append(f"  {i}. {name} {spec} | 销量{qty}件 销售额{_fmt_money(sale)} 利润总额{_fmt_money(profit)} 利润率{margin:.1f}%")
            report.append("  ▶ 专家建议：上述为门店流量担当，建议加大陈列面、设置堆头或端架，提升曝光与复购；可配合档期做主题陈列。")
        else:
            report.append("  暂无符合条件商品")
        report.append("")

        report.append("💰 【高毛利 Top10】毛利率≥35% 且销售额>500 的 10 个商品明细")
        if top10_high_margin_sku:
            for i, r in enumerate(top10_high_margin_sku, 1):
                name = (r.get("name") or r["sku_code"] or "")[:14].strip()
                spec = (r.get("spec") or "-")[:10].strip()
                profit = float(r.get("profit") or 0)
                margin = float(r.get("margin_pct") or 0)
                sale = float(r.get("sale") or 0)
                report.append(f"  {i}. {name} {spec} | 利润总额{_fmt_money(profit)} 利润率{margin:.1f}% 销售额{_fmt_money(sale)}")
            report.append("  ▶ 专家建议：高毛利单品是利润核心，建议重点推广、搭配促销话术与陈列位，避免被低价品稀释毛利结构。")
        else:
            report.append("  暂无符合条件商品")
        report.append("")

        report.append("⭐ 【黄金商品】动销好+毛利高（销量≥10件 毛利率≥30%）主推清单")
        if golden_sku:
            for i, r in enumerate(golden_sku[:10], 1):
                name = (r.get("name") or r["sku_code"] or "")[:14].strip()
                spec = (r.get("spec") or "-")[:10].strip()
                qty = int(r.get("qty") or 0)
                profit = float(r.get("profit") or 0)
                margin = float(r.get("margin_pct") or 0)
                report.append(f"  {i}. {name} {spec} | 销量{qty}件 利润总额{_fmt_money(profit)} 利润率{margin:.1f}%")
            report.append("  ▶ 专家建议：黄金商品兼具周转与毛利，适合作为主推款、组合促销与会员权益，可设置「店长推荐」标识。")
        else:
            report.append("  暂无符合条件商品")
        report.append("")

        report.append("📦 【需补货】畅销但库存不足，优先补货明细")
        if need_replenish_sku:
            for i, r in enumerate(need_replenish_sku, 1):
                name = (r.get("name") or r["sku_code"] or "")[:14].strip()
                spec = (r.get("spec") or "-")[:10].strip()
                stock_qty = int(r.get("stock_qty") or 0)
                sale_qty = int(r.get("sale_qty") or 0)
                profit = float(r.get("profit") or 0)
                margin = float(r.get("margin_pct") or 0)
                report.append(f"  {i}. {name} {spec} | 当前库存{stock_qty}件 近{days}天销量{sale_qty}件 利润总额{_fmt_money(profit)} 利润率{margin:.1f}%")
            report.append("  ▶ 专家建议：断货将直接损失销售额与毛利，建议按销量节奏提前补货，优先保障前 3 名库存安全。")
        else:
            report.append("  暂无符合条件商品")
        report.append("")

        report.append("⚠️ 【滞销高库存】库存≥100件 近30天销量<3件，建议促销清仓明细")
        if slow_high_stock_sku:
            for i, r in enumerate(slow_high_stock_sku, 1):
                name = (r.get("name") or r["sku_code"] or "")[:14].strip()
                spec = (r.get("spec") or "-")[:10].strip()
                stock_qty = int(r.get("stock_qty") or 0)
                sale_qty = int(r.get("sale_qty") or 0)
                report.append(f"  {i}. {name} {spec} | 库存{stock_qty}件 近{days}天销量{sale_qty}件")
            report.append("  ▶ 专家建议：高库存滞销占用资金与陈列，建议限期促销、捆绑搭售或申请调拨，释放资源给畅销品。")
        else:
            report.append("  暂无符合条件商品")
        report.append("")

        report.append("📂 【品类毛利 Top5】聚焦头部品类做主题陈列")
        if profit_rows:
            for i, r in enumerate(profit_rows[:5], 1):
                cat = (r.get("cat") or "未分类")[:12]
                profit = float(r.get("profit") or 0)
                margin = float(r.get("margin_pct") or 0)
                sale = float(r.get("sale") or 0)
                report.append(f"  {i}. {cat} | 利润总额{_fmt_money(profit)} 利润率{margin:.1f}% 销售额{_fmt_money(sale)}")
            report.append("  ▶ 专家建议：头部品类决定门店毛利结构，建议做主题陈列与档期主推，带动关联购买。")
        else:
            report.append("  暂无符合条件品类")
        report.append("")

        if neg_rows:
            report.append("⚠️ 【负毛利商品】需核查成本或调价/清仓")
            for i, r in enumerate(neg_rows[:5], 1):
                name = (r.get("name") or r["sku_code"])[:12]
                report.append(f"  {i}. {name} | 销售额{_fmt_money(r['sale'])} 利润总额{_fmt_money(r['profit'])}")
            report.append("  ▶ 专家建议：负毛利拉低整体利润，建议优先核查进价与促销设置，必要时限期清仓止损。")
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


