#!/usr/bin/env bash
# OpenClaw 可调用的京东比价入口
# 用法: ./run.sh [--limit N] [--dry-run]
set -e
cd "$(dirname "$0")/../../.."
source .venv/bin/activate 2>/dev/null || true
exec python scripts/htma_price_scrape_jd.py "$@"
