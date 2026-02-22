#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建商品表、品类表，并验证导出功能"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "htma_dashboard"))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

def main():
    import pymysql
    from app import DB_CONFIG, get_conn, STORE_ID

    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor()

    # 1. 创建商品表
    with open(os.path.join(os.path.dirname(__file__), "10_create_products_table.sql")) as f:
        content = f.read()
    for stmt in content.split(";"):
        s = stmt.strip()
        if s and "USE htma_dashboard" not in s:
            try:
                cur.execute(s)
                print("OK: 执行 10_create_products_table.sql 片段")
            except Exception as e:
                print("WARN:", e)
    conn.commit()

    # 2. 创建品类表
    with open(os.path.join(os.path.dirname(__file__), "11_create_category_profit_summary.sql")) as f:
        content = f.read()
    for stmt in content.split(";"):
        s = stmt.strip()
        if s and "USE htma_dashboard" not in s:
            try:
                cur.execute(s)
                print("OK: 执行 11_create_category_profit_summary.sql 片段")
            except Exception as e:
                print("WARN:", e)
    conn.commit()

    # 3. 刷新商品表、品类表
    from import_logic import refresh_products_from_sale_stock, refresh_category_profit_summary
    n1 = refresh_products_from_sale_stock(conn)
    n2 = refresh_category_profit_summary(conn)
    print(f"OK: 商品表刷新 {n1} 条, 品类表刷新 {n2} 条")

    # 4. 验证
    cur.execute("SELECT COUNT(*) AS c FROM t_htma_products WHERE store_id = %s", (STORE_ID,))
    pc = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM t_htma_category_profit WHERE store_id = %s", (STORE_ID,))
    cc = cur.fetchone()["c"]
    print(f"验证: 商品表 {pc} 条, 品类表 {cc} 条")
    conn.close()
    print("完成。请访问 http://127.0.0.1:5002 测试「导出商品」「导出品类」。")

if __name__ == "__main__":
    main()
