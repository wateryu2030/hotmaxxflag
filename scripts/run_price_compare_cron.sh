#!/bin/bash
# 定时比价任务入口：调用 batch_price_compare.py，将结果与错误写入 logs。
# 可由 launchd 每周一凌晨 2 点执行，或加入 crontab。
# 使用方式：bash scripts/run_price_compare_cron.sh  或由 install_launchd_price_compare.sh 安装的 plist 调用

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOG_DIR/price_compare_cron.log"

mkdir -p "$LOG_DIR"

# 加载 .env（HTMA_STORE_ID、PRICE_COMPARE_TOP_N 等）
if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$PROJECT_ROOT/.env" 2>/dev/null || true
  set +a
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始执行定时比价" >> "$LOG_FILE"
if [ ! -f "$PROJECT_ROOT/.venv/bin/python" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] 未找到 .venv，请先运行 scripts/ensure_venv.sh" >> "$LOG_FILE"
  exit 1
fi

cd "$PROJECT_ROOT"
if "$PROJECT_ROOT/.venv/bin/python" scripts/batch_price_compare.py >> "$LOG_FILE" 2>&1; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] 定时比价完成" >> "$LOG_FILE"
else
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] 定时比价执行失败，请查看上方日志" >> "$LOG_FILE"
  exit 1
fi
