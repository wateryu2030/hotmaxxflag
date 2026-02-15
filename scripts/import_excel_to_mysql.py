#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将下载目录下的好特卖 Excel（销售日报、销售汇总、实时库存）导入 MySQL htma_dashboard，
供 JimuReport 通过数据源直接使用。
用法: python3 import_excel_to_mysql.py [下载目录]
默认下载目录: /Users/apple/Downloads
MySQL: -h 127.0.0.1 -u root -p62102218, 库 htma_dashboard
"""

import os
import re
import sys
from datetime import datetime

import pandas as pd
import pymysql
from pymysql.converters import escape_string

DOWNLOADS = os.environ.get("DOWNLOADS", "/Users/apple/Downloads")
MYSQL = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "62102218",
    "database": "htma_dashboard",
    "charset": "utf8mb4",
}


def _safe_decimal(v, default=0):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_str(v, max_len=64):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()[:max_len] or None
    return s if s else None


def _parse_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    s = str(v).strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def ensure_db(conn):
    conn.cursor().execute("CREATE DATABASE IF NOT EXISTS htma_dashboard CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    conn.select_db("htma_dashboard")


def import_sale_daily(excel_path, conn):
    """销售日报：xlsx 39列 日期=26,数量=28,金额=29,参考金额=38；xls 更多列 日期=27,数量=29,金额=30,参考金额=35"""
    df = pd.read_excel(excel_path, header=None)
    if df.shape[0] <= 5:
        return 0
    # 检测列布局：39列为 xlsx 格式
    ncol = df.shape[1]
    if ncol == 39:
        col_date, col_qty, col_amount, col_cost = 26, 28, 29, 38
        col_category = 15
    elif ncol >= 36:
        col_date, col_qty, col_amount, col_cost = 27, 29, 30, 35
        col_category = 16
    else:
        return 0
    data_rows = df.iloc[5:]
    store_id = "沈阳超级仓"
    inserted = 0
    cur = conn.cursor()
    for _, row in data_rows.iterrows():
        sku = _safe_str(row.iloc[2])
        category = _safe_str(row.iloc[col_category]) if col_category < ncol else _safe_str(row.iloc[10])
        dt = _parse_date(row.iloc[col_date])
        sale_qty = _safe_decimal(row.iloc[col_qty])
        sale_amount = _safe_decimal(row.iloc[col_amount])
        cost = _safe_decimal(row.iloc[col_cost])
        if not sku or not dt:
            continue
        gross = sale_amount - cost if cost else None
        try:
            cur.execute(
                """INSERT INTO t_htma_sale (data_date, sku_code, category, sale_qty, sale_amount, sale_cost, gross_profit, store_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE
                   sale_qty = sale_qty + VALUES(sale_qty),
                   sale_amount = sale_amount + VALUES(sale_amount),
                   sale_cost = sale_cost + VALUES(sale_cost),
                   gross_profit = sale_amount - sale_cost""",
                (dt, sku, category, sale_qty, sale_amount, cost, gross, store_id),
            )
            inserted += 1
        except Exception as e:
            print(f"  skip row sku={sku} date={dt}: {e}")
    conn.commit()
    return inserted


def import_sale_summary(excel_path, conn):
    """销售汇总：货号=2, 类别名称=9, 销售日期=27, 销售数量=31, 销售金额=32, 参考进价金额=42"""
    df = pd.read_excel(excel_path, header=None)
    if df.shape[0] <= 5 or df.shape[1] < 43:
        return 0
    data_rows = df.iloc[5:]
    store_id = "沈阳超级仓"
    inserted = 0
    cur = conn.cursor()
    for _, row in data_rows.iterrows():
        try:
            sku = _safe_str(row.iloc[2])
            category = _safe_str(row.iloc[9]) or _safe_str(row.iloc[13]) if row.index.size > 13 else _safe_str(row.iloc[9])
            dt = _parse_date(row.iloc[27])
            sale_qty = _safe_decimal(row.iloc[31])
            sale_amount = _safe_decimal(row.iloc[32])
            cost = _safe_decimal(row.iloc[42])
        except IndexError:
            continue
        if not sku or not dt:
            continue
        gross = sale_amount - cost if cost else None
        try:
            cur.execute(
                """INSERT INTO t_htma_sale (data_date, sku_code, category, sale_qty, sale_amount, sale_cost, gross_profit, store_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE
                   sale_qty = sale_qty + VALUES(sale_qty),
                   sale_amount = sale_amount + VALUES(sale_amount),
                   sale_cost = sale_cost + VALUES(sale_cost),
                   gross_profit = sale_amount - sale_cost""",
                (dt, sku, category, sale_qty, sale_amount, cost, gross, store_id),
            )
            inserted += 1
        except Exception as e:
            pass  # skip duplicate or invalid row
    conn.commit()
    return inserted


def import_stock(excel_path, conn):
    """实时库存：货号=4, 类别名称=3, 实时库存=11, 库存金额=13。日期从文件名或今天"""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", os.path.basename(excel_path))
    data_date = m.group(0) if m else datetime.now().strftime("%Y-%m-%d")
    df = pd.read_excel(excel_path, header=None)
    if df.shape[0] <= 7:
        return 0
    data_rows = df.iloc[7:]
    store_id = "沈阳超级仓"
    inserted = 0
    cur = conn.cursor()
    for _, row in data_rows.iterrows():
        sku = _safe_str(row.iloc[4])
        category = _safe_str(row.iloc[3])
        qty = _safe_decimal(row.iloc[11])
        amount = _safe_decimal(row.iloc[13])
        if not sku:
            continue
        try:
            cur.execute(
                """INSERT INTO t_htma_stock (data_date, sku_code, category, stock_qty, stock_amount, store_id)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE stock_qty = VALUES(stock_qty), stock_amount = VALUES(stock_amount)""",
                (data_date, sku, category, qty, amount, store_id),
            )
            inserted += 1
        except Exception as e:
            print(f"  skip row sku={sku}: {e}")
    conn.commit()
    return inserted


def refresh_profit(conn):
    """按日期+品类汇总销售表，写入毛利表（含分类层级）。profit_rate 限制在 0~1 避免越界"""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO t_htma_profit (data_date, category, total_sale, total_profit, profit_rate, store_id,
            category_code, category_large_code, category_large, category_mid_code, category_mid, category_small_code, category_small)
        SELECT data_date, COALESCE(category, '未分类'),
               SUM(sale_amount), SUM(COALESCE(gross_profit, 0)),
               LEAST(1, GREATEST(0, CASE WHEN SUM(sale_amount) > 0 THEN SUM(COALESCE(gross_profit, 0)) / SUM(sale_amount) ELSE 0 END)),
               store_id,
               MAX(category_code), MAX(category_large_code), MAX(category_large),
               MAX(category_mid_code), MAX(category_mid), MAX(category_small_code), MAX(category_small)
        FROM t_htma_sale
        GROUP BY data_date, category, store_id
        ON DUPLICATE KEY UPDATE
        total_sale = VALUES(total_sale),
        total_profit = VALUES(total_profit),
        profit_rate = VALUES(profit_rate),
        category_code = VALUES(category_code),
        category_large_code = VALUES(category_large_code),
        category_large = VALUES(category_large),
        category_mid_code = VALUES(category_mid_code),
        category_mid = VALUES(category_mid),
        category_small_code = VALUES(category_small_code),
        category_small = VALUES(category_small)
    """)
    conn.commit()
    return cur.rowcount


def main():
    download_dir = sys.argv[1] if len(sys.argv) > 1 else DOWNLOADS
    if not os.path.isdir(download_dir):
        print(f"目录不存在: {download_dir}")
        sys.exit(1)

    # 查找要导入的 Excel
    sale_daily = []
    sale_summary = []
    stock = []
    for f in os.listdir(download_dir):
        if f.startswith("."):
            continue
        path = os.path.join(download_dir, f)
        if not os.path.isfile(path):
            continue
        low = f.lower()
        if "销售日报" in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            sale_daily.append(path)
        if "销售汇总_默认" in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            sale_summary.append(path)
        if "实时库存" in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            stock.append(path)

    sale_daily.sort(reverse=True)
    sale_summary.sort(reverse=True)
    stock.sort(reverse=True)

    print("连接 MySQL...")
    conn = pymysql.connect(
        host=MYSQL["host"],
        port=MYSQL["port"],
        user=MYSQL["user"],
        password=MYSQL["password"],
        charset=MYSQL["charset"],
    )
    ensure_db(conn)
    # 若表不存在，请先执行: mysql -h 127.0.0.1 -u root -p62102218 < scripts/01_create_tables.sql

    total = 0
    for path in sale_daily[:3]:
        print(f"导入 销售日报: {os.path.basename(path)}")
        n = import_sale_daily(path, conn)
        total += n
        print(f"  写入 {n} 条")
    for path in sale_summary[:2]:
        print(f"导入 销售汇总: {os.path.basename(path)}")
        n = import_sale_summary(path, conn)
        total += n
        print(f"  写入 {n} 条")
    for path in stock[:3]:
        print(f"导入 实时库存: {os.path.basename(path)}")
        n = import_stock(path, conn)
        total += n
        print(f"  写入 {n} 条")

    print("刷新毛利表（按日期+品类汇总）...")
    refresh_profit(conn)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM t_htma_sale")
    sale_cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM t_htma_stock")
    stock_cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM t_htma_profit")
    profit_cnt = cur.fetchone()[0]
    cur.execute("SELECT MIN(data_date), MAX(data_date) FROM t_htma_sale")
    dr = cur.fetchone()
    conn.close()
    print("完成。JimuReport 数据源: host=127.0.0.1, 库=htma_dashboard")
    print("---------- 数据概况 ----------")
    print(f"  销售表 t_htma_sale:   {sale_cnt:,} 条")
    print(f"  库存表 t_htma_stock:   {stock_cnt:,} 条")
    print(f"  毛利表 t_htma_profit: {profit_cnt:,} 条")
    print(f"  销售日期范围: {dr[0]} ~ {dr[1]}")
    print("------------------------------")


if __name__ == "__main__":
    main()
