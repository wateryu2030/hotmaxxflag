#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整导入：销售日报、销售汇总、实时库存，并自动生成品类表、刷新毛利表"""
import os
import sys

DOWNLOADS = os.path.expanduser("~/Downloads")
if not os.path.isdir(DOWNLOADS):
    DOWNLOADS = "/Users/apple/Downloads"


def find_excel_files():
    """查找销售日报、销售汇总_默认、实时库存（优先带_默认的，取最新）"""
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
    print("=== 好特卖完整导入 ===", flush=True)
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
    print("找到文件:", {k: os.path.basename(v) for k, v in files.items()}, flush=True)

    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE t_htma_sale")
    cur.execute("TRUNCATE TABLE t_htma_profit")
    cur.execute("TRUNCATE TABLE t_htma_stock")
    conn.commit()

    sale_daily_cnt = sale_summary_cnt = stock_cnt = 0
    if "sale_daily" in files:
        sale_daily_cnt, diag = import_sale_daily(files["sale_daily"], conn)
        print(f"销售日报: {sale_daily_cnt} 条", diag or "", flush=True)
    # 销售汇总与销售日报重叠(date,sku)会重复累加，仅以销售日报为销售数据源
    # if "sale_summary" in files:
    #     sale_summary_cnt, diag = import_sale_summary(files["sale_summary"], conn)
    #     print(f"销售汇总: {sale_summary_cnt} 条", diag or "", flush=True)
    if "stock" in files:
        stock_cnt = import_stock(files["stock"], conn)
        print(f"实时库存: {stock_cnt} 条", flush=True)

    if sale_daily_cnt > 0 or sale_summary_cnt > 0:
        refresh_profit(conn)
        print("毛利表已刷新", flush=True)
        cat_cnt = refresh_category_from_sale(conn)
        print(f"品类表已从销售透视: {cat_cnt} 条", flush=True)

    cur.execute("SELECT COUNT(*) AS c FROM t_htma_sale")
    sale_total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM t_htma_stock")
    stock_total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM t_htma_profit")
    profit_total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM t_htma_category")
    cat_total = cur.fetchone()["c"]
    cur.execute("SELECT MIN(data_date) AS min_d, MAX(data_date) AS max_d FROM t_htma_sale")
    dr = cur.fetchone()
    date_range = f"{dr['min_d']} ~ {dr['max_d']}" if dr and dr["min_d"] else "-"

    print("\n=== 导入完成 ===", flush=True)
    print(f"销售表: {sale_total} 条", flush=True)
    print(f"库存表: {stock_total} 条", flush=True)
    print(f"毛利表: {profit_total} 条", flush=True)
    print(f"品类表: {cat_total} 条", flush=True)
    print(f"日期范围: {date_range}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
