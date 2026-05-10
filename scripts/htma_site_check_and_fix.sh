#!/usr/bin/env bash
# 自动化检查 htma 公网与本机看板，异常时尝试修复（重启看板 / 隧道）。
# 用法（项目根）:
#   bash scripts/htma_site_check_and_fix.sh
# 环境变量:
#   HTMA_PUBLIC_URL   默认 https://htma.greatagain.com.cn
#   HTMA_CHECK_NO_FIX  设为 1 则只检查不执行修复
#   HTMA_SKIP_MOBILE_VERIFY 设为 1 则跳过 mobile 路由探测
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
NO_FIX="${HTMA_CHECK_NO_FIX:-0}"
SKIP_MOBILE="${HTMA_SKIP_MOBILE_VERIFY:-0}"

DASH_PLIST="${HOME}/Library/LaunchAgents/com.htma.dashboard.plist"
TUN_PLIST="${HOME}/Library/LaunchAgents/com.htma.tunnel.plist"
LOG="$ROOT/logs/htma_site_check_and_fix.log"
mkdir -p "$ROOT/logs"

http_code() {
  local url="$1"
  curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 15 --max-time 25 "$url" 2>/dev/null || echo "000"
}

health_body_ok() {
  local url="$1"
  local body
  body="$(curl -sS --connect-timeout 10 --max-time 20 "$url" 2>/dev/null || true)"
  echo "$body" | grep -qE '"status"[[:space:]]*:[[:space:]]*"ok"'
}

_log() {
  echo "$(date -Iseconds) $*" | tee -a "$LOG"
}

_log "=== HTMA 站点检查 PUBLIC=$PUBLIC ==="

P_HEALTH="$(http_code "$PUBLIC/api/health")"
_log "公网 /api/health -> HTTP $P_HEALTH"

OK=1
if [ "$P_HEALTH" != "200" ]; then
  OK=0
elif ! health_body_ok "$PUBLIC/api/health"; then
  _log "公网 health 200 但正文非 ok（可能 DB 异常）"
  OK=0
fi

L_HEALTH="000"
if [ "$OK" != "1" ]; then
  L_HEALTH="$(http_code "$LOCAL/api/health")"
  _log "本机 /api/health -> HTTP $L_HEALTH"
fi

attempt_fix() {
  local phase="$1"
  _log ">>> 尝试修复: $phase"
  if [ "$NO_FIX" = "1" ]; then
    _log "已设置 HTMA_CHECK_NO_FIX=1，跳过修复"
    return 1
  fi
  case "$phase" in
    dashboard)
      bash "$ROOT/scripts/restart_htma_dashboard.sh" || true
      sleep 5
      ;;
    tunnel)
      if [ -f "$TUN_PLIST" ]; then
        launchctl unload "$TUN_PLIST" 2>/dev/null || true
        sleep 3
        launchctl load "$TUN_PLIST" 2>/dev/null || _log "launchctl load 隧道失败，请手动检查"
      elif [ -f "$ROOT/.tunnel-token" ] || [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
        bash "$ROOT/scripts/start_tunnel_htma.sh" || _log "start_tunnel_htma.sh 失败，见 logs/tunnel.err.log"
      else
        _log "无 com.htma.tunnel.plist 且无 .tunnel-token，无法自动重启隧道"
      fi
      sleep 10
      ;;
    full)
      if [ -f "$ROOT/scripts/fix_and_ensure_site_ok.sh" ]; then
        bash "$ROOT/scripts/fix_and_ensure_site_ok.sh" || true
      else
        _log "未找到 fix_and_ensure_site_ok.sh"
      fi
      sleep 8
      ;;
  esac
}

if [ "$OK" != "1" ]; then
  _log "公网异常，开始自动修复流程…"
  # 本机看板挂了 → 先拉看板
  if [ "$L_HEALTH" != "200" ]; then
    attempt_fix dashboard
  fi
  P_HEALTH="$(http_code "$PUBLIC/api/health")"
  _log "修复后公网 /api/health -> HTTP $P_HEALTH"
  if [ "$P_HEALTH" = "200" ] && health_body_ok "$PUBLIC/api/health"; then
    OK=1
  fi
  # 本机已好但公网仍不行 → 多为隧道 / 边缘
  if [ "$OK" != "1" ]; then
    L_HEALTH="$(http_code "$LOCAL/api/health")"
    if [ "$L_HEALTH" = "200" ]; then
      attempt_fix tunnel
      P_HEALTH="$(http_code "$PUBLIC/api/health")"
      _log "隧道修复后公网 /api/health -> HTTP $P_HEALTH"
      if [ "$P_HEALTH" = "200" ] && health_body_ok "$PUBLIC/api/health"; then
        OK=1
      fi
    fi
  fi
  # 仍失败 → 重装 launchd（与 fix_and_ensure_site_ok 一致）
  if [ "$OK" != "1" ] && [ -f "$ROOT/scripts/install_launchd_htma.sh" ]; then
    attempt_fix full
    P_HEALTH="$(http_code "$PUBLIC/api/health")"
    _log "全量修复后公网 /api/health -> HTTP $P_HEALTH"
    if [ "$P_HEALTH" = "200" ] && health_body_ok "$PUBLIC/api/health"; then
      OK=1
    fi
  fi
fi

P_ROOT="$(http_code "$PUBLIC/")"
_log "公网 / -> HTTP $P_ROOT"

if [ "$OK" = "1" ] && [ "$SKIP_MOBILE" != "1" ]; then
  _log "=== Mobile API 路由探测（无 JWT 时 401 正常）==="
  BASE_URL="$PUBLIC" bash "$ROOT/scripts/verify_mobile_api_routes.sh" || OK=0
fi

if [ "$OK" = "1" ]; then
  _log "=== 结果: OK ==="
  exit 0
fi

_log "=== 结果: 仍异常。请查看: ==="
_log "  tail -80 $ROOT/logs/dashboard.err.log"
_log "  tail -40 /tmp/com.htma.tunnel.err.log  # 若使用 launchd 隧道"
_log "  tail -40 $ROOT/logs/tunnel.err.log"
exit 1
