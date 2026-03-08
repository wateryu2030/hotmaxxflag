#!/usr/bin/env bash
# OpenClaw 自动化：检查并重启看板服务，验证 5002 与 /api/health
# 执行: bash scripts/openclaw_restart_dashboard_and_verify.sh
# 在项目根目录执行；可选参数: --check-only 仅检查不重启
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECK_ONLY=false
for a in "$@"; do
  if [ "$a" = "--check-only" ]; then CHECK_ONLY=true; elif [ -d "$a" ]; then ROOT="$a"; fi
done
cd "$ROOT"
AGENTS="$HOME/Library/LaunchAgents"
DASHBOARD_PLIST="com.htma.dashboard.plist"
PORT=5002

echo "=============================================="
echo "OpenClaw: 看板服务检查与重启"
echo "=============================================="
echo "项目根: $ROOT"
echo ""

# 0. 可选：仅检查当前状态
if [ "$CHECK_ONLY" = true ]; then
  echo ">>> 仅检查（--check-only）"
  pid=$(lsof -ti :$PORT 2>/dev/null || true)
  if [ -n "$pid" ]; then
    echo "    端口 $PORT: 进程 $pid 占用"
  else
    echo "    端口 $PORT: 无进程"
  fi
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://127.0.0.1:$PORT/api/health" 2>/dev/null) || echo "000"
  echo "    /api/health: HTTP $CODE"
  if [ "$CODE" = "200" ]; then
    echo "    看板正常"
    exit 0
  else
    echo "    看板未就绪或未启动"
    exit 1
  fi
fi

# 1. 释放 5002（避免旧进程占坑）
echo ">>> 1. 释放端口 $PORT"
pid=$(lsof -ti :$PORT 2>/dev/null || true)
if [ -n "$pid" ]; then
  echo "    结束进程: $pid"
  kill -9 $pid 2>/dev/null || true
  sleep 2
else
  echo "    端口无占用"
fi
echo ""

# 2. 重启看板（launchd）
echo ">>> 2. 重启看板 (launchd)"
launchctl unload "$AGENTS/$DASHBOARD_PLIST" 2>/dev/null || true
sleep 2
launchctl load "$AGENTS/$DASHBOARD_PLIST" 2>/dev/null || true
echo "    已执行 unload + load"
echo ""

# 3. 等待就绪（最多 40 秒）
echo ">>> 3. 等待看板就绪（最多 40 秒）"
READY=""
for i in $(seq 1 40); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "http://127.0.0.1:$PORT/api/health" 2>/dev/null) || true
  [ -z "$CODE" ] && CODE="000"
  if [ "$CODE" = "200" ]; then
    READY=1
    echo "    就绪 (${i}s)  /api/health -> 200"
    break
  fi
  [ $((i % 5)) -eq 0 ] && echo "    ${i}s..."
  [ $i -eq 40 ] && echo "    超时: 40 秒内未响应"
  sleep 1
done
echo ""

# 4. 验证并输出结果
CODE_ROOT=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://127.0.0.1:$PORT/" 2>/dev/null) || echo "000"
CODE_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://127.0.0.1:$PORT/api/health" 2>/dev/null) || echo "000"
echo ">>> 4. 验证"
echo "    /         -> HTTP $CODE_ROOT"
echo "    /api/health -> HTTP $CODE_HEALTH"
echo ""

if [ "$CODE_HEALTH" = "200" ]; then
  echo "=============================================="
  echo "看板已就绪"
  echo "=============================================="
  echo "本机: http://127.0.0.1:$PORT/"
  echo "日志: $ROOT/logs/"
  exit 0
else
  echo "=============================================="
  echo "看板未就绪 (health=$CODE_HEALTH)"
  echo "=============================================="
  echo "请查看: tail -30 $ROOT/logs/dashboard.err.log"
  if [ -f "$ROOT/logs/dashboard.err.log" ]; then
    echo "--- 最后 15 行 ---"
    tail -15 "$ROOT/logs/dashboard.err.log" | sed 's/^/  /'
  fi
  echo "若 launchd 反复启动失败，可改用手动启动: cd $ROOT && .venv/bin/python htma_dashboard/app.py"
  exit 1
fi
