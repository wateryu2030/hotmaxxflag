#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人力成本「整体处理」：导入完整薪资表 Excel（含组长/组员/兼职/小时工/保洁/管理岗等所有 sheet），
刷新分析表，并输出全口径合计与类目拆分。用于补齐 53 万等全口径数据。
需在安装项目依赖的环境中运行（openpyxl、pymysql、pandas 等），与启动看板同一 venv。
用法（在项目根目录）:
  python scripts/import_labor_excel_and_analyze.py [Excel路径] [报表月份]
  报表月份默认 2025-12；Excel 需为完整薪资表（如 12月薪资表-沈阳金融中心(1).xlsx，多 sheet 自动识别）。
示例:
  python scripts/import_labor_excel_and_analyze.py
  python scripts/import_labor_excel_and_analyze.py "12月薪资表-沈阳金融中心(1).xlsx" 2025-12
"""
import os
import sys

# 项目根目录并加载 .env
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _project_root)
os.chdir(_project_root)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_project_root, ".env"))
except Exception:
    pass

import pymysql
from htma_dashboard.db_config import get_conn


def main():
    default_excel = os.path.join(_project_root, "12月薪资表-沈阳金融中心.xlsx")
    excel_path = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else default_excel)
    report_month = (sys.argv[2].strip() if len(sys.argv) > 2 else "2025-12")

    if not os.path.isfile(excel_path):
        print("文件不存在:", excel_path)
        print("用法: python scripts/import_labor_excel_and_analyze.py [Excel路径] [报表月份]")
        sys.exit(1)

    from htma_dashboard.import_logic import import_labor_cost, refresh_labor_cost_analysis

    print("导入文件:", excel_path)
    print("报表月份:", report_month)
    conn = get_conn()
    try:
        counts, diag, _ = import_labor_cost(excel_path, report_month, conn)
        labels = {"leader": "组长/职能", "fulltime": "全职", "parttime": "兼职", "hourly": "小时工", "cleaner": "保洁", "management": "管理岗"}
        parts = [f"{labels.get(k, k)} {v} 条" for k, v in counts.items() if v]
        print("导入结果:", ", ".join(parts) if parts else "无数据")
        if diag:
            for d in diag:
                print("  ", d)
        print("刷新分析表...")
        n = refresh_labor_cost_analysis(conn)
        print("  已刷新", n, "个月份")
    finally:
        conn.close()

    # 输出全口径 + 按类目拆分（与看板一致）
    months_to_show = [report_month]
    try:
        y, m = report_month.split("-")
        y, m = int(y), int(m)
        if m == 12:
            months_to_show.append(f"{y+1}-01")
        else:
            months_to_show.append(f"{y}-{m+1:02d}")
    except Exception:
        months_to_show.append("2026-01")

    type_names = {"leader": "组长", "fulltime": "组员", "parttime": "兼职", "hourly": "小时工", "cleaner": "保洁", "management": "管理岗"}
    print("\n--- 人力成本汇总（全口径 = 所有类目合计）---")
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        for month in months_to_show:
            cur.execute(
                """
                SELECT position_type, COUNT(*) AS cnt,
                       COALESCE(SUM(COALESCE(total_cost, company_cost)), 0) AS cost
                FROM t_htma_labor_cost WHERE report_month = %s
                GROUP BY position_type
                """,
                (month,),
            )
            rows = cur.fetchall()
            if not rows:
                print(month, ": 暂无数据")
                continue
            total_cost = 0
            parts = []
            for r in rows:
                t = r["position_type"] or ""
                cnt = int(r["cnt"] or 0)
                cost = float(r["cost"] or 0)
                total_cost += cost
                parts.append("%s %d 岗 %s 元" % (type_names.get(t, t), cnt, f"{cost:,.2f}"))
            print(month, ": 全口径", f"{total_cost:,.2f}", "元 |", " | ".join(parts))
    finally:
        conn.close()
    print("\n可在看板「人力成本」或 /labor 页选择对应月份查看明细。")


if __name__ == "__main__":
    main()
