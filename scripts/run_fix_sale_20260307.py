#!/usr/bin/env python3
# 使用项目 DB 配置执行 3 月 7 日销售数据去重修正（需在项目根目录执行且已安装 pymysql）
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from htma_dashboard.db_config import get_conn

def main():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT SUM(sale_amount) AS amt, SUM(sale_qty) AS qty, COUNT(*) AS cnt FROM t_htma_sale WHERE data_date = '2026-03-07'"
    )
    before = cur.fetchone()
    print("执行前 2026-03-07:", before)
    cur.execute("""
        UPDATE t_htma_sale
        SET sale_qty = sale_qty / 2, sale_amount = sale_amount / 2,
            sale_cost = sale_cost / 2, gross_profit = gross_profit / 2
        WHERE data_date = '2026-03-07'
    """)
    updated = cur.rowcount
    conn.commit()
    cur.execute(
        "SELECT SUM(sale_amount) AS amt, SUM(sale_qty) AS qty, COUNT(*) AS cnt FROM t_htma_sale WHERE data_date = '2026-03-07'"
    )
    after = cur.fetchone()
    print("影响行数:", updated)
    print("执行后 2026-03-07:", after)
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
