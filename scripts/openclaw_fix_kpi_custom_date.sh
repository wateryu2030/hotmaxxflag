#!/usr/bin/env bash
# OpenClaw 自动化：重启看板 + 在浏览器中登录后自动校验自定义日期是否生效
# 用法：
#   bash scripts/openclaw_fix_kpi_custom_date.sh
#   bash scripts/openclaw_fix_kpi_custom_date.sh https://htma.greatagain.com.cn
# 会先重启 5002 看板，再打开浏览器；请在 60 秒内完成登录，脚本将自动填写自定义区间并点击查询、校验结果。
set -e
BASE_URL="${1:-http://127.0.0.1:5002}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=============================================="
echo "OpenClaw：重启看板并校验 KPI 自定义日期"
echo "=============================================="
if [[ "$BASE_URL" =~ ^https?://(127\.0\.0\.1|localhost)(:[0-9]+)? ]]; then
  echo "[1/2] 重启本地看板（释放 5002，启动最新代码）..."
  pid=$(lsof -ti :5002 2>/dev/null || true)
  if [ -n "$pid" ]; then
    echo "  结束进程: $pid"
    kill -9 $pid 2>/dev/null || true
  fi
  pkill -f "htma_dashboard/app.py" 2>/dev/null || true
  sleep 2
  cd "$ROOT/htma_dashboard"
  nohup ../.venv/bin/python app.py >> /tmp/htma_dashboard.log 2>&1 &
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:5002/api/health" 2>/dev/null | grep -q 200; then
      echo "  看板已就绪"
      break
    fi
    sleep 1
  done
  echo ""
fi
echo "[2/2] 打开浏览器执行自定义日期校验（60 秒内请完成登录）..."
export OPENCLAW_WAIT_LOGIN=60
node "$SCRIPT_DIR/openclaw_check_kpi_custom_date.mjs" "$BASE_URL"
echo ""
echo "完成。看板: $BASE_URL"
