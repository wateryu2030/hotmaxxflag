#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查询并删除数据库中「合计/总计/小计」等汇总行（导出的统计结果，非明细，会导致重复计算）。
用法: python3 scripts/delete_summary_rows.py [--dry-run]
"""
import os
import sys

# 与看板一致的汇总标识（货号/品类/品名含这些视为汇总行，需删除）
SUMMARY_KEYWORDS = ("合计", "总计", "小计", "汇总", "求和项", "合计行", "总计行", "小计行")


def get_conn():
    import pymysql
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "62102218"),
        database="htma_dashboard",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def main():
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    if dry_run:
        print("【仅查询，不删除】--dry-run", flush=True)

    conn = get_conn()
    cur = conn.cursor()
    # 条件：任一列 含任一汇总词（合计/总计/小计/汇总/求和项 等）
    kw_params = [f"%{k}%" for k in SUMMARY_KEYWORDS]
    sale_where = " OR ".join(
        [f"sku_code LIKE %s"] * len(SUMMARY_KEYWORDS) +
        [f"category LIKE %s"] * len(SUMMARY_KEYWORDS) +
        [f"product_name LIKE %s"] * len(SUMMARY_KEYWORDS)
    )
    sale_params = kw_params * 3

    # 1) 销售表：货号/品类/品名 含汇总词
    cur.execute(
        f"SELECT COUNT(*) AS c FROM t_htma_sale WHERE {sale_where}",
        sale_params,
    )
    sale_count = cur.fetchone()["c"]
    cur.execute(
        f"SELECT data_date, sku_code, category, product_name, sale_amount FROM t_htma_sale WHERE {sale_where} LIMIT 20",
        sale_params,
    )
    sale_rows = cur.fetchall()
    print(f"销售表 t_htma_sale: 命中 {sale_count} 条（货号/品类/品名含 合计|总计|小计|汇总|求和项 等）", flush=True)
    if sale_rows:
        for r in sale_rows[:10]:
            print(f"  样本: date={r['data_date']} sku={r['sku_code']!r} cat={r['category']!r} product={r['product_name']!r} amount={r['sale_amount']}", flush=True)

    # 2) 库存表
    stock_where = " OR ".join(
        [f"sku_code LIKE %s"] * len(SUMMARY_KEYWORDS) +
        [f"category LIKE %s"] * len(SUMMARY_KEYWORDS) +
        [f"product_name LIKE %s"] * len(SUMMARY_KEYWORDS)
    )
    cur.execute(
        f"SELECT COUNT(*) AS c FROM t_htma_stock WHERE {stock_where}",
        sale_params,
    )
    stock_count = cur.fetchone()["c"]
    cur.execute(
        f"SELECT data_date, sku_code, category, product_name, stock_qty, stock_amount FROM t_htma_stock WHERE {stock_where} LIMIT 20",
        sale_params,
    )
    stock_rows = cur.fetchall()
    print(f"库存表 t_htma_stock: 命中 {stock_count} 条", flush=True)
    if stock_rows:
        for r in stock_rows[:10]:
            print(f"  样本: date={r['data_date']} sku={r['sku_code']!r} cat={r['category']!r} product={r['product_name']!r}", flush=True)

    # 3) 毛利表：品类/大类 含汇总词
    profit_where = " OR ".join(
        [f"category LIKE %s"] * len(SUMMARY_KEYWORDS) +
        [f"category_large LIKE %s"] * len(SUMMARY_KEYWORDS)
    )
    profit_params = kw_params * 2
    cur.execute(
        f"SELECT COUNT(*) AS c FROM t_htma_profit WHERE {profit_where}",
        profit_params,
    )
    profit_count = cur.fetchone()["c"]
    for k in SUMMARY_KEYWORDS:
        cur.execute(
            "SELECT COUNT(*) AS c FROM t_htma_profit WHERE category LIKE %s OR category_large LIKE %s",
            (f"%{k}%", f"%{k}%"),
        )
        n = cur.fetchone()["c"]
        if n:
            print(f"  毛利表 含「{k}」: {n} 条", flush=True)
    cur.execute(
        f"SELECT data_date, category, category_large, total_sale, total_profit FROM t_htma_profit WHERE {profit_where} LIMIT 10",
        profit_params,
    )
    profit_rows = cur.fetchall()
    print(f"毛利表 t_htma_profit: 命中 {profit_count} 条（品类/大类含汇总词）", flush=True)
    if profit_rows:
        for r in profit_rows[:5]:
            print(f"  样本: date={r['data_date']} category={r['category']!r} large={r['category_large']!r} sale={r['total_sale']}", flush=True)

    if dry_run:
        print("dry-run 结束，未执行删除。", flush=True)
        conn.close()
        return

    deleted_sale, deleted_stock, deleted_profit = 0, 0, 0
    if sale_count > 0:
        cur.execute(f"DELETE FROM t_htma_sale WHERE {sale_where}", sale_params)
        deleted_sale = cur.rowcount
        print(f"已删除 销售表 {deleted_sale} 条", flush=True)
    if stock_count > 0:
        cur.execute(f"DELETE FROM t_htma_stock WHERE {stock_where}", sale_params)
        deleted_stock = cur.rowcount
        print(f"已删除 库存表 {deleted_stock} 条", flush=True)
    if profit_count > 0:
        cur.execute(f"DELETE FROM t_htma_profit WHERE {profit_where}", profit_params)
        deleted_profit = cur.rowcount
        print(f"已删除 毛利表 {deleted_profit} 条", flush=True)

    conn.commit()

    # 若删除了销售表数据，按日期+品类汇总的毛利表应重新从销售表生成
    if deleted_sale > 0:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "htma_dashboard"))
        from import_logic import refresh_profit
        refresh_profit(conn)
        conn.commit()
        print("已根据销售表重新刷新毛利表。", flush=True)

    conn.close()
    print("完成。", flush=True)


if __name__ == "__main__":
    main()
