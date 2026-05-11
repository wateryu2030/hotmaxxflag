#!/usr/bin/env bash
# 部署后：安装依赖 → 重启看板（及隧道）→ 自动化验证网页可加载数据链路
# 用法（项目根）: bash scripts/htma_web_deploy_restart_verify.sh
# 环境变量:
#   HTMA_PUBLIC_URL  默认 https://htma.greatagain.com.cn
#   HTMA_SKIP_UNITTEST      设为 1 则跳过本机 Flask KPI 契约测试
#   HTMA_SKIP_TUNNEL        设为 1 则不 reload com.htma.tunnel
#   HTMA_RUN_MOBILE_VERIFY  设为 1 才跑小程序 API 路由探测（默认不跑，专注网页）
#   HTMA_SKIP_PUBLIC_VERIFY 设为 1 则跳过公网 health + 公网 static（隧道/外网不可达时避免长时间卡住）
#   HTMA_SKIP_STORE_VERIFY 设为 1 则跳过 6b（verify_web_session_store_apis，无飞书绑定/测试门店时可能失败）
set -euo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ROOT/.env" 2>/dev/null || true
  set +a
fi
PUBLIC="${HTMA_PUBLIC_URL:-https://htma.greatagain.com.cn}"
PUBLIC="${PUBLIC%/}"
LOCAL="http://127.0.0.1:5002"
TUN_PLIST="${HOME}/Library/LaunchAgents/com.htma.tunnel.plist"
LOG="$ROOT/logs/htma_web_deploy_restart_verify.log"
mkdir -p "$ROOT/logs"

_log() { echo "$(date -Iseconds) $*" | tee -a "$LOG"; }

_log "=== 1) pip install ==="
if [ -x "$ROOT/.venv/bin/pip" ]; then
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/htma_dashboard/requirements.txt"
else
  _log "WARN: 无 .venv/bin/pip，跳过 pip"
fi

_log "=== 2) 重启看板 ==="
bash "$ROOT/scripts/restart_htma_dashboard.sh"

if [ "${HTMA_SKIP_TUNNEL:-0}" != "1" ] && [ -f "$TUN_PLIST" ]; then
  _log "=== 3) reload Cloudflare 隧道 ==="
  launchctl unload "$TUN_PLIST" 2>/dev/null || true
  sleep 2
  launchctl load "$TUN_PLIST" 2>/dev/null || _log "WARN: tunnel load 失败"
  sleep 5
else
  _log "=== 3) 跳过隧道（无 plist 或 HTMA_SKIP_TUNNEL=1）==="
fi

wait_health() {
  local base="$1" label="$2"
  local i
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 15 20; do
    if curl -sf --connect-timeout 3 --max-time 8 "$base/api/health" | grep -qE '"status"[[:space:]]*:[[:space:]]*"ok"'; then
      _log "OK $label /api/health (${i}s)"
      return 0
    fi
    sleep 1
  done
  _log "FAIL $label /api/health"
  return 1
}

_log "=== 4) 健康检查 ==="
wait_health "$LOCAL" "本机" || exit 1
if [ "${HTMA_SKIP_PUBLIC_VERIFY:-0}" = "1" ]; then
  _log "跳过公网 health（HTMA_SKIP_PUBLIC_VERIFY=1）"
else
  wait_health "$PUBLIC" "公网" || exit 1
fi

_log "=== 5) 静态看板页（含带 Cookie 的数据请求封装）==="
# 大 HTML 放变量可能截断，写入临时文件再 grep
BASES=("$LOCAL")
if [ "${HTMA_SKIP_PUBLIC_VERIFY:-0}" != "1" ]; then
  BASES+=("$PUBLIC")
fi
for base in "${BASES[@]}"; do
  tmp="$(mktemp)"
  code="$(curl -sS -o "$tmp" -w "%{http_code}" --connect-timeout 12 --max-time 35 "$base/static/index.html" 2>/dev/null || echo "000")"
  if [ "$code" != "200" ]; then
    rm -f "$tmp"
    _log "FAIL: $base/static/index.html HTTP $code"
    exit 1
  fi
  if ! grep -q "dashboardFetch" "$tmp"; then
    rm -f "$tmp"
    _log "FAIL: $base/static/index.html 未包含 dashboardFetch（可能未部署最新静态文件）"
    exit 1
  fi
  rm -f "$tmp"
  _log "OK $base/static/index.html 含 dashboardFetch (HTTP $code)"
done

_log "=== 6) 数据接口烟测（本机 Flask test_client，不关鉴权时公网无法无 Cookie 调 KPI）==="
if [ "${HTMA_SKIP_UNITTEST:-0}" != "1" ] && [ -x "$ROOT/.venv/bin/python3" ]; then
  HTMA_UNITTEST_DISABLE_AUTH=1 HTMA_SKIP_MOBILE_JWT=1 HTMA_DISABLE_APSCHEDULER=1 \
    "$ROOT/.venv/bin/python3" -m unittest tests.test_api_contract.TestApiContract.test_kpi_200 -v 2>&1 | tee -a "$LOG"
  if [ "${HTMA_SKIP_STORE_VERIFY:-0}" = "1" ]; then
    _log "=== 6b) 跳过（HTMA_SKIP_STORE_VERIFY=1）==="
  else
    _log "=== 6b) 会话门店与多接口同店（HTMA_VERIFY_AUTO=1：从 sale 表取店+模拟飞书绑定；亦可手动设 OPEN_ID+STORE_ID）==="
    if HTMA_DISABLE_APSCHEDULER=1 HTMA_SKIP_MOBILE_JWT=1 HTMA_VERIFY_AUTO=1 \
      "$ROOT/.venv/bin/python3" "$ROOT/scripts/verify_web_session_store_apis.py" 2>&1 | tee -a "$LOG"; then
      _log "OK 6b 会话门店校验"
    else
      _log "WARN: 6b 未通过（无绑定或库无 sale 店时可设 HTMA_SKIP_STORE_VERIFY=1 跳过）。看板已重启，静态页已校验。"
    fi
  fi
else
  _log "跳过 unittest（HTMA_SKIP_UNITTEST=1 或无 .venv）"
fi

_log "=== 7) 可选：Mobile 路由（设 HTMA_RUN_MOBILE_VERIFY=1 才执行）==="
if [ "${HTMA_RUN_MOBILE_VERIFY:-0}" = "1" ]; then
  BASE_URL="$PUBLIC" bash "$ROOT/scripts/verify_mobile_api_routes.sh" 2>&1 | tee -a "$LOG"
else
  _log "跳过（网页部署无需小程序路由检查）"
fi

_log "=== 全部通过。网页请飞书登录后强制刷新(Cmd+Shift+R)；会话失效会自动跳登录页。==="
