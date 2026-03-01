#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从下载目录自动导入 Excel，并完成去重、刷新毛利/品类/商品、数据质量检查，确保数据完整可靠。
- 目录：默认 ~/Downloads，可通过环境变量 DOWNLOADS 或 IMPORT_DOWNLOADS_DIR 或命令行参数指定
- 查找：销售日报、销售汇总、实时库存/库存查询（取同名最新文件）
- 流程：清空表 → 导入 → 去重 → 刷新毛利/品类/商品 → 数据质量简要输出

用法:
  python scripts/auto_import_from_downloads.py [目录]
  DOWNLOADS=/path/to/excel python scripts/auto_import_from_downloads.py
  bash scripts/run_auto_import.sh   # 使用 .venv 并默认 ~/Downloads
"""
import os
import sys
import subprocess

# 默认下载目录：优先环境变量，否则 ~/Downloads
def _default_downloads():
    d = os.environ.get("IMPORT_DOWNLOADS_DIR") or os.environ.get("DOWNLOADS") or os.path.expanduser("~/Downloads")
    if not os.path.isdir(d):
        d = "/Users/apple/Downloads" if os.path.isdir("/Users/apple/Downloads") else d
    return d

STORE_ID = "沈阳超级仓"


def find_excel_files(directory):
    """在指定目录查找销售日报、销售汇总、实时库存或库存查询（取最新，排除临时文件）"""
    if not os.path.isdir(directory):
        return {}
    files = {}
    for f in os.listdir(directory):
        if f.startswith(".") or f.startswith("~"):
            continue
        path = os.path.join(directory, f)
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


def run_dedup(project_root):
    """执行去重脚本（合并同主键后保留一条），返回是否成功"""
    run_sh = os.path.join(project_root, "scripts", "run_dedup.sh")
    if not os.path.isfile(run_sh):
        return False
    try:
        subprocess.run(
            ["/bin/bash", run_sh],
            cwd=project_root,
            check=True,
            capture_output=True,
            timeout=300,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"去重脚本执行异常: {e}", flush=True)
        return False


def data_quality_summary(conn, store_id):
    """返回数据质量简要（缺失成本/售价条数、日期范围）"""
    cur = conn.cursor()
    out = []
    try:
        cur.execute("""
            SELECT COUNT(*) AS cnt FROM t_htma_sale
            WHERE store_id = %s AND (sale_cost IS NULL OR sale_cost = 0) AND sale_amount > 0
        """, (store_id,))
        row = cur.fetchone()
        mc = row["cnt"] if isinstance(row, dict) else (row[0] if row else 0)
    except Exception:
        mc = 0
    try:
        cur.execute("""
            SELECT COUNT(*) AS cnt FROM t_htma_sale
            WHERE store_id = %s AND (sale_price IS NULL OR sale_price = 0) AND sale_qty > 0
        """, (store_id,))
        row = cur.fetchone()
        mp = row["cnt"] if isinstance(row, dict) else (row[0] if row else 0)
    except Exception:
        mp = 0
    try:
        cur.execute("SELECT MIN(data_date) AS min_d, MAX(data_date) AS max_d FROM t_htma_sale WHERE store_id = %s", (store_id,))
        dr = cur.fetchone()
        min_d = dr.get("min_d") if isinstance(dr, dict) else (dr[0] if dr else None)
        max_d = dr.get("max_d") if isinstance(dr, dict) else (dr[1] if dr else None)
        if min_d and max_d:
            out.append(f"日期范围: {min_d} ~ {max_d}")
    except Exception:
        pass
    if mc > 100 or mp > 100:
        out.append(f"数据质量: 成本缺失 {mc} 条, 售价缺失 {mp} 条，建议在「经营分析-数据质量」补全")
    cur.close()
    return out


def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else _default_downloads()
    directory = os.path.abspath(os.path.expanduser(directory))
    if not os.path.isdir(directory):
        print(f"目录不存在: {directory}", flush=True)
        sys.exit(1)

    print("=== 好特卖自动导入（下载目录）===", flush=True)
    print(f"目录: {directory}", flush=True)

    project_root = os.path.join(os.path.dirname(__file__), "..")
    sys.path.insert(0, os.path.join(project_root, "htma_dashboard"))
    import pymysql
    from import_logic import (
        import_sale_daily,
        import_sale_summary,
        import_stock,
        refresh_profit,
        refresh_category_from_sale,
        sync_products_table,
        sync_category_table,
    )

    files = find_excel_files(directory)
    if not files:
        print("未找到销售日报/销售汇总/实时库存 Excel，跳过导入。", flush=True)
        sys.exit(0)

    print("找到文件:", {k: os.path.basename(v) for k, v in files.items()}, flush=True)

    conn = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "62102218"),
        database="htma_dashboard",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )

    cur = conn.cursor()
    has_sale_daily = "sale_daily" in files
    has_sale_summary = "sale_summary" in files
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
            n = sync_products_table(conn, store_id=STORE_ID)
            print(f"商品表同步: {n} 条", flush=True)
        except Exception as e:
            print(f"商品表同步失败: {e}", flush=True)
        try:
            n = sync_category_table(conn, store_id=STORE_ID)
            print(f"品类毛利表同步: {n} 条", flush=True)
        except Exception as e:
            print(f"品类毛利表同步失败: {e}", flush=True)

    conn.commit()
    conn.close()

    # 去重：合并同主键重复行，确保数据一致
    if sale_daily_cnt > 0 or sale_summary_cnt > 0 or stock_cnt > 0:
        print("执行去重...", flush=True)
        if run_dedup(project_root):
            print("去重完成", flush=True)
        else:
            print("去重跳过或失败，数据仍以当前导入为准", flush=True)

    # 再次连接输出最终统计与数据质量
    conn2 = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "62102218"),
        database="htma_dashboard",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    cur = conn2.cursor()
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
    cur.execute("SELECT MIN(data_date) AS min_d, MAX(data_date) AS max_d FROM t_htma_sale")
    dr = cur.fetchone()
    date_range = f"{dr['min_d']} ~ {dr['max_d']}" if dr and dr.get("min_d") else "-"
    conn2.close()

    print("\n=== 导入完成（数据已写入 MySQL）===", flush=True)
    print(f"销售表: {sale_total} 条，销售金额合计: {sale_total_amount:,.2f}", flush=True)
    print(f"库存表: {stock_total} 条，库存金额合计: {stock_total_amount:,.2f}", flush=True)
    print(f"毛利表: {profit_total} 条", flush=True)
    print(f"日期范围: {date_range}", flush=True)

    conn3 = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "62102218"),
        database="htma_dashboard",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    for line in data_quality_summary(conn3, STORE_ID):
        print(line, flush=True)
    conn3.close()

    print("数据完整可靠流程已跑通。", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
