#!/bin/bash
# OpenClaw 自动化：比价功能可用性检查（自检脚本 + 日志）
# 由 launchd 每日执行，或手动：bash scripts/run_price_compare_healthcheck.sh
# 日志：logs/price_compare_healthcheck.log（追加）、.out.log / .err.log（launchd 重定向）

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/price_compare_healthcheck.log"

mkdir -p "$LOG_DIR"
echo "" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ========== 比价可用性检查 ==========" >> "$LOG_FILE"
bash "$SCRIPT_DIR/run_selfserve_price_compare_debug.sh" 2>&1 | tee -a "$LOG_FILE"
exit 0
