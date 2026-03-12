#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量比价：从商品档案+销售表取大额/高销商品，调用百度优选 Skill 比价并写入 t_price_compare。
依赖：1) 已执行 scripts/23_create_t_price_compare.sql  2) clawhub install baidu-ecommerce-skill
"""
import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from htma_dashboard.db_config import get_conn
from htma_dashboard.baidu_skill_compare import call_baidu_skill

STORE_ID = os.environ.get("HTMA_STORE_ID", "沈阳超级仓")


def get_target_products(conn, top_n=50, min_price=5000):
    """
    获取待比价商品：优先单价>=min_price 的大额商品，按最高单价降序，取 top_n 条。
    使用 t_htma_product_master + t_htma_sale 近 30 天聚合。
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            p.sku_code,
            p.product_name,
            p.brand_name AS brand,
            MAX(s.unit_price) AS max_price
        FROM t_htma_product_master p
        INNER JOIN (
            SELECT sku_code,
                   SUM(sale_amount) / NULLIF(SUM(sale_qty), 0) AS unit_price
            FROM t_htma_sale
            WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY sku_code
        ) s ON p.sku_code = s.sku_code AND p.store_id = %s
        WHERE s.unit_price >= %s
        GROUP BY p.sku_code, p.product_name, p.brand_name
        ORDER BY max_price DESC
        LIMIT %s
        """,
        (STORE_ID, STORE_ID, min_price, top_n),
    )
    rows = cur.fetchall()
    cur.close()
    return [{"sku_code": r["sku_code"], "product_name": r["product_name"] or "", "brand": r["brand"] or "", "max_price": float(r["max_price"]) if r.get("max_price") is not None else None} for r in rows]


def save_price_result(conn, sku_code, product_name, brand, platform_data):
    """将 Skill 返回的 platform_data 写入 t_price_compare（每平台一行）。"""
    if not platform_data or not isinstance(platform_data, dict):
        return
    cur = conn.cursor()
    capture = datetime.now()
    for platform, info in platform_data.items():
        if not isinstance(info, dict):
            continue
        price = info.get("price")
        if price is None:
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        original_price = info.get("original_price")
        if original_price is not None:
            try:
                original_price = float(original_price)
            except (TypeError, ValueError):
                original_price = None
        promotion = info.get("promotion") or info.get("促销") or ""
        if isinstance(promotion, dict):
            promotion = json.dumps(promotion, ensure_ascii=False)[:500]
        else:
            promotion = str(promotion)[:500]
        good_rate = info.get("好评率") or info.get("good_rate")
        if good_rate is not None:
            try:
                good_rate = float(good_rate)
            except (TypeError, ValueError):
                good_rate = None
        cur.execute(
            """
            INSERT INTO t_price_compare
            (sku_code, product_name, brand, platform, price, original_price, promotion_info, good_rate, capture_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (sku_code, product_name or "", brand or "", platform, price, original_price, promotion, good_rate, capture),
        )
    conn.commit()
    cur.close()


def main():
    top_n = int(os.environ.get("PRICE_COMPARE_TOP_N", "50"))
    min_price = float(os.environ.get("PRICE_COMPARE_MIN_PRICE", "5000"))
    delay = float(os.environ.get("PRICE_COMPARE_DELAY", "1"))

    conn = get_conn()
    try:
        products = get_target_products(conn, top_n=top_n, min_price=min_price)
        if not products:
            print("没有符合条件的大额商品（近30天销售单价>=%s）" % min_price)
            return
        print("待比价 %s 个商品（单价>=%s 元）" % (len(products), min_price))
        for item in products:
            print("  比价: %s (最高单价: %s)" % (item["product_name"] or item["sku_code"], item.get("max_price")))
            result = call_baidu_skill(
                item["product_name"],
                brand=item.get("brand") or None,
                max_price=item.get("max_price"),
            )
            if result.get("status") == "success" and result.get("data"):
                save_price_result(
                    conn,
                    item["sku_code"],
                    item.get("product_name") or "",
                    item.get("brand") or "",
                    result["data"],
                )
            if delay > 0:
                import time
                time.sleep(delay)
        print("批量比价完成")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
