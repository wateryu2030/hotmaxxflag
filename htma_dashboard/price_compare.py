#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
货盘价格对比分析 - 4 阶段闭环
阶段1：自有数据标准化（OpenCLAW 逻辑）
阶段2：竞品价格检索（百度 Skill 占位，可接入真实 API）
阶段3：价格对比与指标量化
阶段4：货盘分层分析与决策输出
"""
import os
import re
import time
from datetime import datetime, date, timedelta
from typing import Optional, Callable

# 单位标准化映射
_UNIT_MAP = {
    "克": "g", "千克": "kg", "公斤": "kg", "毫升": "ml", "升": "L",
    "斤": "500g", "两": "50g", "盒": "盒", "袋": "袋", "瓶": "瓶",
    "包": "包", "罐": "罐", "桶": "桶", "支": "支", "片": "片",
}
# 过滤词（促销等无关信息）
_FILTER_WORDS = ("特价", "促销", "包邮", "限时", "秒杀", "清仓", "亏本", "爆款", "热卖")
# 价格优势率分层阈值
_TIER_HIGH = 20      # ≥20% 高优势
_TIER_MID = 5        # 5%~20% 中等
_TIER_LOW = 0        # 0~5% 无优势
# <0% 价格劣势


def stage1_standardize(conn, store_id: str = "沈阳超级仓", days: int = 30, limit: int = 200) -> list[dict]:
    """
    阶段1：自有数据标准化
    从 t_htma_sale + t_htma_stock 导出并清洗，形成可检索的商品数据集。
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT s.sku_code,
               COALESCE(st.product_name, s.product_name, s.sku_code) AS raw_name,
               MAX(COALESCE(st.spec, s.spec)) AS spec,
               MAX(COALESCE(st.brand_name, s.brand_name)) AS brand_name,
               MAX(COALESCE(st.barcode, s.barcode)) AS barcode,
               MAX(s.category) AS category, MAX(s.category_large) AS category_large,
               MAX(s.category_mid) AS category_mid, MAX(s.category_small) AS category_small,
               SUM(s.sale_qty) AS sale_qty, SUM(s.sale_amount) AS sale_amount,
               SUM(s.gross_profit) AS gross_profit,
               SUM(s.sale_amount)/NULLIF(SUM(s.sale_qty),0) AS unit_price
        FROM t_htma_sale s
        LEFT JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s
          AND s.data_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
          AND COALESCE(s.category_small,'') NOT LIKE %s
          AND COALESCE(s.category_small,'') NOT LIKE %s
          AND COALESCE(s.category_small,'') NOT LIKE %s
        GROUP BY s.sku_code, st.product_name, s.product_name, s.category, s.category_large, s.category_mid, s.category_small
        HAVING SUM(s.sale_amount) > 100 AND SUM(s.sale_qty) >= 1
        ORDER BY SUM(s.sale_amount) DESC
        LIMIT %s
    """, (store_id, store_id, days, "%购物袋%", "%包装袋%", "%塑料袋%", int(limit)))
    rows = cur.fetchall()
    cur.close()

    out = []
    for r in rows:
        raw = (r.get("raw_name") or r.get("sku_code") or "").strip()
        if not raw:
            continue
        # 数据清洗
        name = _clean_product_name(raw)
        if not name or len(name) < 2:
            continue
        unit_price = float(r.get("unit_price") or 0)
        if unit_price <= 0 or unit_price > 10000:
            continue
        out.append({
            "sku_code": r["sku_code"],
            "raw_name": raw[:64],
            "std_name": name[:128],
            "spec": (r.get("spec") or "")[:32],
            "brand_name": (r.get("brand_name") or "")[:32],
            "barcode": (r.get("barcode") or "")[:32],
            "category": (r.get("category") or "")[:32],
            "category_large": (r.get("category_large") or "")[:32],
            "category_mid": (r.get("category_mid") or "")[:32],
            "category_small": (r.get("category_small") or "")[:32],
            "sale_qty": float(r.get("sale_qty") or 0),
            "sale_amount": float(r.get("sale_amount") or 0),
            "gross_profit": float(r.get("gross_profit") or 0),
            "unit_price": unit_price,
        })
    return out


def stage1_standardize_single_day(
    conn, store_id: str = "沈阳超级仓", data_date: Optional[date] = None, limit: int = 50
) -> list[dict]:
    """
    按单日销售筛选：指定日期的动销商品，按当日销售额排序取前 limit 个。
    用于每日自动比价：只对当天（或昨日）销售占比高、销售额大的商品比价。
    data_date 为 None 时自动选择：优先今日，无数据则昨日。
    """
    cur = conn.cursor()
    if data_date is None:
        cur.execute(
            """SELECT data_date FROM t_htma_sale WHERE store_id = %s AND data_date <= CURDATE()
               GROUP BY data_date ORDER BY data_date DESC LIMIT 2""",
            (store_id,),
        )
        rows = cur.fetchall()
        if not rows:
            cur.close()
            return []
        data_date = rows[0]["data_date"]
        if isinstance(data_date, datetime):
            data_date = data_date.date()
    cur.execute("""
        SELECT s.sku_code,
               COALESCE(st.product_name, s.product_name, s.sku_code) AS raw_name,
               MAX(COALESCE(st.spec, s.spec)) AS spec,
               MAX(COALESCE(st.brand_name, s.brand_name)) AS brand_name,
               MAX(COALESCE(st.barcode, s.barcode)) AS barcode,
               MAX(s.category) AS category, MAX(s.category_large) AS category_large,
               MAX(s.category_mid) AS category_mid, MAX(s.category_small) AS category_small,
               SUM(s.sale_qty) AS sale_qty, SUM(s.sale_amount) AS sale_amount,
               SUM(s.gross_profit) AS gross_profit,
               SUM(s.sale_amount)/NULLIF(SUM(s.sale_qty),0) AS unit_price
        FROM t_htma_sale s
        LEFT JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s AND s.data_date = %s
          AND COALESCE(s.category_small,'') NOT LIKE %s
          AND COALESCE(s.category_small,'') NOT LIKE %s
          AND COALESCE(s.category_small,'') NOT LIKE %s
        GROUP BY s.sku_code, st.product_name, s.product_name, s.category, s.category_large, s.category_mid, s.category_small
        HAVING SUM(s.sale_amount) > 0 AND SUM(s.sale_qty) >= 1
        ORDER BY SUM(s.sale_amount) DESC
        LIMIT %s
    """, (store_id, store_id, data_date, "%购物袋%", "%包装袋%", "%塑料袋%", int(limit)))
    rows = cur.fetchall()
    cur.close()
    out = []
    for r in rows:
        raw = (r.get("raw_name") or r.get("sku_code") or "").strip()
        if not raw:
            continue
        name = _clean_product_name(raw)
        if not name or len(name) < 2:
            continue
        unit_price = float(r.get("unit_price") or 0)
        if unit_price <= 0 or unit_price > 10000:
            continue
        out.append({
            "sku_code": r["sku_code"],
            "raw_name": raw[:64],
            "std_name": name[:128],
            "spec": (r.get("spec") or "")[:32],
            "brand_name": (r.get("brand_name") or "")[:32],
            "barcode": (r.get("barcode") or "")[:32],
            "category": (r.get("category") or "")[:32],
            "category_large": (r.get("category_large") or "")[:32],
            "category_mid": (r.get("category_mid") or "")[:32],
            "category_small": (r.get("category_small") or "")[:32],
            "sale_qty": float(r.get("sale_qty") or 0),
            "sale_amount": float(r.get("sale_amount") or 0),
            "gross_profit": float(r.get("gross_profit") or 0),
            "unit_price": unit_price,
        })
    return out


def sync_platform_products(conn, store_id: str = "沈阳超级仓", days: int = 30, limit: int = 500) -> int:
    """
    将平台商品（大类/中类/小类、规格、条码）同步到 t_htma_platform_products 表。
    返回同步条数。
    """
    items = stage1_standardize(conn, store_id=store_id, days=days, limit=limit)
    if not items:
        return 0
    cur = conn.cursor()
    cnt = 0
    for it in items:
        cur.execute("""
            INSERT INTO t_htma_platform_products
            (store_id, sku_code, product_name, raw_name, spec, barcode, brand_name,
             category, category_large, category_mid, category_small,
             category_large_code, category_mid_code, category_small_code,
             unit_price, sale_qty, sale_amount, gross_profit, sync_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON DUPLICATE KEY UPDATE
            product_name=VALUES(product_name), raw_name=VALUES(raw_name),
            spec=VALUES(spec), barcode=VALUES(barcode), brand_name=VALUES(brand_name),
            category=VALUES(category), category_large=VALUES(category_large),
            category_mid=VALUES(category_mid), category_small=VALUES(category_small),
            category_large_code=VALUES(category_large_code), category_mid_code=VALUES(category_mid_code),
            category_small_code=VALUES(category_small_code),
            unit_price=VALUES(unit_price), sale_qty=VALUES(sale_qty),
            sale_amount=VALUES(sale_amount), gross_profit=VALUES(gross_profit),
            sync_at=NOW()
        """, (
            store_id, it.get("sku_code"), it.get("std_name"), it.get("raw_name"),
            it.get("spec") or "", it.get("barcode") or "", it.get("brand_name") or "",
            it.get("category") or "", it.get("category_large") or "", it.get("category_mid") or "",
            it.get("category_small") or "", "", "", "",
            it.get("unit_price"), it.get("sale_qty"), it.get("sale_amount"), it.get("gross_profit"),
        ))
        cnt += cur.rowcount
    conn.commit()
    cur.close()
    return cnt


def load_platform_products_from_db(conn, store_id: str = "沈阳超级仓", limit: int = 500) -> list[dict]:
    """
    从 t_htma_platform_products 表读取商品列表（按大类/中类/小类）。
    若表为空则返回 []。
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT sku_code, raw_name, product_name, spec, barcode, brand_name,
               category, category_large, category_mid, category_small,
               unit_price, sale_qty, sale_amount, gross_profit
        FROM t_htma_platform_products
        WHERE store_id = %s
        ORDER BY sale_amount DESC
        LIMIT %s
    """, (store_id, int(limit)))
    rows = cur.fetchall()
    cur.close()
    return [
        {
            "sku_code": r.get("sku_code", ""),
            "raw_name": r.get("raw_name") or r.get("product_name", ""),
            "spec": r.get("spec") or "",
            "barcode": r.get("barcode") or "",
            "brand_name": r.get("brand_name") or "",
            "category_large": r.get("category_large") or "未分类",
            "category_mid": r.get("category_mid") or "未分类",
            "category_small": r.get("category_small") or "未分类",
            "unit_price": round(float(r.get("unit_price") or 0), 2),
            "sale_qty": float(r.get("sale_qty") or 0),
            "sale_amount": round(float(r.get("sale_amount") or 0), 2),
        }
        for r in rows
    ]


def build_search_keyword(item: dict) -> str:
    """
    构建京东/淘宝模糊匹配搜索关键词。
    优先：品牌 + 品名 + 规格；若无具体品名则用品类+规格补充。
    空格分隔便于电商平台模糊匹配。
    """
    raw = (item.get("raw_name") or "").strip()
    spec = (item.get("spec") or "").strip()
    brand = (item.get("brand_name") or "").strip()
    cat_small = (item.get("category_small") or "").strip()
    cat = (item.get("category") or "").strip()

    # 排除「好特卖」等门店名作为品牌
    if brand and brand in ("好特卖", "好特卖超级仓", "门店"):
        brand = ""

    parts = []
    if brand and len(brand) >= 2:
        parts.append(brand)
    # 品名：若太短或像品类名（如「羽绒服」「浆果类」），用品类补充
    if raw and len(raw) >= 2:
        generic = raw in (cat, cat_small, item.get("category_large") or "")
        if generic and (cat_small or cat):
            parts.append(cat_small or cat)
        else:
            parts.append(raw)
    elif cat_small or cat:
        parts.append(cat_small or cat)
    if spec and len(spec) >= 1:
        parts.append(spec)

    kw = " ".join(p for p in parts if p)[:40]
    return kw if kw else (raw or cat_small or cat or "商品")[:30]


def _clean_product_name(raw: str) -> str:
    """OpenCLAW 逻辑：过滤无关词、统一单位、去特殊符号"""
    s = raw
    for w in _FILTER_WORDS:
        s = re.sub(rf"{re.escape(w)}", "", s, flags=re.I)
    for cn, en in _UNIT_MAP.items():
        if en in ("盒", "袋", "瓶", "包", "罐", "桶", "支", "片"):
            continue
        s = re.sub(rf"(\d+)\s*{re.escape(cn)}\b", rf"\1{en}", s, flags=re.I)
    s = re.sub(r"[【】\[\]()（）\*#@]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def stage2_fetch_competitor_price(
    item: dict,
    fetcher: Optional[Callable[[dict], Optional[dict]]] = None,
) -> Optional[dict]:
    """
    阶段2：竞品价格检索
    fetcher: 接收完整 item（含 barcode、raw_name、std_name、spec），
    内部「条码优先、名称+规格为辅」检索。返回 {min_price, platform, is_same_spec} 或 None。
    """
    if not fetcher or not isinstance(item, dict):
        return None
    return fetcher(item)


def stage2_mock_fetcher(std_name: str) -> Optional[dict]:
    """
    模拟检索：根据商品名生成模拟竞品价（用于调试）。
    接入百度 Skill 后替换为真实 API 调用。
    """
    # 简单模拟：根据名称长度和字符生成一个「假」最低价
    base = 10.0
    for c in std_name:
        if c.isdigit():
            base += ord(c) % 5
        elif "\u4e00" <= c <= "\u9fff":
            base += 0.5
    base = min(max(base, 3), 200)
    return {"min_price": round(base * 1.15, 2), "platform": "模拟", "is_same_spec": True}


def stage3_calc_advantage(
    items: list[dict],
    fetcher: Optional[Callable[[str], Optional[dict]]] = None,
    use_mock: bool = True,
    fetch_limit: Optional[int] = None,
) -> list[dict]:
    """
    阶段3：价格对比与指标量化
    价格优势率 = (竞品最低价 - 好特卖售价) / 竞品最低价 * 100%
    fetch_limit: 使用真实 fetcher 时，仅对前 N 个商品调用 API，其余标为独家款，用于控制成本
    """
    get_price = fetcher or (stage2_mock_fetcher if use_mock else None)
    out = []
    for idx, it in enumerate(items):
        ht_price = float(it.get("unit_price") or 0)
        if ht_price <= 0:
            continue
        # 真实 API 时，可限制调用次数以控制成本；模拟模式不限制
        do_fetch = get_price and (not fetcher or fetch_limit is None or idx < fetch_limit)
        if fetcher and do_fetch:
            time.sleep(0.12)  # 限流，避免第三方 API 超频
        comp = stage2_fetch_competitor_price(it, get_price if do_fetch else None) if get_price else None
        if not comp or comp.get("min_price") is None or float(comp.get("min_price") or 0) <= 0:
            it["advantage_pct"] = None
            it["competitor_min"] = None
            it["tier"] = "独家款"
            it["platform"] = None
            it["jd_min_price"] = None
            it["jd_platform"] = None
            it["taobao_min_price"] = None
            it["taobao_platform"] = None
        else:
            comp_min = float(comp["min_price"])
            adv = (comp_min - ht_price) / comp_min * 100 if comp_min > 0 else 0
            it["advantage_pct"] = round(adv, 1)
            it["competitor_min"] = comp_min
            it["platform"] = comp.get("platform", "")
            it["jd_min_price"] = comp.get("jd_min_price")
            it["jd_platform"] = comp.get("jd_platform")
            it["taobao_min_price"] = comp.get("taobao_min_price")
            it["taobao_platform"] = comp.get("taobao_platform")
            if adv >= _TIER_HIGH:
                it["tier"] = "高优势款"
            elif adv >= _TIER_MID:
                it["tier"] = "中等优势款"
            elif adv >= _TIER_LOW:
                it["tier"] = "无优势款"
            else:
                it["tier"] = "价格劣势款"
        out.append(it)
    return out


def stage4_portfolio_analysis(items: list[dict]) -> dict:
    """
    阶段4：货盘分层分析与决策输出
    按价格优势率分层，结合库存/分类输出策略。
    """
    tiers = {
        "高优势款": [],
        "中等优势款": [],
        "无优势款": [],
        "价格劣势款": [],
        "独家款": [],
    }
    for it in items:
        t = it.get("tier", "独家款")
        if t in tiers:
            tiers[t].append(it)

    strategies = []
    if tiers["高优势款"]:
        names = [x["std_name"][:12] for x in sorted(tiers["高优势款"], key=lambda x: -x.get("advantage_pct", 0))[:5]]
        strategies.append(f"【高优势款】{len(tiers['高优势款'])} 个，价格优势≥20%，重点主推：{', '.join(names)}")
    if tiers["中等优势款"]:
        strategies.append(f"【中等优势款】{len(tiers['中等优势款'])} 个，优势5%~20%，维持现状")
    if tiers["无优势款"]:
        strategies.append(f"【无优势款】{len(tiers['无优势款'])} 个，优势0~5%，可微调定价或组合销售")
    if tiers["价格劣势款"]:
        names = [x["std_name"][:10] for x in tiers["价格劣势款"][:3]]
        strategies.append(f"【价格劣势款】{len(tiers['价格劣势款'])} 个，建议清库存/替换供应商：{', '.join(names)}")
    if tiers["独家款"]:
        strategies.append(f"【独家款】{len(tiers['独家款'])} 个，无竞品，可提升毛利或差异化主推")

    return {
        "tiers": tiers,
        "strategies": strategies,
        "summary": {
            "total": len(items),
            "high": len(tiers["高优势款"]),
            "mid": len(tiers["中等优势款"]),
            "low": len(tiers["无优势款"]),
            "disadvantage": len(tiers["价格劣势款"]),
            "exclusive": len(tiers["独家款"]),
        },
    }


def run_full_pipeline(
    conn,
    store_id: str = "沈阳超级仓",
    days: int = 30,
    use_mock_fetcher: bool = True,
    fetcher: Optional[Callable[[str], Optional[dict]]] = None,
    save_to_db: bool = True,
    fetch_limit: Optional[int] = None,
) -> dict:
    """执行完整 4 阶段闭环，返回货盘分析结果。fetcher 优先使用传入的，否则尝试 baidu_fetcher 已配置的。
    fetch_limit: 真实 API 时仅对前 N 个商品比价，其余标为独家款，用于控制成本（如 50）"""
    fetcher_error = None
    fetcher_platform = "jd"  # 用于报告提示
    if fetcher is None:
        try:
            from baidu_fetcher import get_configured_fetcher, onebound_test_ok, ONEBOUND_PLATFORM, ONEBOUND_KEY, ONEBOUND_SECRET
            fetcher = get_configured_fetcher()
            fetcher_platform = (ONEBOUND_PLATFORM or "jd").lower()
            # OneBound 预检：双平台或单平台 fetcher 只要用万邦就做预检，便于报告提示
            if fetcher and (ONEBOUND_KEY and ONEBOUND_SECRET):
                ok, err = onebound_test_ok()
                if not ok:
                    fetcher_error = err
        except ImportError:
            fetcher = None
    use_mock = use_mock_fetcher and fetcher is None
    items = stage1_standardize(conn, store_id, days)
    items = stage3_calc_advantage(items, fetcher=fetcher, use_mock=use_mock, fetch_limit=fetch_limit)
    portfolio = stage4_portfolio_analysis(items)
    run_at = datetime.now()

    if save_to_db:
        try:
            cur = conn.cursor()
            # 实体化保存：含京东/淘宝分平台价格、raw_name、spec、barcode（需先执行 09_price_compare_jd_taobao.sql）
            rows_ext = [
                (run_at, store_id, days,
                 it.get("sku_code"), it.get("std_name"), it.get("raw_name"), it.get("spec"), it.get("barcode"),
                 it.get("category"), it.get("unit_price"),
                 it.get("jd_min_price"), it.get("jd_platform"),
                 it.get("taobao_min_price"), it.get("taobao_platform"),
                 it.get("competitor_min"), it.get("advantage_pct"), it.get("tier"), it.get("platform"))
                for it in items
            ]
            sql_ext = """INSERT INTO t_htma_price_compare
                (run_at, store_id, days, sku_code, std_name, raw_name, spec, barcode,
                 category, unit_price, jd_min_price, jd_platform, taobao_min_price, taobao_platform,
                 competitor_min, advantage_pct, tier, platform)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
            try:
                cur.executemany(sql_ext, rows_ext)
            except Exception:
                rows_legacy = [
                    (run_at, store_id, days, it.get("sku_code"), it.get("std_name"), it.get("category"),
                     it.get("unit_price"), it.get("competitor_min"), it.get("advantage_pct"), it.get("tier"), it.get("platform"))
                    for it in items
                ]
                cur.executemany(
                    """INSERT INTO t_htma_price_compare
                       (run_at, store_id, days, sku_code, std_name, category, unit_price,
                        competitor_min, advantage_pct, tier, platform)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    rows_legacy,
                )
            conn.commit()
            cur.close()
        except Exception:
            pass  # 表可能不存在，静默跳过

    return {
        "items": items,
        "portfolio": portfolio,
        "run_at": run_at.isoformat(),
        "store_id": store_id,
        "days": days,
        "use_real_fetcher": fetcher is not None,
        "fetcher_error": fetcher_error,
        "fetcher_platform": fetcher_platform,
    }


def run_daily_top_compare(
    conn,
    store_id: str = "沈阳超级仓",
    data_date: Optional[date] = None,
    limit: int = 50,
    use_mock_fetcher: bool = False,
    fetcher: Optional[Callable] = None,
    save_to_db: bool = True,
    fetch_limit: Optional[int] = None,
) -> dict:
    """
    按单日销售筛选后的比价流水线：用于每日自动比价。
    筛选当日（或最近有数据的日期）销售额最高的 limit 个商品，执行比价并返回结果。
    """
    items = stage1_standardize_single_day(conn, store_id=store_id, data_date=data_date, limit=limit)
    if not items:
        return {
            "items": [],
            "portfolio": {"tiers": {}, "strategies": [], "summary": {"total": 0}},
            "run_at": datetime.now().isoformat(),
            "store_id": store_id,
            "days": 0,
            "data_date": str(data_date) if data_date else None,
            "use_real_fetcher": False,
            "fetcher_error": None,
            "fetcher_platform": "",
        }
    if data_date is None:
        cur = conn.cursor()
        cur.execute(
            """SELECT data_date FROM t_htma_sale WHERE store_id = %s AND data_date <= CURDATE()
               ORDER BY data_date DESC LIMIT 1""",
            (store_id,),
        )
        r = cur.fetchone()
        cur.close()
        if r:
            data_date = r["data_date"]
            if isinstance(data_date, datetime):
                data_date = data_date.date()
    if fetcher is None:
        try:
            from baidu_fetcher import get_configured_fetcher
            fetcher = get_configured_fetcher()
        except ImportError:
            fetcher = None
    use_mock = use_mock_fetcher and fetcher is None
    items = stage3_calc_advantage(items, fetcher=fetcher, use_mock=use_mock, fetch_limit=fetch_limit or limit)
    portfolio = stage4_portfolio_analysis(items)
    run_at = datetime.now()
    if save_to_db:
        try:
            cur = conn.cursor()
            rows_ext = [
                (run_at, store_id, 0,
                 it.get("sku_code"), it.get("std_name"), it.get("raw_name"), it.get("spec"), it.get("barcode"),
                 it.get("category"), it.get("unit_price"),
                 it.get("jd_min_price"), it.get("jd_platform"),
                 it.get("taobao_min_price"), it.get("taobao_platform"),
                 it.get("competitor_min"), it.get("advantage_pct"), it.get("tier"), it.get("platform"))
                for it in items
            ]
            sql_ext = """INSERT INTO t_htma_price_compare
                (run_at, store_id, days, sku_code, std_name, raw_name, spec, barcode,
                 category, unit_price, jd_min_price, jd_platform, taobao_min_price, taobao_platform,
                 competitor_min, advantage_pct, tier, platform)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
            try:
                cur.executemany(sql_ext, rows_ext)
            except Exception:
                rows_legacy = [
                    (run_at, store_id, 0, it.get("sku_code"), it.get("std_name"), it.get("category"),
                     it.get("unit_price"), it.get("competitor_min"), it.get("advantage_pct"), it.get("tier"), it.get("platform"))
                    for it in items
                ]
                cur.executemany(
                    """INSERT INTO t_htma_price_compare
                       (run_at, store_id, days, sku_code, std_name, category, unit_price,
                        competitor_min, advantage_pct, tier, platform)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    rows_legacy,
                )
            conn.commit()
            cur.close()
        except Exception:
            pass
    return {
        "items": items,
        "portfolio": portfolio,
        "run_at": run_at.isoformat(),
        "store_id": store_id,
        "days": 0,
        "data_date": str(data_date) if data_date else None,
        "use_real_fetcher": fetcher is not None,
        "fetcher_error": None,
        "fetcher_platform": "jd",
    }


def format_report(result: dict) -> str:
    """将货盘分析结果格式化为可读报告，含「好特卖商品/规格 vs 其他平台价格」表格"""
    p = result.get("portfolio", {})
    strategies = p.get("strategies", [])
    summary = p.get("summary", {})
    items = result.get("items", [])
    data_date = result.get("data_date")
    if data_date:
        period_line = f"分析日期：{data_date}（当日销售TOP） | 门店：{result.get('store_id', '')}"
    else:
        period_line = f"分析周期：近{result.get('days', 30)}天 | 门店：{result.get('store_id', '')}"
    lines = [
        "【货盘价格对比分析报告】",
        period_line,
        f"有效商品数：{summary.get('total', 0)}",
        "",
        "━━━ 货盘分层 ━━━",
    ]
    lines.extend(strategies)
    # 当使用真实 API 且全部为独家款时，给出排查提示
    total = summary.get("total", 0)
    exclusive = summary.get("exclusive", 0)
    if result.get("use_real_fetcher") and total > 0 and exclusive == total:
        lines.append("")
        lines.append("【排查提示】本次比价全部未命中竞品（均为独家款），可能原因：")
        lines.append("1) .env 未配置 ONEBOUND_KEY/ONEBOUND_SECRET 或 PDD_HOJINGKE_APIKEY；")
        lines.append("2) 万邦控制台未开通京东/淘宝 item_search 接口（与 key 用量/权限有关）；")
        lines.append("3) 蚂蚁星球需在开发者中心完成京东联盟设置。建议先配置后重试或联系管理员。")
    if result.get("fetcher_error"):
        lines.append("")
        lines.append(f"【接口预检】竞品接口异常：{result.get('fetcher_error')}")
    lines.append("")
    # 表格：好特卖商品、规格、好特卖售价、竞品最低价、竞品来源、价格优势%
    lines.append("━━━ 比价明细表（好特卖 vs 其他平台） ━━━")
    lines.append("（检索逻辑：条码优先；条码无结果/无条码时用「商品名称+规格」关键词）")
    w_name, w_spec = 20, 12
    sep = "+" + "-" * (w_name + 2) + "+" + "-" * (w_spec + 2) + "+" + "-" * 14 + "+" + "-" * 14 + "+" + "-" * 16 + "+" + "-" * 10 + "+"
    lines.append(sep)
    lines.append(f"| {'品名':<{w_name}} | {'规格':<{w_spec}} | {'好特卖售价(元)':>12} | {'竞品最低价(元)':>12} | {'竞品来源':>14} | {'价格优势%':>8} |")
    lines.append(sep)
    for it in items[:80]:  # 最多 80 行，避免过长
        name = ((it.get("raw_name") or it.get("std_name") or "")[:w_name]).strip()
        spec = (it.get("spec") or "-")[:w_spec]
        ht = it.get("unit_price")
        ht_s = f"{ht:.2f}" if ht is not None else "-"
        comp = it.get("competitor_min")
        comp_s = f"{comp:.2f}" if comp is not None else "-"
        plat = (it.get("platform") or "-")[:14]
        adv = it.get("advantage_pct")
        adv_s = f"{adv}%" if adv is not None else "-"
        lines.append(f"| {name:<{w_name}} | {spec:<{w_spec}} | {ht_s:>12} | {comp_s:>12} | {plat:>14} | {adv_s:>8} |")
    if len(items) > 80:
        lines.append("")
        lines.append(f"（共 {len(items)} 条，上表仅展示前 80 条）")
    lines.append(sep)
    lines.append("")
    lines.append("━━━ 高优势款 Top10（可主推） ━━━")
    high = [x for x in items if x.get("tier") == "高优势款"]
    high.sort(key=lambda x: -(x.get("advantage_pct") or 0))
    for i, it in enumerate(high[:10], 1):
        adv = it.get("advantage_pct")
        adv_s = f"{adv}%" if adv is not None else "N/A"
        lines.append(f"  {i}. {it.get('std_name','')[:16]} | 售价{it.get('unit_price',0):.1f}元 竞品最低{it.get('competitor_min') or '-'}元 优势{adv_s}")
    lines.append("")
    if result.get("use_real_fetcher"):
        platforms = {it.get("platform") for it in items if it.get("platform") and it.get("platform") != "模拟"}
        plat_str = "、".join(p for p in platforms if p) or "真实API"
        lines.append(f"（注：竞品价来自 {plat_str}）")
    elif result.get("fetcher_error"):
        err = (result["fetcher_error"] or "")[:70]
        if len((result["fetcher_error"] or "")) > 70:
            err = err.rstrip() + "…"
        plat = "京东" if (result.get("fetcher_platform") or "jd") == "jd" else "淘宝"
        lines.append(f"（注：OneBound 接口异常，当前为模拟数据。{err} 请在控制台开通{plat} item_search 接口。）")
    else:
        lines.append("（注：竞品价为模拟数据。配置 ONEBOUND_KEY/SECRET 或 JUHE_PRICE_KEY 可接入真实比价，见 .env.example 与 docs/货盘价格对比分析.md）")
    lines.append(f"--- 报告生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M')} ---")
    return "\n".join(lines)
