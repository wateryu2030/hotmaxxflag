#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入后自检：统计兼职/小时工行数、明细列填充率、抽样打印若干行，便于确认展示内容是否完整。
用法（项目根目录）: .venv/bin/python scripts/openclaw_labor_selfcheck.py
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

# 兼职/小时工明细列（与 Excel 及页面展示一致）
DETAIL_COLS = [
    "cost_include", "store_name", "person_name", "city", "position_name", "department",
    "join_date", "leave_date", "work_hours", "normal_hours", "triple_pay_hours",
    "hourly_rate", "pay_amount", "service_fee_unit", "service_fee_total", "tax",
    "total_cost", "supplier_name",
]


def _safe_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def main():
    from htma_dashboard.db_config import get_conn

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT report_month, position_type, COUNT(*) AS cnt FROM t_htma_labor_cost GROUP BY report_month, position_type ORDER BY report_month, position_type"
        )
        rows = cur.fetchall()
    except Exception as e:
        print("自检查询失败:", e)
        return
    if not rows:
        print("自检: 表 t_htma_labor_cost 无数据，跳过列填充率与抽样。")
        return

    # 检查表是否有扩展列
    cur.execute("SHOW COLUMNS FROM t_htma_labor_cost")
    columns = [r.get("Field") or list(r.values())[0] for r in cur.fetchall()]
    has_ext = all(c in columns for c in ["store_name", "cost_include"])

    print("==============================================")
    print("人力成本导入自检：兼职/小时工明细列填充率与抽样")
    print("==============================================")

    def _first(r, key="report_month"):
        return r.get(key) if isinstance(r, dict) else r[0]
    for report_month in sorted({_first(r) for r in rows}):
        print("\n--- 报表月份 %s ---" % report_month)
        for ptype in ("parttime", "hourly"):
            cur.execute(
                "SELECT COUNT(*) AS n FROM t_htma_labor_cost WHERE report_month = %s AND position_type = %s",
                (report_month, ptype),
            )
            row = cur.fetchone()
            n = int(row.get("n", row.get("COUNT(*)", 0) or 0)) if isinstance(row, dict) else (row or [0])[0]
            if n == 0:
                continue
            print("\n  [%s] 共 %d 条" % ("兼职" if ptype == "parttime" else "小时工", n))
            if not has_ext:
                print("    表无扩展列，仅基础字段；请执行 scripts/run_add_columns.py 后重新导入。")
                continue
            # 填充率：各明细列非空条数（列名已白名单）
            fill = {}
            for col in DETAIL_COLS:
                if col not in columns:
                    continue
                cur.execute(
                    "SELECT COUNT(*) FROM t_htma_labor_cost WHERE report_month = %s AND position_type = %s AND " + col + " IS NOT NULL",
                    (report_month, ptype),
                )
                row = cur.fetchone()
                fill[col] = int(row.get("COUNT(*)", 0) or 0) if isinstance(row, dict) else (row or [0])[0]
            # 简化为关键列
            key_cols = ["cost_include", "store_name", "person_name", "city", "department", "join_date", "leave_date", "work_hours", "pay_amount", "total_cost"]
            key_cols = [c for c in key_cols if c in columns]
            parts = ["%s: %d/%d" % (c, fill.get(c, 0), n) for c in key_cols]
            print("    填充: " + " | ".join(parts))

            # 抽样 2 行（全列）
            sel_cols = [c for c in DETAIL_COLS if c in columns]
            if not sel_cols:
                sel_cols = ["person_name", "position_name", "total_cost", "supplier_name"]
            cur.execute(
                "SELECT " + ", ".join(sel_cols) + " FROM t_htma_labor_cost WHERE report_month = %s AND position_type = %s ORDER BY COALESCE(total_cost, 0) DESC LIMIT 2",
                (report_month, ptype),
            )
            samples = cur.fetchall()
            for i, row in enumerate(samples):
                if isinstance(row, dict):
                    print("    样本%d: " % (i + 1) + " | ".join("%s=%s" % (k, row.get(k)) for k in sel_cols))
                else:
                    print("    样本%d: " % (i + 1) + " | ".join("%s=%s" % (sel_cols[j], row[j]) for j in range(len(sel_cols))))

    print("\n自检完成。若关键列填充为 0，请核对 Excel 表头（成本计入、店铺名、用人部门等）与 import_logic 列名匹配。")
    conn.close()


if __name__ == "__main__":
    main()
