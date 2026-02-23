#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手工整理：剔除重复数据。按业务主键合并金额后只保留一条，删除其余重复行。
- 销售表 t_htma_sale: 主键 (data_date, sku_code)，合并时累加 sale_qty/sale_amount/sale_cost/gross_profit
- 库存表 t_htma_stock: 主键 (data_date, sku_code)，合并时累加 stock_qty/stock_amount
- 毛利表 t_htma_profit: 主键 (data_date, category, store_id)，合并时累加 total_sale/total_profit

用法: python3 scripts/dedup_htma_tables.py [--dry-run]
需先安装依赖: pip3 install pymysql  或  pip3 install -r htma_dashboard/requirements.txt
"""
import os
import sys

try:
    import pymysql
except ImportError:
    print("未找到 pymysql。本机为 Homebrew Python 时请用项目虚拟环境运行：", flush=True)
    print("  bash scripts/ensure_venv.sh   # 首次：创建 .venv 并安装依赖", flush=True)
    print("  bash scripts/run_dedup.sh --dry-run   # 用 venv 执行去重脚本", flush=True)
    print("或手动：", flush=True)
    print("  python3 -m venv .venv && source .venv/bin/activate", flush=True)
    print("  pip install -r htma_dashboard/requirements.txt", flush=True)
    print("  python scripts/dedup_htma_tables.py --dry-run", flush=True)
    sys.exit(1)


def get_conn():
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
        print("【仅查询重复条数，不执行合并删除】--dry-run", flush=True)

    conn = get_conn()
    cur = conn.cursor()

    # 1) 销售表：总行数 vs 按(日期,货号)去重后行数，以及重复组
    cur.execute("SELECT COUNT(*) AS total FROM t_htma_sale")
    sale_total = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) AS uniq FROM (SELECT data_date, sku_code FROM t_htma_sale GROUP BY data_date, sku_code) t")
    sale_uniq = cur.fetchone()["uniq"]
    sale_dupe_rows = max(0, sale_total - sale_uniq)
    cur.execute("""
        SELECT data_date, sku_code, COUNT(*) AS cnt, SUM(sale_qty) AS s_qty, SUM(sale_amount) AS s_amt, SUM(sale_cost) AS s_cost, SUM(gross_profit) AS s_gp
        FROM t_htma_sale
        GROUP BY data_date, sku_code
        HAVING COUNT(*) > 1
    """)
    sale_dupes = cur.fetchall()
    sale_dupe_groups = len(sale_dupes)
    print(f"销售表 t_htma_sale: 总行 {sale_total}，按(日期,货号)去重后 {sale_uniq}，重复 {sale_dupe_rows} 条（重复组 {sale_dupe_groups} 个）", flush=True)

    # 2) 库存表
    cur.execute("SELECT COUNT(*) AS total FROM t_htma_stock")
    stock_total = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) AS uniq FROM (SELECT data_date, sku_code FROM t_htma_stock GROUP BY data_date, sku_code) t")
    stock_uniq = cur.fetchone()["uniq"]
    stock_dupe_rows = max(0, stock_total - stock_uniq)
    cur.execute("""
        SELECT data_date, sku_code, COUNT(*) AS cnt
        FROM t_htma_stock
        GROUP BY data_date, sku_code
        HAVING COUNT(*) > 1
    """)
    stock_dupes = cur.fetchall()
    stock_dupe_groups = len(stock_dupes)
    print(f"库存表 t_htma_stock: 总行 {stock_total}，按(日期,货号)去重后 {stock_uniq}，重复 {stock_dupe_rows} 条（重复组 {stock_dupe_groups} 个）", flush=True)

    # 3) 毛利表
    cur.execute("SELECT COUNT(*) AS total FROM t_htma_profit")
    profit_total = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) AS uniq FROM (SELECT data_date, category, store_id FROM t_htma_profit GROUP BY data_date, category, store_id) t")
    profit_uniq = cur.fetchone()["uniq"]
    profit_dupe_rows = max(0, profit_total - profit_uniq)
    cur.execute("""
        SELECT data_date, category, store_id, COUNT(*) AS cnt
        FROM t_htma_profit
        GROUP BY data_date, category, store_id
        HAVING COUNT(*) > 1
    """)
    profit_dupes = cur.fetchall()
    profit_dupe_groups = len(profit_dupes)
    print(f"毛利表 t_htma_profit: 总行 {profit_total}，按(日期,品类,门店)去重后 {profit_uniq}，重复 {profit_dupe_rows} 条（重复组 {profit_dupe_groups} 个）", flush=True)

    has_any_dupe = sale_dupe_rows > 0 or stock_dupe_rows > 0 or profit_dupe_rows > 0
    if has_any_dupe:
        print("检测到重复数据，将合并金额后保留一条并删除其余。", flush=True)

    if dry_run:
        conn.close()
        print("dry-run 结束。", flush=True)
        return

    # 执行合并：每组保留 id 最小的一行并更新为合并后的金额，再删除同组其余行（无重复时 DELETE 影响 0 行）
    # 销售表：主键 (data_date, sku_code)
    if sale_dupe_groups > 0:
        cur.execute("""
            UPDATE t_htma_sale t
            INNER JOIN (
                SELECT data_date, sku_code, MIN(id) AS keep_id,
                       SUM(sale_qty) AS s_qty, SUM(sale_amount) AS s_amt, SUM(sale_cost) AS s_cost, SUM(gross_profit) AS s_gp
                FROM t_htma_sale
                GROUP BY data_date, sku_code
                HAVING COUNT(*) > 1
            ) agg ON t.data_date = agg.data_date AND t.sku_code = agg.sku_code AND t.id = agg.keep_id
            SET t.sale_qty = agg.s_qty, t.sale_amount = agg.s_amt, t.sale_cost = agg.s_cost, t.gross_profit = agg.s_gp
        """)
        print("销售表: 已合并重复组金额", flush=True)
    # 始终执行：删除「同主键下 id 非最小」的行，确保每主键只留一条（无重复时影响 0 行）
    cur.execute("""
        DELETE t FROM t_htma_sale t
        INNER JOIN (SELECT data_date, sku_code, MIN(id) AS keep_id FROM t_htma_sale GROUP BY data_date, sku_code) k
        ON t.data_date = k.data_date AND t.sku_code = k.sku_code AND t.id <> k.keep_id
    """)
    if cur.rowcount > 0:
        print(f"销售表: 已删除 {cur.rowcount} 条重复行", flush=True)

    if stock_dupe_groups > 0:
        cur.execute("""
            UPDATE t_htma_stock t
            INNER JOIN (
                SELECT data_date, sku_code, MIN(id) AS keep_id, SUM(stock_qty) AS s_qty, SUM(stock_amount) AS s_amt
                FROM t_htma_stock
                GROUP BY data_date, sku_code
                HAVING COUNT(*) > 1
            ) agg ON t.data_date = agg.data_date AND t.sku_code = agg.sku_code AND t.id = agg.keep_id
            SET t.stock_qty = agg.s_qty, t.stock_amount = agg.s_amt
        """)
        print("库存表: 已合并重复组金额", flush=True)
    cur.execute("""
        DELETE t FROM t_htma_stock t
        INNER JOIN (SELECT data_date, sku_code, MIN(id) AS keep_id FROM t_htma_stock GROUP BY data_date, sku_code) k
        ON t.data_date = k.data_date AND t.sku_code = k.sku_code AND t.id <> k.keep_id
    """)
    if cur.rowcount > 0:
        print(f"库存表: 已删除 {cur.rowcount} 条重复行", flush=True)

    if profit_dupe_groups > 0:
        cur.execute("""
            UPDATE t_htma_profit t
            INNER JOIN (
                SELECT data_date, category, store_id, MIN(id) AS keep_id, SUM(total_sale) AS s_sale, SUM(total_profit) AS s_profit
                FROM t_htma_profit
                GROUP BY data_date, category, store_id
                HAVING COUNT(*) > 1
            ) agg ON t.data_date = agg.data_date AND t.category = agg.category AND t.store_id = agg.store_id AND t.id = agg.keep_id
            SET t.total_sale = agg.s_sale, t.total_profit = agg.s_profit,
                t.profit_rate = CASE WHEN agg.s_sale > 0 THEN agg.s_profit / agg.s_sale ELSE 0 END
        """)
        print("毛利表: 已合并重复组金额", flush=True)
    cur.execute("""
        DELETE t FROM t_htma_profit t
        INNER JOIN (SELECT data_date, category, store_id, MIN(id) AS keep_id FROM t_htma_profit GROUP BY data_date, category, store_id) k
        ON t.data_date = k.data_date AND t.category = k.category AND t.store_id = k.store_id AND t.id <> k.keep_id
    """)
    if cur.rowcount > 0:
        print(f"毛利表: 已删除 {cur.rowcount} 条重复行", flush=True)

    conn.commit()

    # 整理后自动更新衍生表：销售去重后重算毛利并同步品类；库存/销售去重后同步商品表；毛利去重后同步品类表
    if sale_dupe_rows > 0 or stock_dupe_rows > 0 or profit_dupe_rows > 0:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "htma_dashboard"))
        from import_logic import refresh_profit, sync_products_table, sync_category_table
        if sale_dupe_rows > 0:
            refresh_profit(conn)
            conn.commit()
            print("已刷新毛利表（按销售表重新汇总）。", flush=True)
        if sale_dupe_rows > 0 or stock_dupe_rows > 0:
            try:
                n = sync_products_table(conn)
                conn.commit()
                print(f"已同步商品表: {n} 条。", flush=True)
            except Exception as e:
                print(f"商品表同步跳过: {e}", flush=True)
        if sale_dupe_rows > 0 or profit_dupe_rows > 0:
            try:
                n = sync_category_table(conn)
                conn.commit()
                print(f"已同步品类毛利表: {n} 条。", flush=True)
            except Exception as e:
                print(f"品类表同步跳过: {e}", flush=True)

    conn.close()
    print("完成。", flush=True)


if __name__ == "__main__":
    main()
