#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人力成本数据补全：用完整薪资表 Excel 导入指定月份并刷新分析表，确保 /labor 页显示全口径与全部类目（组长/组员/兼职/小时工/保洁/管理岗）。
部署后若线上仅显示组长+组员、合计不对（如应为约 43～53 万），在服务器项目根目录执行本脚本即可。
用法:
  python scripts/ensure_labor_data.py
  python scripts/ensure_labor_data.py 2026-01
  python scripts/ensure_labor_data.py 2026-01 2025-12
  python scripts/ensure_labor_data.py 2026-01 --file "12月薪资表-沈阳金融中心.xlsx"
"""
import os
import sys
import argparse

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _project_root)
os.chdir(_project_root)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_project_root, ".env"))
except Exception:
    pass

from htma_dashboard.db_config import get_conn
from htma_dashboard.import_logic import import_labor_cost, refresh_labor_cost_analysis


def main():
    parser = argparse.ArgumentParser(description="人力成本数据补全：导入完整 Excel 并刷新分析表")
    parser.add_argument("months", nargs="*", default=["2026-01", "2025-12"], help="报表月份，如 2026-01 2025-12")
    parser.add_argument("--file", "-f", default=None, help="Excel 路径，默认项目根目录 12月薪资表-沈阳金融中心.xlsx")
    args = parser.parse_args()
    months = args.months if args.months else ["2026-01", "2025-12"]
    excel_path = args.file or os.path.join(_project_root, "12月薪资表-沈阳金融中心.xlsx")
    if not os.path.isfile(excel_path):
        print("错误：Excel 不存在", excel_path)
        print("用法：python scripts/ensure_labor_data.py [月份...] [--file 路径]")
        sys.exit(1)
    labels = {"leader": "组长/职能", "fulltime": "全职", "parttime": "兼职", "hourly": "小时工", "cleaner": "保洁", "management": "管理岗"}
    conn = get_conn()
    try:
        for report_month in months:
            print("导入", report_month, "...")
            counts, diag, _ = import_labor_cost(excel_path, report_month, conn)
            parts = [f"{labels.get(k, k)} {v} 条" for k, v in counts.items() if v]
            print("  ", ", ".join(parts) if parts else "无数据")
        print("刷新分析表...")
        n = refresh_labor_cost_analysis(conn)
        print("  已刷新", n, "个月份")
    finally:
        conn.close()
    print("完成。请打开 /labor 或看板「人力成本」查看全口径与类目拆分。")


if __name__ == "__main__":
    main()
