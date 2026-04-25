#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查 t_htma_invoice_detail 表中是否有记录，用于排查「导入成功但前端不显示」"""
import os
import sys

# 项目根，确保可 import htma_dashboard
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def main():
    try:
        from htma_dashboard.db_config import get_conn
    except ImportError as e:
        print("导入失败:", e)
        print("请从项目根目录运行: python scripts/check_invoice_db.py")
        sys.exit(1)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='t_htma_invoice_detail' LIMIT 1")
        if not cur.fetchone():
            print("表 t_htma_invoice_detail 不存在。请先执行: mysql ... htma_dashboard < scripts/24_create_invoice_tables.sql")
            return
        cur.execute("""
            SELECT period_month, store_id, COUNT(*) AS cnt, SUM(invoice_amount) AS total_amount
            FROM t_htma_invoice_detail
            GROUP BY period_month, store_id
            ORDER BY period_month DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        if not rows:
            print("表 t_htma_invoice_detail 中暂无记录。")
            print("若前端提示导入成功，请确认：1) 看板连接的数据库与脚本一致；2) 导入时未报错。")
            return
        print("t_htma_invoice_detail 已有记录：")
        print("-" * 60)
        for r in rows:
            period = r.get('period_month', r[0] if isinstance(r, (list, tuple)) else None)
            store = r.get('store_id', r[1] if isinstance(r, (list, tuple)) else None)
            cnt = r.get('cnt', r[2] if isinstance(r, (list, tuple)) else None)
            total = r.get('total_amount', r[3] if isinstance(r, (list, tuple)) else None)
            period_str = period.strftime("%Y-%m") if hasattr(period, 'strftime') else period
            print("  账期: {}  门店: {}  条数: {}  开票金额合计: {}".format(period_str, store, cnt, total))
        print("-" * 60)
        first_period = rows[0].get('period_month') if isinstance(rows[0], dict) else rows[0][0]
        period_str = first_period.strftime("%Y-%m") if first_period and hasattr(first_period, 'strftime') else first_period
        print("前端「发票明细」选择上述账期（如 {}）后点「查询」应能显示。".format(period_str))
    finally:
        conn.close()

if __name__ == "__main__":
    main()
