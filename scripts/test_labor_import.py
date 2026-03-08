#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test labor cost import with 12月薪资表 Excel."""
import os
import sys

# 项目根目录（脚本所在目录的上一级）
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))
load_dotenv()

sys.path.insert(0, ROOT)
os.chdir(os.path.join(ROOT, "htma_dashboard"))

import pymysql
from htma_dashboard.db_config import get_conn
from htma_dashboard.import_logic import import_labor_cost, refresh_labor_cost_analysis

def main():
    path = "/Users/zhonglian/Downloads/12月薪资表-沈阳金融中心(1).xlsx"
    report_month = "2025-12"
    try:
        conn = get_conn()
    except pymysql.err.OperationalError as e:
        if "1045" in str(e) or "Access denied" in str(e):
            print("数据库连接失败：请检查项目根目录 .env 中是否配置 MYSQL_PASSWORD（及 MYSQL_USER/MYSQL_HOST）。")
            print("示例：MYSQL_HOST=127.0.0.1  MYSQL_USER=root  MYSQL_PASSWORD=你的密码  MYSQL_DATABASE=htma_dashboard")
        raise
    cur = conn.cursor()
    cur.execute("DELETE FROM t_htma_labor_cost WHERE report_month = %s", (report_month,))
    conn.commit()
    counts, diag, _ = import_labor_cost(path, report_month, conn)
    print("Import: counts=%s, diag=%s" % (counts, diag))
    refresh_labor_cost_analysis(conn)
    cur.execute("SELECT * FROM t_htma_labor_cost_analysis WHERE report_month = %s", (report_month,))
    row = cur.fetchone()
    print("Analysis:", row)
    cur.execute(
        "SELECT position_type, COUNT(*) AS cnt, ROUND(SUM(total_cost), 2) AS total FROM t_htma_labor_cost WHERE report_month = %s GROUP BY position_type",
        (report_month,),
    )
    for r in cur.fetchall():
        print("  ", r)
    conn.close()

if __name__ == "__main__":
    main()
