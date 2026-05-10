#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用项目根目录 .env 中的 MYSQL_* 连接数据库，执行 Phase 2 建表脚本
scripts/33_alert_events_daily_ai_reports.sql（幂等：CREATE TABLE IF NOT EXISTS）。

用法（在项目根目录）:
  .venv/bin/python3 scripts/apply_33_alert_ai_tables.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HTM = os.path.join(_ROOT, "htma_dashboard")
if _HTM not in sys.path:
    sys.path.insert(0, _HTM)

from db_config import DB_CONFIG, get_conn  # noqa: E402


def main() -> int:
    sql_path = os.path.join(_ROOT, "scripts", "33_alert_events_daily_ai_reports.sql")
    if not os.path.isfile(sql_path):
        print("missing:", sql_path, file=sys.stderr)
        return 2
    with open(sql_path, "r", encoding="utf-8") as f:
        raw = f.read()
    parts = []
    buf = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        if s.upper().startswith("USE "):
            continue
        buf.append(line)
        if s.endswith(";"):
            stmt = "\n".join(buf).strip()
            buf = []
            if stmt:
                parts.append(stmt.rstrip(";").strip())
    if buf:
        stmt = "\n".join(buf).strip()
        if stmt:
            parts.append(stmt.rstrip(";").strip())

    print("数据库:", DB_CONFIG.get("host"), DB_CONFIG.get("database"))
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("USE `%s`" % str(DB_CONFIG["database"]).replace("`", ""))
        for stmt in parts:
            cur.execute(stmt)
            print("OK:", stmt.split()[0:3], "...")
        conn.commit()
    finally:
        conn.close()
    print("完成: alert_events / daily_ai_reports（已存在则跳过）")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("apply_33 失败:", e, file=sys.stderr)
        raise SystemExit(1)
