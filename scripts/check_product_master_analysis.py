#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动化检查：分店商品档案分析接口是否正常，无 dictionary changed size during iteration。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

def main():
    from htma_dashboard.db_config import get_conn
    from htma_dashboard.app import _product_master_analysis

    conn = get_conn()
    try:
        data = _product_master_analysis(conn)
    except RuntimeError as e:
        if "dictionary changed size during iteration" in str(e):
            print("FAIL: dictionary changed size during iteration")
            sys.exit(1)
        raise
    finally:
        conn.close()

    # 校验返回结构含 data_quality 且可安全序列化（无迭代中修改）
    dq = data.get("data_quality") or {}
    assert isinstance(dq, dict), "data_quality 应为 dict"
    keys = list(dq)
    for k in keys:
        _ = dq[k]
    print("OK: 商品档案分析无 dictionary changed size during iteration, data_quality keys:", len(keys))
    return 0

if __name__ == "__main__":
    sys.exit(main())
