#!/usr/bin/env bash
# 重启好特卖看板（5002）。请在「本机终端 / 访达双击 .command」执行，不依赖 Cursor 沙箱。
# 若已安装 launchd（install_launchd_htma.sh）：先释放端口再 unload/load，由系统拉起进程。
# 若未安装 launchd：直接 nohup 启动 start_htma.sh。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.htma.dashboard.plist"
LOG="$ROOT/logs/restart_htma_dashboard.log"

mkdir -p "$ROOT/logs"
_log() { echo "$@" | /usr/bin/tee -a "$LOG"; }
_log "======== $(date -Iseconds) restart_htma_dashboard ========"

free_5002() {
  if lsof -ti:5002 >/dev/null 2>&1; then
    _log "Killing process(es) on :5002"
    for pid in $(lsof -ti:5002 2>/dev/null); do
      kill -9 "$pid" 2>/dev/null || true
    done
    sleep 2
  else
    _log "Port 5002 already free"
  fi
}

wait_health() {
  local i
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if curl -sf --connect-timeout 2 "http://127.0.0.1:5002/api/health" >/dev/null; then
      _log "OK /api/health (after ${i}s)"
      return 0
    fi
    sleep 1
  done
  _log "WARN: /api/health not ready after 20s; see dashboard.err.log"
  return 1
}

free_5002

if [ -f "$PLIST" ]; then
  _log "launchctl unload com.htma.dashboard"
  launchctl unload "$PLIST" 2>/dev/null || true
  sleep 2
  _log "launchctl load com.htma.dashboard"
  launchctl load "$PLIST"
  sleep 6
else
  _log "No $PLIST — starting via nohup start_htma.sh"
  cd "$ROOT"
  nohup bash "$ROOT/scripts/start_htma.sh" >>"$ROOT/logs/dashboard_restart.log" 2>&1 &
  _log "nohup PID $!"
  sleep 4
fi

wait_health || true
_log "Done. Log: $LOG"
_log "Also: $ROOT/logs/dashboard.err.log"
