#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查 KPI 自定义周期日期范围 API 与数据完整性。
用法：在项目根目录执行 python scripts/check_kpi_date_range.py
      或指定看板 base URL：BASE_URL=https://htma.greatagain.com.cn python scripts/check_kpi_date_range.py
"""
import os
import sys
import json
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    requests = None

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:5200")
DATE_RANGE_PATH = "/api/date_range"


def main():
    base = BASE_URL.rstrip("/")
    url = base + DATE_RANGE_PATH
    print(f"检查: {url}")
    ok = True

    if requests is None:
        print("请安装 requests: pip install requests")
        sys.exit(1)

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        min_date = data.get("min_date")
        max_date = data.get("max_date")
        if not min_date or not max_date:
            print("失败: 返回缺少 min_date 或 max_date")
            ok = False
        else:
            try:
                d_min = datetime.strptime(min_date, "%Y-%m-%d").date()
                d_max = datetime.strptime(max_date, "%Y-%m-%d").date()
                if d_min > d_max:
                    print("失败: min_date 晚于 max_date")
                    ok = False
                else:
                    print(f"通过: min_date={min_date}, max_date={max_date}")
            except ValueError as e:
                print(f"失败: 日期格式无效 min_date={min_date!r} max_date={max_date!r} ({e})")
                ok = False
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        ok = False
    except json.JSONDecodeError as e:
        print(f"响应非 JSON: {e}")
        ok = False

    if not ok:
        sys.exit(1)
    print("KPI 日期范围 API 与数据检查完成。")


if __name__ == "__main__":
    main()
