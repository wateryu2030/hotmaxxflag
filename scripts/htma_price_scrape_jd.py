#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
好特卖货盘 - 京东自主比价（Playwright 爬取）
从 DB 挑选部分商品，用浏览器打开京东搜索页，提取竞品最低价。
无需 OneBound 等付费 API，适合小规模抽样比价。
用法：python scripts/htma_price_scrape_jd.py [--limit 15] [--headless]
"""
import argparse
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "htma_dashboard"))

def _parse_price(s: str) -> float | None:
    """从文本提取数字价格"""
    if not s:
        return None
    s = str(s).replace(",", "").replace("￥", "").strip()
    m = re.search(r"(\d+\.?\d*)", s)
    return float(m.group(1)) if m else None


def _fetch_jd_price_api(sku_ids: list[str], timeout: int = 6) -> list[float]:
    """调用京东 p.3.cn 价格接口（需 skuId 列表）"""
    if not sku_ids:
        return []
    ids_str = ",".join(str(s).replace("J_", "") for s in sku_ids[:20])
    url = f"https://p.3.cn/prices/mgets?skuIds={ids_str}"
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"Referer": "https://item.jd.com/"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = __import__("json").loads(r.read().decode())
    except Exception:
        return []
    prices = []
    for item in (data if isinstance(data, list) else []):
        if isinstance(item, dict):
            p = item.get("p") or item.get("op")
            if p is not None:
                try:
                    prices.append(float(p))
                except (TypeError, ValueError):
                    pass
    return prices


def _extract_sku_ids_from_page(page) -> list[str]:
    """从京东搜索页提取商品 sku ID（item.jd.com/123456.html）"""
    ids = []
    try:
        links = page.query_selector_all("a[href*='item.jd.com/']")
        for a in (links or []):
            href = a.get_attribute("href") or ""
            import re
            m = re.search(r"item\.jd\.com/(\d+)", href)
            if m:
                ids.append(m.group(1))
    except Exception:
        pass
    return list(dict.fromkeys(ids))[:15]  # 去重，最多15个


def _scrape_jd_prices(page, keyword: str, timeout: int = 15) -> list[float]:
    """打开京东搜索页，提取前几页商品价格"""
    url = f"https://search.jd.com/Search?keyword={keyword}&enc=utf-8"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
    except Exception:
        return []
    # 等待商品列表加载（京东多为异步渲染）
    page.wait_for_timeout(3500)
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
    except Exception:
        pass

    # 策略1：提取 sku ID，调 p.3.cn 价格接口（更稳定）
    sku_ids = _extract_sku_ids_from_page(page)
    if sku_ids:
        api_prices = _fetch_jd_price_api(sku_ids)
        if api_prices:
            return api_prices

    # 策略2：从页面 DOM 提取价格
    prices = []
    selectors = [
        "li.gl-item .p-price i",
        ".p-price i",
        ".p-price strong i",
        "[class*='price'] i",
        ".gl-price i",
        ".price i",
        "[class*='Price'] i",
    ]
    for sel in selectors:
        try:
            els = page.query_selector_all(sel)
            for el in els:
                t = el.inner_text() if el else ""
                p = _parse_price(t)
                if p and 0.01 < p < 50000:
                    prices.append(p)
            if prices:
                break
        except Exception:
            continue
    return prices


def main():
    ap = argparse.ArgumentParser(description="好特卖货盘 - 京东自主比价")
    ap.add_argument("--limit", type=int, default=15, help="比价商品数（默认15）")
    ap.add_argument("--headless", action="store_true", help="无头模式")
    ap.add_argument("--delay", type=float, default=2.0, help="每次搜索间隔秒数")
    ap.add_argument("--dry-run", action="store_true", help="仅列出待比价商品，不启动浏览器")
    args = ap.parse_args()

    if not args.dry_run:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("请先安装: pip install playwright && playwright install chromium")
            sys.exit(1)

    # 连接 DB 获取商品
    conn = None
    try:
        import pymysql
        conn = pymysql.connect(
            host="127.0.0.1", port=3306, user="root", password="62102218",
            database="htma_dashboard", charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
    except Exception as e:
        print(f"数据库连接失败: {e}")
        sys.exit(1)

    from price_compare import stage1_standardize, build_search_keyword
    items = stage1_standardize(conn, store_id="沈阳超级仓", days=30, limit=args.limit * 3)
    conn.close()

    # 优先选有具体品名+规格的，模糊匹配效果更好
    def _score(it):
        raw = (it.get("raw_name") or "")
        spec = (it.get("spec") or "")
        brand = (it.get("brand_name") or "")
        return (len(raw) >= 4) + (bool(spec)) * 2 + (bool(brand))

    items.sort(key=lambda x: (-_score(x), -(x.get("sale_amount") or 0)))
    items = items[: args.limit]

    if not items:
        print("无有效商品")
        sys.exit(0)

    print(f"【京东自主比价】共 {len(items)} 个商品（按品名+规格优先）")
    print("=" * 60)

    if args.dry_run:
        for i, it in enumerate(items, 1):
            kw = build_search_keyword(it)
            raw = (it.get("raw_name") or "")[:20]
            spec = (it.get("spec") or "")[:12]
            ht = float(it.get("unit_price") or 0)
            print(f"  {i}. {raw} {spec} | 搜索词: {kw} | 好特卖 {ht:.1f}元")
        print("（使用 --dry-run 仅预览，去掉此参数执行真实比价）")
        return

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()
        page.set_default_timeout(15000)

        for i, it in enumerate(items):
            kw = build_search_keyword(it)
            if not kw.strip():
                continue
            ht_price = float(it.get("unit_price") or 0)
            raw = (it.get("raw_name") or "")[:16]
            print(f"[{i+1}/{len(items)}] {raw} | 搜索: {kw[:28]}...")
            prices = _scrape_jd_prices(page, kw)
            time.sleep(args.delay)

            jd_min = min(prices) if prices else None
            if jd_min and ht_price > 0:
                adv = (jd_min - ht_price) / jd_min * 100
                tier = "高优势" if adv >= 20 else "中等" if adv >= 5 else "无优势" if adv >= 0 else "劣势"
                results.append({
                    "name": raw,
                    "search_kw": kw,
                    "ht_price": ht_price,
                    "jd_min": jd_min,
                    "adv": adv,
                    "tier": tier,
                })
                print(f"     好特卖 {ht_price:.1f}元 | 京东最低 {jd_min:.1f}元 | 优势 {adv:.1f}% | {tier}")
            else:
                print(f"     好特卖 {ht_price:.1f}元 | 京东未找到")
                results.append({"name": raw, "search_kw": kw, "ht_price": ht_price, "jd_min": None, "adv": None, "tier": "独家"})

        browser.close()

    print("=" * 60)
    high = [r for r in results if r.get("tier") == "高优势"]
    if high:
        print(f"高优势款 {len(high)} 个: {', '.join(r['name'][:8] for r in high[:5])}")
    print("完成")


if __name__ == "__main__":
    main()
