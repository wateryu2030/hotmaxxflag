#!/usr/bin/env python3
"""手工统计 3 月 7 日销售收入，并验证是否重复。在项目根目录执行：.venv/bin/python scripts/verify_sale_20260307.py"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from htma_dashboard.db_config import get_conn

def main():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
          COUNT(*) AS row_count,
          COUNT(DISTINCT sku_code) AS distinct_sku,
          ROUND(COALESCE(SUM(sale_amount), 0), 2) AS total_sale_amount,
          ROUND(COALESCE(SUM(sale_qty), 0), 2) AS total_sale_qty,
          ROUND(COALESCE(SUM(sale_cost), 0), 2) AS total_sale_cost,
          ROUND(COALESCE(SUM(gross_profit), 0), 2) AS total_gross_profit
        FROM t_htma_sale WHERE data_date = '2026-03-07'
    """)
    row = cur.fetchone()
    print("=" * 50)
    print("2026-03-07 销售收入手工统计（当前库）")
    print("=" * 50)
    print("行数（SKU 条数）:", row["row_count"])
    print("去重货号数:", row["distinct_sku"])
    print("销售收入（元）:", row["total_sale_amount"])
    print("销售数量:", row["total_sale_qty"])
    print("销售成本（元）:", row["total_sale_cost"])
    print("毛利（元）:", row["total_gross_profit"])
    print()

    cur.execute("""
        SELECT data_date, sku_code, COUNT(*) AS cnt
        FROM t_htma_sale WHERE data_date = '2026-03-07'
        GROUP BY data_date, sku_code HAVING COUNT(*) > 1
    """)
    dup = cur.fetchall()
    print("重复验证：同(日期,货号)出现多于 1 行的组数 =", len(dup), "（0 表示无重复行）")
    print()

    cur.execute("""
        SELECT data_date,
          ROUND(COALESCE(SUM(sale_amount), 0), 2) AS total_amt,
          COUNT(*) AS row_cnt
        FROM t_htma_sale
        WHERE data_date BETWEEN '2026-03-05' AND '2026-03-10'
        GROUP BY data_date ORDER BY data_date
    """)
    daily = cur.fetchall()
    print("3/5～3/10 每日销售额对比（判断 3/7 是否异常高）")
    print("-" * 50)
    for r in daily:
        mark = "  <-- 若约为相邻日 2 倍则可能重复" if str(r["data_date"]) == "2026-03-07" else ""
        print(r["data_date"], "  销售额:", r["total_amt"], "  行数:", r["row_cnt"], mark)
    print()
    print("结论：若您有 3 月 7 日销售日报/汇总表的手工合计，与上面「销售收入」对比；")
    print("若当前值约为正确值的 2 倍，可执行 scripts/fix_sale_20260307_double.sql 做除以 2 修正。")
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
