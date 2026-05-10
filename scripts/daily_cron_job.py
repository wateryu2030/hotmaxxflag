#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日自动化（精简版）：规则引擎预警 + AI 经营快报。
分类日表刷新已移至每晚 23:00 的 nightly_business_job.py，避免与 23 点任务重复。

建议：
  - 主方案：仅安装 nightly（23:00 含刷新+预警+快报），卸载本 LaunchAgent。
  - 若仍保留本任务：可保持凌晨 2 点作二次快报补跑（数据已在 23 点刷新）。

Linux crontab 示例（仅预警+快报）: 0 2 * * * cd /path/to/repo && .venv/bin/python3 scripts/daily_cron_job.py
环境变量：HTMA_CRON_WEBHOOK_URL、FEISHU_WEBHOOK_URL、HTMA_STORE_ID 等（见 htma_cron_util）
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HTMA = os.path.join(_ROOT, "htma_dashboard")
if _HTMA not in sys.path:
    sys.path.insert(0, _HTMA)
_SCRIPTS = os.path.abspath(os.path.dirname(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from htma_cron_util import cron_run_step  # noqa: E402


def main() -> int:
    os.environ.setdefault("HTMA_SKIP_MOBILE_JWT", "1")
    from alert_engine import check_all_rules
    from ai_advisor import generate_daily_summary

    cron_run_step("check_all_rules", lambda: check_all_rules())
    cron_run_step("generate_daily_summary", lambda: generate_daily_summary())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("daily_cron_job fatal:", e, file=sys.stderr)
        raise SystemExit(1)
