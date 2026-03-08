#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清空好特卖看板历史数据，便于重新上传。
会 TRUNCATE：销售表、库存表、毛利表、商品表、品类毛利表（若存在）。
用法: bash scripts/run_clear_data.sh  或  .venv/bin/python scripts/clear_htma_data.py --confirm
数据库配置从项目根目录 .env 的 MYSQL_* 读取。
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
    import pymysql
    print("未找到 pymysql。请用: bash scripts/run_clear_data.sh（会使用项目 .venv）", flush=True)
    sys.exit(1)


def main():
    if "--confirm" not in sys.argv and "-y" not in sys.argv:
        print("将清空：t_htma_sale、t_htma_stock、t_htma_profit、t_htma_products、t_htma_category_profit", flush=True)
        print("执行前请确认。若确定清空，请加参数: --confirm 或 -y", flush=True)
        sys.exit(0)

    conn = get_conn()
    cur = conn.cursor()
    tables = ["t_htma_sale", "t_htma_stock", "t_htma_profit", "t_htma_products", "t_htma_category_profit"]
    for t in tables:
        try:
            cur.execute(f"TRUNCATE TABLE {t}")
            print(f"已清空 {t}", flush=True)
        except Exception as e:
            if "doesn't exist" in str(e):
                print(f"跳过 {t}（表不存在）", flush=True)
            else:
                print(f"清空 {t} 失败: {e}", flush=True)
    conn.commit()
    conn.close()
    print("完成。可重新上传销售/库存/毛利 Excel。", flush=True)


if __name__ == "__main__":
    main()
