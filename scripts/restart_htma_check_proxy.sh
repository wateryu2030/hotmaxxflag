#!/bin/bash
# 重启看板服务并做代理自检：先结束占用 5002 的进程，再以无代理环境启动，避免 ERR_PROXY_CONNECTION_FAILED
# 用法: bash scripts/restart_htma_check_proxy.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

PORT=5002
# 结束已在监听 5002 的进程
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -ti :$PORT 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "正在结束占用端口 $PORT 的进程: $PIDS"
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
    sleep 2
  fi
fi

echo "正在启动看板服务..."
bash scripts/start_htma.sh &
sleep 3

# 自检：端口是否在监听
if command -v lsof >/dev/null 2>&1; then
  if lsof -i :$PORT >/dev/null 2>&1; then
    echo ""
    echo "服务已启动: http://127.0.0.1:$PORT"
    echo "若浏览器仍报「未连接到互联网 / ERR_PROXY_CONNECTION_FAILED」，请："
    echo "  1. 在系统或浏览器代理设置中，将 127.0.0.1、localhost 设为「不使用代理」；或"
    echo "  2. 暂时关闭代理后刷新页面。"
  else
    echo "警告: 端口 $PORT 未监听，请检查启动日志。"
  fi
fi
