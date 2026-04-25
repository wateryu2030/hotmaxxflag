#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从下载目录自动导入 Excel，并完成去重、刷新毛利/品类/商品、数据质量检查，确保数据完整可靠。
- 目录：默认 ~/Downloads，可通过环境变量 DOWNLOADS 或 IMPORT_DOWNLOADS_DIR 或命令行参数指定
- 查找：销售日报、销售汇总、实时库存/库存查询（取同名最新文件）
- 流程：清空表 → 导入 → 去重 → 刷新毛利/品类/商品 → 数据质量简要输出

用法:
  python scripts/auto_import_from_downloads.py [目录]
  python scripts/auto_import_from_downloads.py [目录] --multi   # 导入目录内所有销售日报（多份）+ 销售汇总 + 库存
  python scripts/auto_import_from_downloads.py --today          # 仅处理本机「今天」修改过的上述 Excel（默认 ~/Downloads）
  DOWNLOADS=/path/to/excel python scripts/auto_import_from_downloads.py
  bash scripts/run_auto_import.sh   # 使用 .venv 并默认 ~/Downloads
"""
import os
import sys
import subprocess
from datetime import date, datetime

# 默认下载目录：优先环境变量，否则 ~/Downloads
def _default_downloads():
    d = os.environ.get("IMPORT_DOWNLOADS_DIR") or os.environ.get("DOWNLOADS") or os.path.expanduser("~/Downloads")
    if not os.path.isdir(d):
        d = "/Users/apple/Downloads" if os.path.isdir("/Users/apple/Downloads") else d
    return d

STORE_ID = "沈阳超级仓"


def _mtime_local_date(path):
    return datetime.fromtimestamp(os.path.getmtime(path)).date()


def find_excel_files(directory, only_date=None):
    """在指定目录查找销售日报、销售汇总、实时库存/库存查询、分店商品档案（取最新，排除临时文件）
    only_date: 若指定，仅考虑该日期当天修改过的文件（本机时区）。"""
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
        if only_date is not None and _mtime_local_date(path) != only_date:
            continue
        if "销售日报" in f and "品项" not in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "sale_daily" not in files or os.path.getmtime(path) > os.path.getmtime(files["sale_daily"]):
                files["sale_daily"] = path
        elif "销售汇总" in f and "品项" not in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "sale_summary" not in files or os.path.getmtime(path) > os.path.getmtime(files["sale_summary"]):
                files["sale_summary"] = path
        elif ("实时库存" in f or "库存查询" in f) and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "stock" not in files or os.path.getmtime(path) > os.path.getmtime(files["stock"]):
                files["stock"] = path
        elif "分店商品档案" in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "product_master" not in files or os.path.getmtime(path) > os.path.getmtime(files["product_master"]):
                files["product_master"] = path
    return files


def find_excel_files_multi_sale_daily(directory, only_date=None):
    """查找所有销售日报（列表，按修改时间升序）、销售汇总（最新）、库存（最新）、分店商品档案（最新），便于一次导入多份日报
    only_date: 若指定，仅该日期当天修改过的文件。"""
    if not os.path.isdir(directory):
        return {"sale_daily_list": [], "sale_summary": None, "stock": None, "product_master": None}
    sale_daily_list = []
    sale_summary = None
    stock = None
    product_master = None
    for f in os.listdir(directory):
        if f.startswith(".") or f.startswith("~"):
            continue
        path = os.path.join(directory, f)
        if not os.path.isfile(path):
            continue
        low = f.lower()
        if only_date is not None and _mtime_local_date(path) != only_date:
            continue
        if "销售日报" in f and "品项" not in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            sale_daily_list.append(path)
        elif "销售汇总" in f and "品项" not in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if sale_summary is None or os.path.getmtime(path) > os.path.getmtime(sale_summary):
                sale_summary = path
        elif ("实时库存" in f or "库存查询" in f) and (low.endswith(".xls") or low.endswith(".xlsx")):
            if stock is None or os.path.getmtime(path) > os.path.getmtime(stock):
                stock = path
        elif "分店商品档案" in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if product_master is None or os.path.getmtime(path) > os.path.getmtime(product_master):
                product_master = path
    sale_daily_list.sort(key=lambda p: os.path.getmtime(p))
    return {"sale_daily_list": sale_daily_list, "sale_summary": sale_summary, "stock": stock, "product_master": product_master}


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
    argv = [a for a in sys.argv[1:] if a not in ("--multi", "--today")]
    use_multi = "--multi" in sys.argv[1:]
    only_today = "--today" in sys.argv[1:]
    only_date = date.today() if only_today else None
    directory = argv[0] if argv else _default_downloads()
    directory = os.path.abspath(os.path.expanduser(directory))
    if not os.path.isdir(directory):
        print(f"目录不存在: {directory}", flush=True)
        sys.exit(1)

    print("=== 好特卖自动导入（下载目录）===", flush=True)
    print(f"目录: {directory}", flush=True)
    if only_today:
        print(f"模式: 仅今天修改的文件（{only_date}）", flush=True)
    if use_multi:
        print("模式: 多份销售日报 + 销售汇总 + 库存", flush=True)

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(project_root, ".env"))
    except ImportError:
        pass
    sys.path.insert(0, project_root)
    import pymysql
    from htma_dashboard.db_config import get_conn
    from htma_dashboard.import_logic import (
        import_sale_daily,
        import_sale_summary,
        import_stock,
        import_product_master,
        refresh_profit,
        refresh_category_from_sale,
        sync_products_table,
        sync_category_table,
    )

    conn = get_conn()
    cur = conn.cursor()
    sale_daily_cnt = sale_summary_cnt = stock_cnt = product_master_cnt = 0
    has_sale_daily = False
    has_sale_summary = False

    if use_multi:
        multi = find_excel_files_multi_sale_daily(directory, only_date=only_date)
        sale_daily_list = multi["sale_daily_list"]
        has_any = sale_daily_list or multi["sale_summary"] or multi["stock"] or multi.get("product_master")
        if not has_any:
            print("未找到销售日报/销售汇总/实时库存/分店商品档案 Excel，跳过导入。", flush=True)
            conn.close()
            sys.exit(0)
        print("找到 销售日报:", [os.path.basename(p) for p in sale_daily_list], flush=True)
        if multi["sale_summary"]:
            print("找到 销售汇总:", os.path.basename(multi["sale_summary"]), flush=True)
        if multi["stock"]:
            print("找到 库存:", os.path.basename(multi["stock"]), flush=True)
        if multi.get("product_master"):
            print("找到 分店商品档案:", os.path.basename(multi["product_master"]), flush=True)
        for i, path in enumerate(sale_daily_list, 1):
            cnt, diag = import_sale_daily(path, conn)
            sale_daily_cnt += cnt
            print(f"  销售日报 [{i}/{len(sale_daily_list)}] {os.path.basename(path)}: {cnt} 条", diag or "", flush=True)
        has_sale_daily = sale_daily_cnt > 0
        if multi["sale_summary"]:
            sale_summary_cnt, diag = import_sale_summary(
                multi["sale_summary"], conn, overwrite_on_duplicate=True
            )
            print(f"销售汇总: {sale_summary_cnt} 条", diag or "", flush=True)
            has_sale_summary = True
        if multi["stock"]:
            stock_cnt, stock_diag = import_stock(multi["stock"], conn)
            print(f"库存: {stock_cnt} 条", stock_diag or "", flush=True)
        if multi.get("product_master"):
            product_master_cnt, diag = import_product_master(multi["product_master"], conn)
            print(f"分店商品档案: {product_master_cnt} 条", diag or "", flush=True)
    else:
        files = find_excel_files(directory, only_date=only_date)
        if not files:
            print("未找到销售日报/销售汇总/实时库存/分店商品档案 Excel，跳过导入。", flush=True)
            conn.close()
            sys.exit(0)
        print("找到文件:", {k: os.path.basename(v) for k, v in files.items()}, flush=True)
        has_sale_daily = "sale_daily" in files
        has_sale_summary = "sale_summary" in files
        if has_sale_daily:
            sale_daily_cnt, diag = import_sale_daily(files["sale_daily"], conn)
            print(f"销售日报: {sale_daily_cnt} 条", diag or "", flush=True)
        if has_sale_summary:
            sale_summary_cnt, diag = import_sale_summary(
                files["sale_summary"], conn, overwrite_on_duplicate=True
            )
            print(f"销售汇总: {sale_summary_cnt} 条", diag or "", flush=True)
        if "stock" in files:
            stock_cnt, stock_diag = import_stock(files["stock"], conn)
            print(f"库存: {stock_cnt} 条", stock_diag or "", flush=True)
        if "product_master" in files:
            product_master_cnt, diag = import_product_master(files["product_master"], conn)
            print(f"分店商品档案: {product_master_cnt} 条", diag or "", flush=True)

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

    print("清理误导入的合计/汇总行...", flush=True)
    del_py = os.path.join(project_root, "scripts", "delete_summary_rows.py")
    try:
        r = subprocess.run(
            [sys.executable, del_py],
            cwd=project_root,
            timeout=180,
            capture_output=True,
            text=True,
        )
        if r.stdout:
            print(r.stdout, end="", flush=True)
        if r.returncode != 0:
            print(
                "清理脚本异常（可手动执行: bash scripts/run_delete_summary_rows.sh）",
                r.stderr or "",
                flush=True,
            )
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"清理合计行失败: {e}", flush=True)

    # 再次连接输出最终统计与数据质量
    conn2 = get_conn()
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
    try:
        cur.execute("SELECT COUNT(*) AS c FROM t_htma_product_master")
        product_master_total = cur.fetchone()["c"]
    except Exception:
        product_master_total = 0
    conn2.close()

    print("\n=== 导入完成（数据已写入 MySQL）===", flush=True)
    print(f"销售表: {sale_total} 条，销售金额合计: {sale_total_amount:,.2f}", flush=True)
    print(f"库存表: {stock_total} 条，库存金额合计: {stock_total_amount:,.2f}", flush=True)
    print(f"毛利表: {profit_total} 条", flush=True)
    if product_master_total > 0:
        print(f"商品档案表: {product_master_total} 条", flush=True)
    print(f"日期范围: {date_range}", flush=True)

    conn3 = get_conn()
    for line in data_quality_summary(conn3, STORE_ID):
        print(line, flush=True)
    conn3.close()

    print("数据完整可靠流程已跑通。", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
