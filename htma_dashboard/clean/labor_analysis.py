# -*- coding: utf-8 -*-
"""人力成本分析汇总刷新 — clean 层：从 t_htma_labor_cost 汇总写入 t_htma_labor_cost_analysis"""
import pymysql


def refresh_labor_cost_analysis(conn):
    """从 t_htma_labor_cost 汇总写入 t_htma_labor_cost_analysis，用于月度比对分析。返回刷新的月份数。"""
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT report_month,
               SUM(CASE WHEN position_type='leader' THEN 1 ELSE 0 END) AS leader_count,
               COALESCE(SUM(CASE WHEN position_type='leader' THEN total_cost ELSE 0 END), 0) AS leader_total_cost,
               SUM(CASE WHEN position_type='fulltime' THEN 1 ELSE 0 END) AS fulltime_count,
               COALESCE(SUM(CASE WHEN position_type='fulltime' THEN COALESCE(total_cost, company_cost) ELSE 0 END), 0) AS fulltime_total_cost,
               COALESCE(SUM(CASE WHEN position_type='fulltime' THEN work_hours ELSE 0 END), 0) AS fulltime_total_hours,
               COALESCE(SUM(total_cost), 0) AS total_all_cost
        FROM t_htma_labor_cost
        GROUP BY report_month
        ORDER BY report_month
    """)
    rows = cur.fetchall()
    if not rows:
        return 0
    cur.execute("""
        CREATE TABLE IF NOT EXISTS t_htma_labor_cost_analysis (
          report_month VARCHAR(7) NOT NULL PRIMARY KEY,
          leader_count INT NOT NULL DEFAULT 0,
          leader_total_cost DECIMAL(14,2) NOT NULL DEFAULT 0,
          fulltime_count INT NOT NULL DEFAULT 0,
          fulltime_total_cost DECIMAL(14,2) NOT NULL DEFAULT 0,
          fulltime_total_hours DECIMAL(12,2) NOT NULL DEFAULT 0,
          total_labor_cost DECIMAL(14,2) NOT NULL DEFAULT 0,
          prev_month_total DECIMAL(14,2) DEFAULT NULL,
          mom_pct DECIMAL(8,2) DEFAULT NULL,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()
    prev_by_month = {}
    for r in rows:
        total_all = float(r.get("total_all_cost") or 0)
        prev_by_month[r["report_month"]] = total_all
    n = 0
    for r in rows:
        month = r["report_month"]
        leader_total = round(float(r["leader_total_cost"] or 0), 2)
        fulltime_total = round(float(r["fulltime_total_cost"] or 0), 2)
        hours = round(float(r["fulltime_total_hours"] or 0), 2)
        total = round(float(r.get("total_all_cost") or 0), 2)
        prev_total = None
        mom_pct = None
        try:
            y, m = map(int, month.split("-"))
            if m == 1:
                prev_month = f"{y-1}-12"
            else:
                prev_month = f"{y}-{m-1:02d}"
            prev_total = prev_by_month.get(prev_month)
            if prev_total is not None and prev_total != 0:
                mom_pct = round((total - prev_total) / prev_total * 100, 2)
        except Exception:
            pass
        cur.execute("""
            INSERT INTO t_htma_labor_cost_analysis
            (report_month, leader_count, leader_total_cost, fulltime_count, fulltime_total_cost,
             fulltime_total_hours, total_labor_cost, prev_month_total, mom_pct)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
            leader_count=VALUES(leader_count), leader_total_cost=VALUES(leader_total_cost),
            fulltime_count=VALUES(fulltime_count), fulltime_total_cost=VALUES(fulltime_total_cost),
            fulltime_total_hours=VALUES(fulltime_total_hours), total_labor_cost=VALUES(total_labor_cost),
            prev_month_total=VALUES(prev_month_total), mom_pct=VALUES(mom_pct)
        """, (month, r["leader_count"], leader_total, r["fulltime_count"], fulltime_total,
              hours, total, prev_total, mom_pct))
        n += 1
    conn.commit()
    return n
