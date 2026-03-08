#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整导入：销售日报、销售汇总、库存（实时库存/库存查询），并自动生成品类表、刷新毛利表、同步商品表与品类毛利表"""
import os
import sys

DOWNLOADS = os.path.expanduser("~/Downloads")
if not os.path.isdir(DOWNLOADS):
    DOWNLOADS = "/Users/apple/Downloads"

STORE_ID = "沈阳超级仓"


def find_excel_files():
    """查找销售日报、销售汇总、实时库存或库存查询（取最新，排除临时文件 .~）"""
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
        elif ("实时库存" in f or "库存查询" in f) and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "stock" not in files or os.path.getmtime(path) > os.path.getmtime(files["stock"]):
                files["stock"] = path
    return files


def main():
    print("=== 好特卖完整导入（下载目录）===", flush=True)
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_root, ".env"))
    except ImportError:
        pass
    sys.path.insert(0, _root)
    from htma_dashboard.db_config import get_conn
    from htma_dashboard.import_logic import (
        import_sale_daily,
        import_sale_summary,
        import_stock,
        refresh_profit,
        refresh_category_from_sale,
        sync_products_table,
        sync_category_table,
    )

    conn = get_conn()

    files = find_excel_files()
    if not files:
        print("下载目录未找到销售日报/销售汇总/库存 Excel，退出。", flush=True)
        conn.close()
        sys.exit(1)
    print("找到文件:", {k: os.path.basename(v) for k, v in files.items()}, flush=True)

    cur = conn.cursor()
    has_sale_daily = "sale_daily" in files
    has_sale_summary = "sale_summary" in files
    # 与 Web 一致：同时有销售日报+销售汇总时才清空销售/毛利，避免分步上传误清空
    if has_sale_daily and has_sale_summary:
        cur.execute("TRUNCATE TABLE t_htma_sale")
        cur.execute("TRUNCATE TABLE t_htma_profit")
        conn.commit()
    if "stock" in files:
        cur.execute("TRUNCATE TABLE t_htma_stock")
        conn.commit()

    sale_daily_cnt = sale_summary_cnt = stock_cnt = 0
    if has_sale_daily:
        sale_daily_cnt, diag = import_sale_daily(files["sale_daily"], conn)
        print(f"销售日报: {sale_daily_cnt} 条", diag or "", flush=True)
    if has_sale_summary:
        # 与日报同传时：同(日期,货号)覆盖不累加，避免销售额翻倍
        sale_summary_cnt, diag = import_sale_summary(
            files["sale_summary"], conn, overwrite_on_duplicate=has_sale_daily
        )
        print(f"销售汇总: {sale_summary_cnt} 条", diag or "", flush=True)
    if "stock" in files:
        stock_cnt, stock_diag = import_stock(files["stock"], conn)
        print(f"库存: {stock_cnt} 条", stock_diag or "", flush=True)

    if sale_daily_cnt > 0 or sale_summary_cnt > 0:
        refresh_profit(conn)
        print("毛利表已刷新", flush=True)
        cat_cnt = refresh_category_from_sale(conn)
        print(f"品类表(从销售透视): {cat_cnt} 条", flush=True)
        try:
            products_synced = sync_products_table(conn, store_id=STORE_ID)
            print(f"商品表同步: {products_synced} 条", flush=True)
        except Exception as e:
            print(f"商品表同步失败: {e}", flush=True)
        if conn:
            try:
                cat_profit_cnt = sync_category_table(conn, store_id=STORE_ID)
                print(f"品类毛利表同步: {cat_profit_cnt} 条", flush=True)
            except Exception as e:
                print(f"品类毛利表同步失败: {e}", flush=True)

    cur.execute("SELECT COUNT(*) AS c FROM t_htma_sale")
    sale_total = cur.fetchone()["c"]
    cur.execute("SELECT COALESCE(SUM(sale_amount), 0) AS v FROM t_htma_sale")
    sale_total_amount = round(float(cur.fetchone().get("v") or 0), 2)
    cur.execute("SELECT COUNT(*) AS c FROM t_htma_stock")
    stock_total = cur.fetchone()["c"]
    cur.execute("""
        SELECT COALESCE(SUM(stock_amount), 0) AS v FROM t_htma_stock
        WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
    """, (STORE_ID, STORE_ID))
    stock_total_amount = round(float(cur.fetchone().get("v") or 0), 2)
    cur.execute("SELECT COUNT(*) AS c FROM t_htma_profit")
    profit_total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM t_htma_category")
    cat_total = cur.fetchone()["c"]
    cur.execute("SELECT MIN(data_date) AS min_d, MAX(data_date) AS max_d FROM t_htma_sale")
    dr = cur.fetchone()
    date_range = f"{dr['min_d']} ~ {dr['max_d']}" if dr and dr["min_d"] else "-"

    print("\n=== 导入完成（数据已写入当前 MySQL）===", flush=True)
    print(f"销售表: {sale_total} 条，销售金额合计: {sale_total_amount:,.2f}", flush=True)
    print(f"库存表: {stock_total} 条，库存金额合计: {stock_total_amount:,.2f}", flush=True)
    print(f"毛利表: {profit_total} 条", flush=True)
    print(f"品类表: {cat_total} 条", flush=True)
    print(f"日期范围: {date_range}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
