#!/usr/bin/env python3
"""
数据口径一致性校验：确保 KPI、趋势图、周几对比 均来自 t_htma_sale，且同一周期下总额一致。
可用于导入后验证或 OpenClaw 自动化检测。
用法: .venv/bin/python scripts/verify_sale_consistency.py [start_date] [end_date]
默认: 2026-03-07 2026-03-08
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    start = (sys.argv[1] if len(sys.argv) > 1 else "2026-03-07").strip()
    end = (sys.argv[2] if len(sys.argv) > 2 else "2026-03-08").strip()

    from htma_dashboard.db_config import get_conn
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(sale_amount), 0) AS total_sale,
               COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS total_profit
        FROM t_htma_sale
        WHERE store_id = %s AND data_date BETWEEN %s AND %s
    """, (os.environ.get("STORE_ID", "沈阳超级仓"), start, end))
    row = cur.fetchone()
    db_total_sale = float(row["total_sale"] or 0)
    db_total_profit = float(row["total_profit"] or 0)
    cur.execute("""
        SELECT data_date, COALESCE(SUM(sale_amount), 0) AS day_sale
        FROM t_htma_sale
        WHERE store_id = %s AND data_date BETWEEN %s AND %s
        GROUP BY data_date ORDER BY data_date
    """, (os.environ.get("STORE_ID", "沈阳超级仓"), start, end))
    daily_rows = cur.fetchall()
    sum_by_day = sum(float(r["day_sale"] or 0) for r in daily_rows)
    cur.execute("""
        SELECT DAYOFWEEK(data_date) AS dow, COALESCE(SUM(sale_amount), 0) AS dow_sale
        FROM t_htma_sale
        WHERE store_id = %s AND data_date BETWEEN %s AND %s
        GROUP BY DAYOFWEEK(data_date)
    """, (os.environ.get("STORE_ID", "沈阳超级仓"), start, end))
    dow_rows = cur.fetchall()
    sum_by_dow = sum(float(r["dow_sale"] or 0) for r in dow_rows)
    cur.close()
    conn.close()

    ok = True
    print(f"周期: {start} ~ {end}")
    print(f"  t_htma_sale 汇总销售额: {db_total_sale:.2f}")
    print(f"  按日汇总再相加:          {sum_by_day:.2f}")
    print(f"  按周几汇总再相加:       {sum_by_dow:.2f}")
    if abs(db_total_sale - sum_by_day) > 0.01:
        print("  [FAIL] 按日汇总与总和不一致")
        ok = False
    else:
        print("  [OK] 按日汇总与总和一致")
    if abs(db_total_sale - sum_by_dow) > 0.01:
        print("  [FAIL] 按周几汇总与总和不一致")
        ok = False
    else:
        print("  [OK] 按周几汇总与总和一致")
    print(f"  t_htma_sale 汇总毛利:   {db_total_profit:.2f}")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
