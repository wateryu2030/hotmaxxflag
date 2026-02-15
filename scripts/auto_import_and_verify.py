#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动导入下载目录下的 3 个 Excel，验证统计是否与附表一致"""
import os
import sys

DOWNLOADS = os.path.expanduser("~/Downloads")
if not os.path.isdir(DOWNLOADS):
    DOWNLOADS = "/Users/apple/Downloads"
# 期望值（附表 本期数据）
EXPECTED = {
    "sales_amount": 4145000.00,      # 销售额
    "total_profit": 1615278.46,      # 总毛利
    "profit_rate_pct": 38.97,        # 平均毛利率 %
    "sales_qty": 212190,             # 销售数量
    "return_amount": 19500.00,       # 退货金额
    "return_qty": 975,               # 退货数量
    "actual_sales": 4125500.00,      # 实际销售金额
    "sales_cost": 2529721.54,        # 销售成本
}

def find_excel_files():
    """在 Downloads 下查找销售日报、销售汇总、实时库存（取最新，排除临时文件 .~）"""
    if not os.path.isdir(DOWNLOADS):
        return {}
    files = {}
    for f in os.listdir(DOWNLOADS):
        if f.startswith(".") or f.startswith("~"):
            continue
        path = os.path.join(DOWNLOADS, f)
        if not os.path.isfile(path):
            continue
        low = f.lower()
        if "销售日报" in f and "品项" not in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "sale_daily" not in files or os.path.getmtime(path) > os.path.getmtime(files["sale_daily"]):
                files["sale_daily"] = path
        elif "销售汇总" in f and "品项" not in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "sale_summary" not in files or os.path.getmtime(path) > os.path.getmtime(files["sale_summary"]):
                files["sale_summary"] = path
        elif "实时库存" in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "stock" not in files or os.path.getmtime(path) > os.path.getmtime(files["stock"]):
                files["stock"] = path
    return files

def main():
    print("=== 好特卖自动导入验证 ===", flush=True)
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "htma_dashboard"))
    import pymysql
    from import_logic import import_sale_daily, import_sale_summary, import_stock, refresh_profit, refresh_category_from_sale

    conn = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "62102218"),
        database="htma_dashboard",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )

    files = find_excel_files()
    print("找到文件:", files)

    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE t_htma_sale")
    cur.execute("TRUNCATE TABLE t_htma_profit")
    cur.execute("TRUNCATE TABLE t_htma_stock")
    conn.commit()

    sale_daily_cnt = sale_summary_cnt = stock_cnt = 0
    # 销售汇总覆盖销售日报中重叠的(date,sku)，优先导入销售日报再导入销售汇总
    if "sale_daily" in files:
        sale_daily_cnt, diag = import_sale_daily(files["sale_daily"], conn)
        print(f"销售日报: {sale_daily_cnt} 条", diag or "")
    if "sale_summary" in files:
        sale_summary_cnt, diag = import_sale_summary(files["sale_summary"], conn)
        print(f"销售汇总: {sale_summary_cnt} 条", diag or "")
    if "stock" in files:
        stock_cnt = import_stock(files["stock"], conn)
        print(f"实时库存: {stock_cnt} 条")

    if sale_daily_cnt > 0 or sale_summary_cnt > 0:
        refresh_profit(conn)
        refresh_category_from_sale(conn)

    # 查询统计（本期=2026年1月，与附表一致）
    period_start, period_end = "2026-01-01", "2026-01-31"
    try:
        cur.execute("""
            SELECT
                COALESCE(SUM(sale_amount), 0) AS total_sale,
                COALESCE(SUM(sale_cost), 0) AS total_cost,
                COALESCE(SUM(gross_profit), 0) AS total_profit,
                COALESCE(SUM(sale_qty), 0) AS total_qty,
                COALESCE(SUM(return_amount), 0) AS return_amount,
                COALESCE(SUM(return_qty), 0) AS return_qty
            FROM t_htma_sale
            WHERE data_date BETWEEN %s AND %s
        """, (period_start, period_end))
    except Exception:
        cur.execute("""
            SELECT
                COALESCE(SUM(sale_amount), 0) AS total_sale,
                COALESCE(SUM(sale_cost), 0) AS total_cost,
                COALESCE(SUM(gross_profit), 0) AS total_profit,
                COALESCE(SUM(sale_qty), 0) AS total_qty,
                0 AS return_amount,
                0 AS return_qty
            FROM t_htma_sale
            WHERE data_date BETWEEN %s AND %s
        """, (period_start, period_end))
    row = cur.fetchone()
    conn.close()

    actual = {
        "sales_amount": float(row["total_sale"] or 0),
        "sales_cost": float(row["total_cost"] or 0),
        "total_profit": float(row["total_profit"] or 0),
        "sales_qty": float(row["total_qty"] or 0),
        "return_amount": float(row["return_amount"] or 0),
        "return_qty": float(row["return_qty"] or 0),
    }
    actual["profit_rate_pct"] = (actual["total_profit"] / actual["sales_amount"] * 100) if actual["sales_amount"] > 0 else 0
    actual["actual_sales"] = actual["sales_amount"] - actual["return_amount"]

    print(f"\n=== 统计对比（本期: {period_start} ~ {period_end}）===")
    print(f"{'指标':<20} {'期望值':>18} {'实际值':>18} {'差异':>12} {'状态'}")
    print("-" * 80)

    for k, exp in EXPECTED.items():
        act = actual.get(k, 0)
        diff = act - exp
        if abs(diff) < 1:
            status = "✓"
        elif abs(diff) < exp * 0.01:
            status = "~"
        else:
            status = "✗"
        print(f"{k:<20} {exp:>18,.2f} {act:>18,.2f} {diff:>+12,.2f} {status}")

    print("\n结论:")
    ok = ["sales_amount", "total_profit", "profit_rate_pct", "sales_cost"]
    mismatches = [k for k in ok if k in EXPECTED and abs(actual.get(k, 0) - EXPECTED[k]) > max(100, EXPECTED[k] * 0.05)]
    if mismatches:
        print("  - 差异项:", mismatches, "(允许5%误差)")
    else:
        print("  - 核心统计(销售额/毛利/毛利率/成本)与附表一致")
