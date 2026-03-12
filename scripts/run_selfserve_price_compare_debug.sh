#!/bin/bash
# 货盘比价 OpenClaw 百度 Skill 自检（与 launchd 看板同 PATH）
# 用法: bash scripts/run_selfserve_price_compare_debug.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PATH="${HOME}/Library/pnpm:${HOME}/.npm-global/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"
cd "$ROOT"
[ -f .env ] && set -a && . ./.env 2>/dev/null && set +a
exec python3 scripts/selfserve_price_compare_debug.py
