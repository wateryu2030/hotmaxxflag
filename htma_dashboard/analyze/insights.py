# -*- coding: utf-8 -*-
"""洞察生成 — analyze/insights"""

from datetime import datetime, date


def _row(r, key):
    """安全取行值"""
    if r is None:
        return None
    if isinstance(r, dict):
        return r.get(key)
    if hasattr(r, key):
        return getattr(r, key)
    try:
        return r[key]
    except (IndexError, KeyError, TypeError):
        return None


def _get_price_compare_insights(conn, store_id="沈阳超级仓"):
    """比价预警：近7天降价与价差"""
    insights = []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) AS cnt FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_price_compare'
        """)
        if (cur.fetchone() or {}).get("cnt", 0) == 0:
            return insights
    except Exception:
        return insights
    try:
        cur.execute("""
            SELECT sku_code, price, compare_price, source, created_at
            FROM t_price_compare
            WHERE store_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            ORDER BY created_at DESC LIMIT 5
        """, (store_id,))
        rows = cur.fetchall()
        if rows:
            alerts = []
            for r in rows:
                diff = (float(r["price"] or 0) - float(r["compare_price"] or 0))
                if abs(diff) > 1:
                    pct = diff / float(r["compare_price"] or 1) * 100
                    alerts.append(f"{r['sku_code']} 价差{pct:+.0f}%")
            if alerts:
                insights.append({
                    "type": "info",
                    "title": "比价预警",
                    "desc": "近7天比价发现: " + "; ".join(alerts[:3]),
                    "action": "可在「比价」页面查看详情",
                })
    except Exception:
        pass
    return insights


def build_insights(conn, store_id="沈阳超级仓", drill_context=None):
    """基于数据生成智能分析建议。drill_context 可选：下钻时的 {category, brand, product_name, drill_brands, drill_styles, drill_sku_rank}。"""
    insights = []
    cur = conn.cursor()

    # 1. 品类毛利率分析
    cur.execute("""
        SELECT COALESCE(NULLIF(TRIM(category), ''), '未分类') AS category,
               SUM(sale_amount) AS total_sale, SUM(gross_profit) AS total_profit,
               SUM(gross_profit)/NULLIF(SUM(sale_amount),0)*100 AS margin_pct
        FROM t_htma_sale
        WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
        GROUP BY COALESCE(NULLIF(TRIM(category), ''), '未分类')
        HAVING SUM(sale_amount) > 1000
    """, (store_id,))
    cats = cur.fetchall()
    total_sale = sum(float(c["total_sale"] or 0) for c in cats)
    total_profit = sum(float(c["total_profit"] or 0) for c in cats)
    avg_margin = (total_profit / total_sale * 100) if total_sale > 0 else 0

    low_margin = [c for c in cats if (float(c["margin_pct"] or 0) < 15 and float(c["total_sale"] or 0) > 5000)]
    high_margin = [c for c in cats if float(c["margin_pct"] or 0) >= 35 and float(c["total_sale"] or 0) > 3000]

    if low_margin:
        names = "、".join([c["category"] for c in low_margin[:5]])
        insights.append({"type": "warning", "title": "低毛利品类需关注", "desc": f"{names} 等品类毛利率低于15%，建议检查定价或成本结构。", "action": "可考虑优化采购成本或调整售价策略", "data_source": "t_htma_sale_aggregated", "sources": ["1. 出处：t_htma_sale 近90天按 category 汇总（销售额>1000元）。", "2. 口径：毛利率 = 总毛利/总销售额×100%；低于15%且销售额>5000元记为低毛利品类。"]})
    if high_margin:
        names = "、".join([c["category"] for c in high_margin[:3]])
        insights.append({"type": "success", "title": "高毛利优势品类", "desc": f"{names} 毛利率超过35%，可作为重点推广品类。", "action": "建议加大陈列与促销力度，提升销售占比", "data_source": "t_htma_sale_aggregated", "sources": ["1. 出处：t_htma_sale 近90天按 category 汇总。", "2. 口径：毛利率≥35%且销售额>3000元记为高毛利优势品类。"]})

    # 2. 品类销售贡献度（二八分析）
    sorted_cats = sorted(cats, key=lambda x: float(x["total_sale"] or 0), reverse=True)
    cum, top80_pct = 0, 0
    for i, c in enumerate(sorted_cats):
        cum += float(c["total_sale"] or 0)
        if cum >= total_sale * 0.8 and top80_pct == 0:
            top80_pct = i + 1
            break
    if top80_pct and len(sorted_cats) > 10:
        insights.append({"type": "info", "title": "销售集中度分析", "desc": f"前 {top80_pct} 个品类贡献了约80%销售额，共 {len(sorted_cats)} 个品类。", "action": "可聚焦头部品类做精细化运营，同时关注长尾品类动销", "data_source": "t_htma_sale_aggregated", "sources": ["1. 出处：t_htma_sale 近90天品类销售额汇总，按销售额降序累加。", "2. 理由：累加至≥80%总销售额时的品类数即为「前 N 个贡献约80%」的 N。"]})

    # 3. 低库存预警
    cur.execute("""
        SELECT COUNT(DISTINCT sku_code) AS cnt
        FROM t_htma_stock WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
        AND stock_qty < 50 AND stock_qty >= 0
    """, (store_id, store_id))
    low_stock = cur.fetchone()["cnt"] or 0
    if low_stock > 20:
        insights.append({"type": "warning", "title": "低库存 SKU 较多", "desc": f"共有 {low_stock} 个 SKU 库存低于50，存在断货风险。", "action": "建议及时补货，优先保障畅销品库存", "sources": ["1. 出处：t_htma_stock 最新数据日期的库存快照。", "2. 口径：stock_qty < 50 且 ≥0 的 SKU 数；超过20个即提示断货风险。"]})

    # 4. 负毛利记录
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM t_htma_sale
        WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) AND gross_profit < 0 AND sale_amount > 0
    """, (store_id,))
    neg_profit = cur.fetchone()["cnt"] or 0
    if neg_profit > 0:
        insights.append({"type": "warning", "title": "存在负毛利记录", "desc": f"近30天有 {neg_profit} 条负毛利记录（销售额>0但毛利<0）。", "action": "建议核查成本数据或促销力度是否过大", "data_source": "t_htma_sale_aggregated", "sources": ["1. 出处：t_htma_sale 近30天按行（日×SKU）。", "2. 口径：sale_amount>0 且 gross_profit<0 的记录条数。"]})

    # 5. 整体毛利率健康度
    if avg_margin < 20 and total_sale > 10000:
        insights.append({"type": "warning", "title": "整体毛利率偏低", "desc": f"近90天平均毛利率约 {avg_margin:.1f}%，低于零售业常见水平。", "action": "建议优化品类结构，提升高毛利品类占比", "data_source": "t_htma_sale_aggregated", "sources": ["1. 出处：t_htma_sale 近90天全店汇总（总毛利/总销售额）。", "2. 理由：总销售额>1万时，平均毛利率<20%视为整体偏低。"]})
    elif avg_margin >= 30:
        insights.append({"type": "success", "title": "毛利率表现良好", "desc": f"近90天平均毛利率约 {avg_margin:.1f}%，盈利结构健康。", "action": "可继续保持，关注周转与库存健康", "data_source": "t_htma_sale_aggregated", "sources": ["1. 出处：t_htma_sale 近90天全店汇总。", "2. 理由：平均毛利率≥30%视为盈利结构健康。"]})

    # 6. 动销
    cur.execute("""
        SELECT COUNT(DISTINCT sku_code) AS sku_cnt, SUM(sale_qty) AS total_qty
        FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    """, (store_id,))
    sale_30 = cur.fetchone()
    sku_cnt = sale_30["sku_cnt"] or 0
    total_qty = sale_30["total_qty"] or 0
    if sku_cnt > 100 and total_qty > 0:
        avg_qty = total_qty / sku_cnt
        if avg_qty < 2:
            insights.append({"type": "info", "title": "临期折扣动销分析", "desc": f"近30天 {sku_cnt} 个 SKU 动销，平均每 SKU 销售 {avg_qty:.1f} 件。", "action": "建议关注滞销品类，加快清仓或调整陈列位置", "sources": ["1. 出处：t_htma_sale 近30天动销 SKU 数及总销量。", "2. 口径：平均每 SKU 销量 = 总销量/动销 SKU 数；<2 件视为动销偏弱。"]})
        elif avg_qty > 5:
            insights.append({"type": "success", "title": "动销表现良好", "desc": f"近30天 {sku_cnt} 个 SKU 动销，平均每 SKU 销售 {avg_qty:.1f} 件。", "action": "周转良好，可维持当前补货节奏", "sources": ["1. 出处：t_htma_sale 近30天动销 SKU 数及总销量。", "2. 口径：平均每 SKU 销量>5 件视为动销表现良好。"]})

    # 7. 数据新鲜度
    cur.execute("SELECT MAX(data_date) AS d FROM t_htma_sale WHERE store_id = %s", (store_id,))
    last_date = cur.fetchone()["d"]
    if last_date:
        today = date.today()
        last_d = last_date if hasattr(last_date, 'year') else today
        days_ago = (today - last_d).days
        if days_ago > 3:
            d_str = last_date.strftime("%Y-%m-%d") if hasattr(last_date, "strftime") else str(last_date)
            insights.append({"type": "info", "title": "数据更新提醒", "desc": f"最新销售数据日期为 {d_str}，距今 {days_ago} 天。", "action": "建议定期导入最新数据以保持看板时效性", "sources": ["1. 出处：t_htma_sale 表 MAX(data_date)。", "2. 理由：与当前日期相差>3 天即提示更新。"]})

    # 8. 退货/赠送
    cur.execute("""
        SELECT COALESCE(SUM(sale_amount), 0) AS total_sale, COALESCE(SUM(return_amount), 0) AS return_amt,
               COALESCE(SUM(gift_amount), 0) AS gift_amt
        FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    """, (store_id,))
    rg = cur.fetchone()
    sale_30 = float(rg["total_sale"] or 0)
    return_amt = float(rg["return_amt"] or 0)
    gift_amt = float(rg["gift_amt"] or 0)
    return_ratio = (return_amt / sale_30 * 100) if sale_30 > 0 else 0
    gift_ratio = (gift_amt / sale_30 * 100) if sale_30 > 0 else 0
    if sale_30 > 1000:
        if return_ratio > 5:
            insights.append({"type": "warning", "title": "退货占比偏高", "desc": f"近30天退货金额占比 {return_ratio:.1f}%（退货约 {_fmt_money(return_amt)}），影响净销售。", "action": "建议排查高退货品类与供应商质量，优化验收与陈列减少退货", "sources": ["1. 出处：t_htma_sale 近30天 return_amount、sale_amount 汇总。", "2. 口径：退货占比 = 退货金额/销售额×100%；>5% 即提示偏高。"]})
        elif return_ratio > 0:
            insights.append({"type": "info", "title": "退货与赠送概况", "desc": f"近30天退货金额占比 {return_ratio:.1f}%，赠送金额占比 {gift_ratio:.1f}%。", "action": "可在「经营分析」查看退货/赠送明细，做精细化管控", "sources": ["1. 出处：t_htma_sale 近30天 return_amount、gift_amount、sale_amount。", "2. 口径：退货占比=退货/销售额×100%；赠送占比=赠送/销售额×100%。"]})
        if gift_ratio > 2 and gift_ratio < 15:
            insights.append({"type": "info", "title": "赠送占比", "desc": f"赠送金额占比 {gift_ratio:.1f}%（约 {_fmt_money(gift_amt)}），属促销与引流成本。", "action": "可结合毛利与复购评估赠品 ROI，避免过度赠送", "sources": ["1. 出处：t_htma_sale 近30天 gift_amount、sale_amount。", "2. 理由：赠送占比在 2%～15% 区间单独提示，便于评估促销成本。"]})

    # 9. 品牌集中度
    cur.execute("""
        SELECT COALESCE(NULLIF(TRIM(brand_name), ''), '未填') AS brand_name, SUM(sale_amount) AS sale
        FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        GROUP BY brand_name HAVING SUM(sale_amount) > 0 ORDER BY SUM(sale_amount) DESC LIMIT 5
    """, (store_id,))
    top_brands = cur.fetchall()
    if top_brands and sale_30 > 0:
        top3_sale = sum(float(b["sale"] or 0) for b in top_brands[:3])
        top3_pct = top3_sale / sale_30 * 100
        names = "、".join([(b["brand_name"] or "未填")[:8] for b in top_brands[:3]])
        if top3_pct > 50:
            insights.append({"type": "info", "title": "品牌集中度", "desc": f"前3品牌（{names}）销售占比约 {top3_pct:.0f}%。", "action": "可做品牌级毛利与周转分析，优化采购与陈列资源", "sources": ["1. 出处：t_htma_sale 近30天按 brand_name 汇总销售额，取前5品牌。", "2. 口径：前3品牌销售额/全店销售额×100%；>50% 即品牌集中度较高。"]})

    # 10. 库存周转
    cur.execute("""
        SELECT COALESCE(SUM(stock_amount), 0) AS total_stock
        FROM t_htma_stock WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
    """, (store_id, store_id))
    stock_row = cur.fetchone()
    cur.execute("""
        SELECT COALESCE(SUM(sale_amount), 0) AS sale, COALESCE(SUM(sale_cost), 0) AS cost
        FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    """, (store_id,))
    sale_row = cur.fetchone()
    total_stock = float(stock_row["total_stock"] or 0)
    cost_30 = float(sale_row["cost"] or 0)
    daily_cost = cost_30 / 30 if cost_30 > 0 else 0
    turnover_days = (total_stock / daily_cost) if daily_cost > 0 else None
    if turnover_days is not None and total_stock > 0:
        if turnover_days > 60:
            insights.append({"type": "warning", "title": "库存周转偏慢", "desc": f"按当前销速估算周转天数约 {turnover_days:.0f} 天，库存资金占用较高。", "action": "建议压缩滞销品、加快促销与清仓，提升周转", "sources": ["1. 出处：t_htma_stock 最新日库存金额；t_htma_sale 近30天销售成本。", "2. 口径：周转天数 = 库存金额/(近30天销售成本/30)；>60 天视为偏慢。"]})
        elif turnover_days < 30 and total_stock > 50000:
            insights.append({"type": "success", "title": "周转表现良好", "desc": f"估算周转天数约 {turnover_days:.0f} 天，资金使用效率较好。", "action": "保持补货与动销监控，避免断货", "sources": ["1. 出处：t_htma_stock 最新日库存金额；t_htma_sale 近30天销售成本。", "2. 理由：周转<30 天且库存金额>5万视为周转良好。"]})

    # 11. 数据质量
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM t_htma_sale
        WHERE store_id = %s AND (sale_cost IS NULL OR sale_cost = 0) AND sale_amount > 0
    """, (store_id,))
    missing_cost = cur.fetchone()["cnt"] or 0
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM t_htma_sale
        WHERE store_id = %s AND (sale_price IS NULL OR sale_price = 0) AND sale_qty > 0
    """, (store_id,))
    missing_price = cur.fetchone()["cnt"] or 0
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM (
            SELECT sku_code FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code HAVING COUNT(DISTINCT COALESCE(category, '')) > 1
        ) t
    """, (store_id,))
    inconsistent = cur.fetchone()["cnt"] or 0
    if missing_cost > 100 or missing_price > 100 or inconsistent > 50:
        parts = []
        if missing_cost > 100:
            parts.append(f"成本缺失{missing_cost}条")
        if missing_price > 100:
            parts.append(f"售价缺失{missing_price}条")
        if inconsistent > 50:
            parts.append(f"同SKU多品类{inconsistent}个")
        insights.append({"type": "warning", "title": "数据质量待优化", "desc": "存在 " + "、".join(parts) + "，可能影响毛利与经营分析准确性。", "action": "建议在「经营分析-数据质量」查看明细，优先补全成本与售价", "sources": ["1. 出处：t_htma_sale 中 sale_cost/sale_price 为空或0 的记录数；同 sku_code 多 category 的 SKU 数。", "2. 理由：成本缺失>100 或售价缺失>100 或同 SKU 多品类>50 即提示数据质量待优化。"]})

    # 下钻维度可选建议
    if drill_context:
        drill_brands = drill_context.get("drill_brands") or []
        drill_styles = drill_context.get("drill_styles") or []
        category = (drill_context.get("category") or "").strip()
        brand = (drill_context.get("brand") or "").strip()
        if drill_brands and len(drill_brands) >= 2:
            total_sale = sum(float(b.get("sale_amount") or 0) for b in drill_brands)
            if total_sale > 0:
                top3_sale = sum(float(b.get("sale_amount") or 0) for b in drill_brands[:3])
                pct = top3_sale / total_sale * 100
                if pct >= 50:
                    names = "、".join([(b.get("brand") or "未填")[:8] for b in drill_brands[:3]])
                    scope = f"「{category}」" if category else "当前品类"
                    insights.append({"type": "info", "title": "下钻：品牌集中度较高", "desc": f"{scope}下前3品牌（{names}）销售占比约 {pct:.0f}%。", "action": "可重点维护头部品牌库存与陈列，同时关注长尾品牌动销", "sources": ["1. 出处：消费洞察下钻数据 drill_brands。", "2. 口径：前3品牌销售额/该品类总销售额×100%；≥50% 即集中度较高。"]})
        if drill_styles and len(drill_styles) >= 2 and brand:
            total_sale = sum(float(s.get("sale_amount") or 0) for s in drill_styles)
            if total_sale > 0:
                top3_sale = sum(float(s.get("sale_amount") or 0) for s in drill_styles[:3])
                pct = top3_sale / total_sale * 100
                if pct >= 50:
                    names = "、".join([(s.get("product_name") or "未填")[:8] for s in drill_styles[:3]])
                    scope = f"「{brand}」" if brand else "当前品牌"
                    insights.append({"type": "info", "title": "下钻：款式集中度较高", "desc": f"{scope}下前3款式（{names}）销售占比约 {pct:.0f}%。", "action": "可聚焦畅销款补货与陈列，并评估滞销款清仓或调位", "sources": ["1. 出处：消费洞察下钻数据 drill_styles。", "2. 口径：前3款式销售额/该品牌下总销售额×100%；≥50% 即集中度较高。"]})

    # 比价预警
    try:
        insights.extend(_get_price_compare_insights(conn, store_id))
    except Exception:
        pass

    # ---------- 人力成本分析 ----------
    try:
        _add_labor_insights(conn, store_id, insights)
    except Exception:
        pass

    cur.close()
    return insights


from analyze.report import _fmt_money, _excluded_cond_sale, _excluded_cond_stock, _neg_diagnosis_hint


def build_enhanced_insights(conn, store_id="沈阳超级仓", period_days=30, category_large=None):
    """
    返回增强后的分析卡片数据（结构化），供前端 /api/enhanced_insights 渲染。
    包含：高毛利品类、销售集中度、低库存预警、毛利率表现、动销、退货Top3、库存周转、数据质量、新品（可选）。
    """
    cur = conn.cursor()
    try:
        out = {}
        params = [store_id]
        start_date_cond = f"AND data_date >= DATE_SUB(CURDATE(), INTERVAL {period_days} DAY)"
        large_cond = ""
        if category_large:
            large_cond = " AND category_large = %s"
            params.append(category_large)
        # 高毛利品类 top5
        cur.execute(f"""
            SELECT category, SUM(sale_amount) AS total_sale,
                   SUM(gross_profit) AS total_profit,
                   SUM(gross_profit)/NULLIF(SUM(sale_amount),0)*100 AS margin_pct
            FROM t_htma_sale WHERE store_id = %s {start_date_cond} {large_cond}
            GROUP BY category
            HAVING SUM(sale_amount) > 1000 AND (SUM(gross_profit)/NULLIF(SUM(sale_amount),0)*100) >= 35
            ORDER BY (SUM(gross_profit)/NULLIF(SUM(sale_amount),0)*100) DESC LIMIT 5
        """, params)
        out["high_margin_cats"] = cur.fetchall()
        # 周转分析摘要
        cur.execute(f"""
            SELECT COALESCE(SUM(sale_amount), 0) AS total_sale, COALESCE(SUM(sale_cost), 0) AS total_cost
            FROM t_htma_sale WHERE store_id = %s {start_date_cond}
        """, [store_id])
        sale_sum = cur.fetchone()
        out["period_sale"] = float(sale_sum["total_sale"] or 0)
        out["period_cost"] = float(sale_sum["total_cost"] or 0)
        # 库存
        cur.execute("""
            SELECT COALESCE(SUM(stock_amount), 0) AS stock_amt
            FROM t_htma_stock WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
        """, (store_id, store_id))
        stock_row = cur.fetchone()
        out["stock_amount"] = float(stock_row["stock_amt"] or 0)
        # 库存周转天数
        daily_cost = out["period_cost"] / period_days if period_days > 0 and out["period_cost"] > 0 else 0
        out["turnover_days"] = round(out["stock_amount"] / daily_cost, 1) if daily_cost > 0 else None
        # 低库存 SKU 数
        cur.execute("""
            SELECT COUNT(*) AS cnt FROM t_htma_stock
            WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
            AND stock_qty < 50 AND stock_qty >= 0
        """, (store_id, store_id))
        out["low_stock_sku_count"] = cur.fetchone()["cnt"] or 0
        # 数据质量
        cur.execute(f"""
            SELECT COUNT(*) AS cnt FROM t_htma_sale
            WHERE store_id = %s {start_date_cond} AND (sale_cost IS NULL OR sale_cost = 0) AND sale_amount > 0
        """, [store_id])
        out["missing_cost_count"] = cur.fetchone()["cnt"] or 0
        # 退货Top3
        cur.execute(f"""
            SELECT category, SUM(return_amount) AS return_amt
            FROM t_htma_sale WHERE store_id = %s {start_date_cond} AND COALESCE(return_amount, 0) > 0
            GROUP BY category ORDER BY return_amt DESC LIMIT 3
        """, [store_id])
        out["return_top3"] = cur.fetchall()
        cur.close()
        return out
    except Exception:
        try:
            cur.close()
        except Exception:
            pass
        raise


def _add_labor_insights(conn, store_id, insights):
    """人力成本分析：月度趋势、人效、人力/销售比、岗位分布"""
    import os
    cur = conn.cursor()
    
    # 获取最新月份（假设当前是4月或5月，取最新2个月做对比）
    cur.execute("""
        SELECT DISTINCT report_month FROM t_htma_labor_cost 
        WHERE total_cost > 0 ORDER BY report_month DESC LIMIT 2
    """)
    months = [r["report_month"] for r in cur.fetchall()]
    if len(months) < 1:
        cur.close()
        return
    
    # 解析月份对应的销售起止日期
    def _month_sale_dates(m):
        y, mth = m.split("-")
        start = f"{y}-{mth}-01"
        if mth == "12":
            end = f"{y}-12-31"
        else:
            next_m = int(mth) + 1
            end = f"{y}-{next_m:02d}-01"
        return start, end
    
    labor_data = []
    for m in months:
        cur.execute("""
            SELECT position_type, COUNT(*) as cnt,
                   ROUND(SUM(total_cost),2) as total_cost,
                   ROUND(AVG(work_hours),1) as avg_hours,
                   ROUND(SUM(work_hours),1) as total_hours
            FROM t_htma_labor_cost
            WHERE report_month=%s AND total_cost > 0
            GROUP BY position_type ORDER BY position_type
        """, (m,))
        by_type = cur.fetchall()
        
        cur.execute("""
            SELECT COUNT(*) as cnt, ROUND(SUM(total_cost),2) as total
            FROM t_htma_labor_cost WHERE report_month=%s AND total_cost > 0
        """, (m,))
        summary = cur.fetchone()
        cnt = summary["cnt"] or 0
        labor_total = float(summary["total"] or 0)
        
        start_d, end_d = _month_sale_dates(m)
        cur.execute("""
            SELECT COALESCE(SUM(sale_amount),0) as sale,
                   COALESCE(SUM(COALESCE(gross_profit,0)),0) as profit
            FROM t_htma_sale
            WHERE store_id=%s AND data_date>=%s AND data_date<=%s
        """, (store_id, start_d, end_d))
        sale_row = cur.fetchone()
        sale_amt = float(sale_row["sale"] or 0)
        profit_amt = float(sale_row["profit"] or 0)
        
        labor_data.append({
            "month": m,
            "headcount": cnt,
            "labor_total": labor_total,
            "sale": sale_amt,
            "profit": profit_amt,
            "by_type": by_type,
        })
    
    cur.close()
    
    if not labor_data:
        return
    
    latest = labor_data[0]
    
    # 人力成本占比分析
    sale_amt = latest["sale"]
    profit_amt = latest["profit"]
    labor_total = latest["labor_total"]
    headcount = latest["headcount"]
    labor_sale_ratio = labor_total / sale_amt * 100 if sale_amt else 0
    labor_profit_ratio = labor_total / profit_amt * 100 if profit_amt else 0
    per_person_sale = sale_amt / headcount if headcount else 0
    
    if labor_profit_ratio > 25:
        insights.append({
            "type": "warning", "title": "人力成本占比偏高",
            "desc": f"{latest['month']} 人力成本占毛利 {labor_profit_ratio:.1f}%（人力{labor_total:.0f}元/毛利{profit_amt:.0f}元），每赚1元毛利需花{labor_profit_ratio/100:.2f}元在人力上。",
            "action": "建议优化排班降低低峰期冗余，或调整绩效考核提升人效",
            "sources": ["1. 出处：t_htma_labor_cost 月总和 vs t_htma_sale 月毛利汇总。",
                        "2. 口径：人力成本/毛利额×100%；>25% 提示偏高。"]
        })
    elif labor_profit_ratio > 15:
        insights.append({
            "type": "info", "title": "人力成本占比中等",
            "desc": f"{latest['month']} 人力成本占毛利 {labor_profit_ratio:.1f}%（人力{labor_total:.0f}元），需持续关注趋势变化。",
            "action": "建议每月监控人力/毛利比，设定预警线",
            "sources": ["1. 出处：t_htma_labor_cost 月总和 vs t_htma_sale 月毛利。"]
        })
    
    # 人效趋势（如果有两个月数据对比）
    if len(labor_data) >= 2:
        prev = labor_data[1]
        pct_hc = (latest["headcount"] - prev["headcount"]) / prev["headcount"] * 100 if prev["headcount"] else 0
        pct_sale = (sale_amt - prev["sale"]) / prev["sale"] * 100 if prev["sale"] else 0
        prev_pps = prev["sale"] / prev["headcount"] if prev["headcount"] else 0
        pct_pps = (per_person_sale - prev_pps) / prev_pps * 100 if prev_pps else 0
        
        insight_desc = (
            f"对比{prev['month']}→{latest['month']}：人员{prev['headcount']}→{headcount}人（{pct_hc:+.1f}%），"
            f"销售额{prev['sale']:.0f}→{sale_amt:.0f}（{pct_sale:+.1f}%），"
            f"人均销售{prev_pps:.0f}→{per_person_sale:.0f}（{pct_pps:+.1f}%）。"
        )
        
        if pct_pps > 10:
            insights.append({
                "type": "success", "title": "人效显著提升",
                "desc": insight_desc,
                "action": "人员精简效果明显，建议保持并关注服务质量与员工满意度",
                "sources": ["1. 出处：t_htma_labor_cost 人数 vs t_htma_sale 月总额。",
                            "2. 口径：人均销售 = 月销售额/人数。"]
            })
        elif pct_pps < -5:
            insights.append({
                "type": "warning", "title": "人效下滑需关注",
                "desc": insight_desc,
                "action": "建议排查是否因人员扩张过快或销售疲软，优化排班与激励",
                "sources": ["1. 出处：t_htma_labor_cost 人数 vs t_htma_sale 月总额。"]
            })
        else:
            insights.append({
                "type": "info", "title": "人效趋势分析",
                "desc": insight_desc,
                "action": "可结合品类结构与岗位分布进一步分析提升空间",
                "sources": ["1. 出处：t_htma_labor_cost 人数 vs t_htma_sale 月总额。"]
            })
    
    # 人力成本结构分析（最新月）
    by_type = latest.get("by_type", [])
    if by_type:
        type_parts = []
        for t in by_type:
            tp = t["position_type"]
            cnt = t["cnt"]
            tc = float(t["total_cost"])
            pct = tc / labor_total * 100 if labor_total else 0
            label = {"fulltime": "组员", "leader": "组长", "management": "管理", "cleaner": "保洁"}.get(tp, tp)
            type_parts.append(f"{label}{cnt}人({pct:.0f}%)")
        insights.append({
            "type": "info", "title": "人力成本结构",
            "desc": f"{latest['month']} 人力结构：" + "、".join(type_parts) + f"。总成本约{labor_total:.0f}元，人均{latest['labor_total']/headcount:.0f}元/月。",
            "action": "管理岗占比较高时可考虑职能合并或扁平化",
            "sources": ["1. 出处：t_htma_labor_cost 按 position_type 汇总。",
                        "2. 口径：管理岗占比=管理岗成本/总人力成本×100%。"]
        })

    # 人力成本月份趋势（输入完整月度数据）
    try:
        cur2 = conn.cursor()
        cur2.execute("""
            SELECT report_month, COUNT(*) as cnt, ROUND(SUM(total_cost),2) as t
            FROM t_htma_labor_cost WHERE total_cost > 0
            GROUP BY report_month ORDER BY report_month
        """)
        all_months = cur2.fetchall()
        cur2.close()
        if len(all_months) >= 2:
            trend_parts = [f"{r['report_month']}={r['cnt']}人({r['t']:.0f}元)" for r in all_months[-6:]]
            insights.append({
                "type": "info", "title": "月度人力成本趋势",
                "desc": "近6个月人力变化：" + " → ".join(trend_parts),
                "action": "可在「人力分析报告」页面查看详细趋势图",
                "sources": ["1. 出处：t_htma_labor_cost 按月汇总。",
                            "2. 口径：当月总人力成本（不含离职和成本为0的记录）。"]
            })
    except Exception:
        pass
