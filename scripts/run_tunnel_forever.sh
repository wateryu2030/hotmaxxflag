#!/bin/bash
# 供 launchd 调用的隧道脚本：从项目根目录的 .tunnel-token 读取 Token，防睡眠常驻
# 由 install_launchd_htma.sh 安装为后台服务，关掉终端也会继续跑

set -e
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

TOKEN_FILE="${1:-$(pwd)/.tunnel-token}"
if [ ! -f "$TOKEN_FILE" ]; then
  echo "Token 文件不存在: $TOKEN_FILE" >&2
  echo "请创建并写入 Cloudflare 隧道 Token，或运行: bash scripts/install_launchd_htma.sh" >&2
  exit 1
fi
TOKEN=$(cat "$TOKEN_FILE" | tr -d '\n\r ')
if [ -z "$TOKEN" ]; then
  echo "Token 文件为空: $TOKEN_FILE" >&2
  exit 1
fi

# 等看板先起来（launchd 同时启动两个服务时可能有时序问题）
for i in 1 2 3 4 5 6 7 8 9 10; do
  lsof -i :5002 >/dev/null 2>&1 && break
  sleep 1
done

exec caffeinate -s -i -- cloudflared tunnel run --token "$TOKEN"
