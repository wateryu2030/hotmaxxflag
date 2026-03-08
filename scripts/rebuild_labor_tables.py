#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重建人力成本表结构：按 13_create_labor_cost_table.sql 建表（含 person_name、pre_tax_pay 及唯一键），
并清空 t_htma_labor_cost_analysis。执行后需重新导入人力 Excel。

用法（项目根目录）:
  python scripts/rebuild_labor_tables.py
  python scripts/rebuild_labor_tables.py --yes
"""
import os
import sys

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _root)
os.chdir(_root)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))
except Exception:
    pass

from htma_dashboard.db_config import get_conn


def main():
    import argparse
    p = argparse.ArgumentParser(description="重建人力成本表结构并清空汇总表")
    p.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    args = p.parse_args()

    sql_path = os.path.join(_root, "scripts", "13_create_labor_cost_table.sql")
    if not os.path.isfile(sql_path):
        print("未找到", sql_path)
        sys.exit(1)

    if not args.yes:
        r = input("将 DROP t_htma_labor_cost 并按新结构重建、清空 t_htma_labor_cost_analysis，确认？(y/N): ").strip().lower()
        if r not in ("y", "yes"):
            print("已取消")
            sys.exit(0)

    conn = get_conn()
    try:
        cur = conn.cursor()
        with open(sql_path, "r", encoding="utf-8") as f:
            sql_content = f.read()
        for raw in sql_content.split(";"):
            stmt = raw.strip()
            if not stmt or stmt.startswith("--"):
                continue
            if stmt.upper().startswith("USE "):
                continue
            cur.execute(stmt)
            conn.commit()
        print("已执行 13_create_labor_cost_table.sql（含 person_name、pre_tax_pay 及唯一键）")
        cur.execute("DELETE FROM t_htma_labor_cost_analysis")
        conn.commit()
        print("已清空 t_htma_labor_cost_analysis")
    finally:
        conn.close()

    print("请运行 scripts/openclaw_labor_import_from_downloads.py 或到「数据导入」重新上传人力成本 Excel。")


if __name__ == "__main__":
    main()
