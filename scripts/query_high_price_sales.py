#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询：销售单价超过5000元的记录、以及是否含大额羽绒服"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from htma_dashboard.db_config import get_conn

def main():
    conn = get_conn()
    try:
        cur = conn.cursor()
        # 1) 销售表中是否有“羽绒服”且单价>5000的记录（单价用 销售额/数量 或 sale_price）
        cur.execute("""
            SELECT COLUMN_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_htma_sale'
            AND COLUMN_NAME IN ('product_name','sale_price','avg_sale_price')
        """)
        cols = {r["COLUMN_NAME"] for r in cur.fetchall()}
        has_product_name = "product_name" in cols
        has_sale_price = "sale_price" in cols

        # 2) 单价>5000的销售记录：优先用 sale_price，否则用 sale_amount/sale_qty
        if has_sale_price:
            price_expr = "COALESCE(sale_price, sale_amount/NULLIF(sale_qty,0))"
        else:
            price_expr = "sale_amount/NULLIF(sale_qty,0)"
        sel_cols = "data_date, sku_code, category, sale_qty, sale_amount, sale_cost, (%s) AS unit_price" % price_expr
        if has_product_name:
            sel_cols = "data_date, sku_code, category, product_name, sale_qty, sale_amount, sale_cost, (%s) AS unit_price" % price_expr
        cur.execute("""
            SELECT %s
            FROM t_htma_sale
            WHERE sale_qty > 0 AND (%s) > 5000
            ORDER BY unit_price DESC
            LIMIT 100
        """ % (sel_cols, price_expr))
        rows = cur.fetchall()
        print("=" * 80)
        print("【销售单价 > 5000 元的记录】（前100条，按单价降序）")
        print("=" * 80)
        if not rows:
            print("无。")
        else:
            for r in rows:
                pn = (r.get("product_name") or "-") if has_product_name else "-"
                print(f"  日期: {r.get('data_date')} | SKU: {r.get('sku_code')} | 品类: {r.get('category') or '-'} | 品名: {pn}")
                print(f"    数量: {r.get('sale_qty')} | 销售额: {r.get('sale_amount')} | 单价: {r.get('unit_price')}")

        # 3) 去重：销售单价>5000的品有哪些（SKU/品名/品类）
        agg_pn = "MAX(product_name) AS product_name," if has_product_name else ""
        cur.execute("""
            SELECT sku_code,
                   %s
                   MAX(category) AS category,
                   MAX(%s) AS max_unit_price,
                   SUM(sale_qty) AS total_qty,
                   SUM(sale_amount) AS total_amount
            FROM t_htma_sale
            WHERE sale_qty > 0 AND (%s) > 5000
            GROUP BY sku_code
            ORDER BY max_unit_price DESC
        """ % (agg_pn, price_expr, price_expr))
        products = cur.fetchall()
        print()
        print("=" * 80)
        print("【销售单价超过 5000 元的品（按最高单价降序）】")
        print("=" * 80)
        if not products:
            print("无。")
        else:
            for p in products:
                pn = (p.get("product_name") or "-") if has_product_name else "-"
                print(f"  SKU: {p.get('sku_code')} | 品名: {pn} | 品类: {p.get('category') or '-'} | 最高单价: {p.get('max_unit_price')} | 总销量: {p.get('total_qty')} | 总销售额: {p.get('total_amount')}")

        # 4) 是否含“羽绒服”且单价>5000
        if has_product_name:
            cur.execute(f"""
                SELECT data_date, sku_code, product_name, category, sale_qty, sale_amount, ({price_expr}) AS unit_price
                FROM t_htma_sale
                WHERE (product_name LIKE %s OR category LIKE %s) AND sale_qty > 0 AND ({price_expr}) > 5000
                ORDER BY unit_price DESC
                LIMIT 50
            """, ("%羽绒服%", "%羽绒服%"))
            down = cur.fetchall()
            print()
            print("=" * 80)
            print("【大额羽绒服：品名/品类含“羽绒服”且销售单价 > 5000 元】")
            print("=" * 80)
            if not down:
                print("无此类销售记录。")
            else:
                for r in down:
                    print(f"  日期: {r.get('data_date')} | SKU: {r.get('sku_code')} | 品名: {r.get('product_name')} | 品类: {r.get('category')} | 数量: {r.get('sale_qty')} | 销售额: {r.get('sale_amount')} | 单价: {r.get('unit_price')}")
        cur.close()
    finally:
        conn.close()

if __name__ == "__main__":
    main()
