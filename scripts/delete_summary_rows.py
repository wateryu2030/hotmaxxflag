#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查询并删除数据库中「合计/总计/小计」等汇总行（导出的统计结果，非明细，会导致重复计算）。
用法: python3 scripts/delete_summary_rows.py [--dry-run]
数据库配置从项目根目录 .env 的 MYSQL_* 读取。
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except ImportError:
    pass
sys.path.insert(0, _ROOT)
from htma_dashboard.db_config import get_conn

# 与看板 import_logic 一致的汇总标识（货号/品类/品名含这些视为汇总行，需删除）
SUMMARY_KEYWORDS = ("合计", "总计", "小计", "汇总", "求和项", "合计行", "总计行", "小计行")
# 货号为这些字面量或为空：视为「无商品、仅合计」行，必须删除
SUMMARY_SKU_EXACT = ("货号", "总计", "合计", "小计", "汇总", "求和项", "合计行", "总计行", "小计行")


def _sale_where_with_product_name():
    kw_params = [f"%{k}%" for k in SUMMARY_KEYWORDS]
    conds = (
        [f"sku_code LIKE %s"] * len(SUMMARY_KEYWORDS) +
        [f"category LIKE %s"] * len(SUMMARY_KEYWORDS) +
        [f"product_name LIKE %s"] * len(SUMMARY_KEYWORDS)
    )
    return " OR ".join(conds), kw_params * 3


def _sale_where_no_product_name():
    kw_params = [f"%{k}%" for k in SUMMARY_KEYWORDS]
    conds = (
        [f"sku_code LIKE %s"] * len(SUMMARY_KEYWORDS) +
        [f"category LIKE %s"] * len(SUMMARY_KEYWORDS)
    )
    return " OR ".join(conds), kw_params * 2


def main():
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    if dry_run:
        print("【仅查询，不删除】--dry-run", flush=True)

    conn = get_conn()
    cur = conn.cursor()

    # 是否含 product_name 列（部分环境可能未执行 03_add_full_columns）
    has_product_name = False
    try:
        cur.execute("SELECT product_name FROM t_htma_sale LIMIT 1")
        has_product_name = True
    except Exception:
        pass

    # 条件1：货号为空或为表头/汇总字面量（无商品、仅合计）
    sale_where_base = " (TRIM(COALESCE(sku_code,'')) = '' OR sku_code IN (%s)) " % ",".join(["%s"] * len(SUMMARY_SKU_EXACT))
    sale_params_base = list(SUMMARY_SKU_EXACT)
    # 条件2：货号/品类/品名 含汇总词
    if has_product_name:
        sale_where_like, sale_params_like = _sale_where_with_product_name()
    else:
        sale_where_like, sale_params_like = _sale_where_no_product_name()
    sale_where = "(" + sale_where_base + ") OR (" + sale_where_like + ")"
    sale_params = sale_params_base + sale_params_like

    # 1) 销售表：货号为空/表头/汇总字面量，或 货号/品类/品名 含汇总词
    cur.execute(
        f"SELECT COUNT(*) AS c FROM t_htma_sale WHERE {sale_where}",
        sale_params,
    )
    sale_count = cur.fetchone()["c"]
    sel_cols = "data_date, sku_code, category, sale_amount" + (", product_name" if has_product_name else "")
    cur.execute(
        f"SELECT {sel_cols} FROM t_htma_sale WHERE {sale_where} LIMIT 20",
        sale_params,
    )
    sale_rows = cur.fetchall()
    print(f"销售表 t_htma_sale: 命中 {sale_count} 条（货号为空/合计/总计等 或 货号/品类/品名含汇总词）", flush=True)
    if sale_rows:
        for r in sale_rows[:10]:
            pn = r.get("product_name", "") if has_product_name else ""
            print(f"  样本: date={r['data_date']} sku={r['sku_code']!r} cat={r['category']!r} product={pn!r} amount={r['sale_amount']}", flush=True)

    # 2) 库存表：同口径
    stock_has_pn = False
    try:
        cur.execute("SELECT product_name FROM t_htma_stock LIMIT 1")
        stock_has_pn = True
    except Exception:
        pass
    if stock_has_pn:
        stock_where_like, stock_params_like = _sale_where_with_product_name()
    else:
        stock_where_like, stock_params_like = _sale_where_no_product_name()
    stock_where = "(" + sale_where_base + ") OR (" + stock_where_like + ")"
    stock_params = sale_params_base + stock_params_like
    cur.execute(
        f"SELECT COUNT(*) AS c FROM t_htma_stock WHERE {stock_where}",
        stock_params,
    )
    stock_count = cur.fetchone()["c"]
    stock_sel = "data_date, sku_code, category, stock_qty, stock_amount" + (", product_name" if stock_has_pn else "")
    cur.execute(
        f"SELECT {stock_sel} FROM t_htma_stock WHERE {stock_where} LIMIT 20",
        stock_params,
    )
    stock_rows = cur.fetchall()
    print(f"库存表 t_htma_stock: 命中 {stock_count} 条", flush=True)
    if stock_rows:
        for r in stock_rows[:10]:
            pn = r.get("product_name", "") if stock_has_pn else ""
            print(f"  样本: date={r['data_date']} sku={r['sku_code']!r} cat={r['category']!r} product={pn!r}", flush=True)

    # 3) 毛利表：品类/大类 含汇总词
    kw_params = [f"%{k}%" for k in SUMMARY_KEYWORDS]
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
        cur.execute(f"DELETE FROM t_htma_stock WHERE {stock_where}", stock_params)
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
