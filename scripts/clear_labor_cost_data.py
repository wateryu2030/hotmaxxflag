#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人力成本数据清空：清空明细表与汇总表，便于重新上传 Excel 后避免重复计算。
执行后请到「数据导入」重新上传各月人力成本 Excel，再刷新 /labor 查看。

用法（项目根目录）:
  python scripts/clear_labor_cost_data.py
  python scripts/clear_labor_cost_data.py --yes   # 跳过确认
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
    p = argparse.ArgumentParser(description="清空人力成本明细表与汇总表，便于重新导入")
    p.add_argument("--yes", "-y", action="store_true", help="跳过确认直接清空")
    args = p.parse_args()

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM t_htma_labor_cost")
        row = cur.fetchone()
        n_detail = (row.get("n") or 0) if isinstance(row, dict) else (row[0] if row else 0)
        cur.execute("SELECT COUNT(*) AS n FROM t_htma_labor_cost_analysis")
        row = cur.fetchone()
        n_analysis = (row.get("n") or 0) if isinstance(row, dict) else (row[0] if row else 0)
    finally:
        conn.close()

    print("当前数据：")
    print("  t_htma_labor_cost 明细表: %d 条" % n_detail)
    print("  t_htma_labor_cost_analysis 汇总表: %d 条" % n_analysis)
    if not args.yes and (n_detail or n_analysis):
        r = input("确认清空以上两张表？(y/N): ").strip().lower()
        if r != "y" and r != "yes":
            print("已取消")
            sys.exit(0)

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM t_htma_labor_cost")
        conn.commit()
        d1 = cur.rowcount
        cur.execute("DELETE FROM t_htma_labor_cost_analysis")
        conn.commit()
        d2 = cur.rowcount
        print("已清空：t_htma_labor_cost %d 条，t_htma_labor_cost_analysis %d 条。" % (d1, d2))
    finally:
        conn.close()

    print("请到「数据导入」重新上传各月人力成本 Excel，再打开 /labor 查看。")
    print("刷新汇总表可执行: .venv/bin/python -c \"from htma_dashboard.db_config import get_conn; from htma_dashboard.import_logic import refresh_labor_cost_analysis; refresh_labor_cost_analysis(get_conn())\"")


if __name__ == "__main__":
    main()
