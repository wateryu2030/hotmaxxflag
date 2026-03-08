#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 人力成本自动化：完整导入 Excel -> MySQL，刷新分析表，校验后飞书通知余为军。
数据分级：t_htma_labor_cost（原始按岗位汇总）-> t_htma_labor_cost_analysis（月度比对）。
用法（项目根目录）：python scripts/openclaw_labor_import_and_notify.py [Excel路径] [报表月份]
"""
import os
import sys

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _project_root)
os.chdir(_project_root)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_project_root, ".env"))
except Exception:
    pass

from htma_dashboard.db_config import get_conn


def main():
    default_excel = os.path.join(_project_root, "12月薪资表-沈阳金融中心.xlsx")
    excel_path = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else default_excel)
    report_month = (sys.argv[2].strip() if len(sys.argv) > 2 else "2025-12")

    if not os.path.isfile(excel_path):
        print("ERROR: 文件不存在", excel_path)
        sys.exit(1)

    from htma_dashboard.import_logic import import_labor_cost, refresh_labor_cost_analysis

    # 1) 完整导入到 MySQL（原始表）
    print("Step 1: 导入人力成本 Excel -> t_htma_labor_cost ...")
    conn = get_conn()
    try:
        counts, diag, _ = import_labor_cost(excel_path, report_month, conn)
        labels = {"leader": "组长", "fulltime": "组员", "parttime": "兼职", "hourly": "小时工", "cleaner": "保洁", "management": "管理岗"}
        parts = [f"{labels.get(k, k)} {v} 条" for k, v in counts.items() if v]
        print("  " + "，".join(parts) if parts else "  无数据")
        if diag:
            for d in diag:
                print("  ", d)
    finally:
        conn.close()

    # 2) 刷新分析表（比对用）
    print("Step 2: 刷新 t_htma_labor_cost_analysis ...")
    conn = get_conn()
    try:
        n = refresh_labor_cost_analysis(conn)
        print("  刷新", n, "个月份")
    finally:
        conn.close()

    # 3) 校验
    print("Step 3: 校验 ...")
    import pymysql
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute(
            "SELECT report_month, position_type, COUNT(*) AS cnt FROM t_htma_labor_cost GROUP BY report_month, position_type"
        )
        rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) AS n FROM t_htma_labor_cost_analysis")
        analysis_count = cur.fetchone()["n"]
    finally:
        conn.close()

    labels = {"leader": "组长", "fulltime": "组员", "parttime": "兼职", "hourly": "小时工", "cleaner": "保洁", "management": "管理岗"}
    detail = "，".join("%s %s 条" % (labels.get(k, k), v) for k, v in counts.items() if v) or "无"
    summary_lines = [
        "【人力成本导入完成】",
        "报表月份: " + report_month,
        "明细表 t_htma_labor_cost: " + detail,
        "分析表 t_htma_labor_cost_analysis: %s 个月份已刷新" % analysis_count,
    ]
    for r in rows:
        summary_lines.append("  %s %s %s 条" % (r["report_month"], r["position_type"], r["cnt"]))
    summary_lines.append("看板「人力成本」页可查看明细与类目总体。")
    summary_text = "\n".join(summary_lines)
    print(summary_text)

    # 4) 飞书通知余为军
    try:
        from htma_dashboard.feishu_util import send_feishu
        ok, err = send_feishu(
            summary_text,
            at_user_id="ou_8db735f2",
            at_user_name="余为军",
            title="人力成本数据导入完成",
        )
        if ok:
            print("Step 4: 飞书已通知余为军")
        else:
            print("Step 4: 飞书发送失败:", err)
    except Exception as e:
        print("Step 4: 飞书通知异常:", e)

    print("Done.")
    sys.exit(0)


if __name__ == "__main__":
    main()
