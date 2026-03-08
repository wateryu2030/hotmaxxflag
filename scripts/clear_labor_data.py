#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清空人力成本数据，便于重新导入。
会 TRUNCATE：t_htma_labor_cost、t_htma_labor_cost_analysis。
用法: .venv/bin/python scripts/clear_labor_data.py --confirm
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except ImportError:
    pass
sys.path.insert(0, _ROOT)

try:
    from htma_dashboard.db_config import get_conn
except ImportError:
    print("未找到 db_config。请用项目 .venv 运行: .venv/bin/python scripts/clear_labor_data.py --confirm", flush=True)
    sys.exit(1)


def main():
    if "--confirm" not in sys.argv and "-y" not in sys.argv:
        print("将清空人力成本表：t_htma_labor_cost、t_htma_labor_cost_analysis", flush=True)
        print("执行前请确认。若确定清空，请加参数: --confirm 或 -y", flush=True)
        sys.exit(0)

    conn = get_conn()
    cur = conn.cursor()
    for t in ["t_htma_labor_cost", "t_htma_labor_cost_analysis"]:
        try:
            cur.execute("TRUNCATE TABLE %s" % t)
            print("已清空 %s" % t, flush=True)
        except Exception as e:
            if "doesn't exist" in str(e):
                print("跳过 %s（表不存在）" % t, flush=True)
            else:
                print("清空 %s 失败: %s" % (t, e), flush=True)
    conn.commit()
    conn.close()
    print("完成。请到「数据导入」重新上传人力成本 Excel，或运行 scripts/run_labor_import.sh。", flush=True)


if __name__ == "__main__":
    main()
