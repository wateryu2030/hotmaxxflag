#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动化：建表 t_htma_product_master + 从下载目录导入分店商品档案 Excel，并校验数据有效。
用法（项目根目录）:
  .venv/bin/python scripts/run_product_master_create_and_import.py
  .venv/bin/python scripts/run_product_master_create_and_import.py --file /path/to/分店商品档案_xxx.xlsx
"""
import os
import re
import sys
import glob
import warnings
# 抑制 openpyxl 无默认样式警告
warnings.filterwarnings("ignore", message="Workbook contains no default style", module="openpyxl")

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _root)
os.chdir(_root)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))
except Exception:
    pass

# 建表：用 pymysql 执行 SQL，与 app 同库
def ensure_table(conn):
    sql_path = os.path.join(_root, "scripts", "19_create_product_master_table.sql")
    with open(sql_path, "r", encoding="utf-8") as f:
        content = f.read()
    cur = conn.cursor()
    for stmt in content.split(";"):
        stmt = stmt.strip()
        if not stmt or stmt.upper().startswith("USE "):
            continue
        # 去掉行内注释（-- 到行尾）
        stmt = re.sub(r"--[^\n]*", "", stmt)
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            cur.execute(stmt)
        except Exception as e:
            if "Duplicate column name" in str(e) or "already exists" in str(e).lower():
                pass
            else:
                raise
    conn.commit()
    cur.close()
    print("[OK] 表 t_htma_product_master 已创建/已存在", flush=True)


def find_excel(directory):
    for p in ["分店商品档案_*.xlsx", "分店商品档案_*.xls"]:
        for path in glob.glob(os.path.join(directory, p)):
            if os.path.isfile(path) and not os.path.basename(path).startswith("."):
                return path
    return None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", "-f", default=None, help="指定档案 Excel 路径")
    ap.add_argument("--dir", "-d", default=None, help="扫描目录，默认 ~/Downloads")
    ap.add_argument("--skip-import", action="store_true", help="仅建表，不导入")
    args = ap.parse_args()

    from htma_dashboard.db_config import get_conn
    from htma_dashboard.import_logic import import_product_master

    conn = get_conn()
    try:
        ensure_table(conn)
        # 确保 distribution_mode 列存在（消费洞察依赖）
        from htma_dashboard.import_logic import _ensure_product_master_distribution_mode
        _ensure_product_master_distribution_mode(conn)

        if args.skip_import:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS c FROM t_htma_product_master")
            row = cur.fetchone()
            total = (row.get("c") or row[0]) if row else 0
            cur.close()
            print("[OK] 当前表内条数: %d（未执行导入）" % total, flush=True)
            return 0

        excel_path = args.file
        if not excel_path and args.dir:
            excel_path = find_excel(args.dir)
        if not excel_path:
            directory = os.environ.get("IMPORT_DOWNLOADS_DIR") or os.path.expanduser("~/Downloads")
            excel_path = find_excel(directory)
        if not excel_path or not os.path.isfile(excel_path):
            print("[SKIP] 未找到分店商品档案 Excel（可指定 -f 路径或放入 ~/Downloads）", flush=True)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS c FROM t_htma_product_master")
            row = cur.fetchone()
            total = (row.get("c") or row[0]) if row else 0
            cur.close()
            print("[OK] 当前表内条数: %d" % total, flush=True)
            return 0

        print("[RUN] 导入: %s" % os.path.basename(excel_path), flush=True)
        cnt, msg = import_product_master(excel_path, conn)
        print("[OK] %s" % msg, flush=True)

        # 校验数据有效
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM t_htma_product_master")
        row = cur.fetchone()
        total = (row.get("c") or row[0]) if row else 0
        cur.execute("SELECT MIN(archive_date) AS min_d, MAX(archive_date) AS max_d FROM t_htma_product_master")
        r2 = cur.fetchone()
        min_d = r2.get("min_d") or (r2[0] if r2 else None)
        max_d = r2.get("max_d") or (r2[1] if r2 and len(r2) > 1 else None)
        cur.execute("SELECT product_status, COUNT(*) AS cnt FROM t_htma_product_master WHERE COALESCE(TRIM(product_status),'')!='' GROUP BY product_status ORDER BY cnt DESC LIMIT 5")
        status_rows = cur.fetchall()
        cur.close()

        print("[VERIFY] 总条数: %d" % total, flush=True)
        if min_d or max_d:
            print("[VERIFY] 档案日期范围: %s ~ %s" % (min_d, max_d), flush=True)
        if status_rows:
            print("[VERIFY] 按状态抽样: %s" % ", ".join("%s=%d" % (r.get("product_status") or r[0], r.get("cnt") or r[1]) for r in status_rows), flush=True)
        if total == 0:
            print("[WARN] 表内无数据，请检查 Excel 是否含「货号」列及数据行", flush=True)
            return 1
        print("[OK] 数据有效，可访问 /product_master 查看分析", flush=True)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
