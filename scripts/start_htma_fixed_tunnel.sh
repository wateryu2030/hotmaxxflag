#!/bin/bash
# 启动看板 + Cloudflare 正式隧道（固定外网链接，适合发给同事长期用）
# 使用前请先按 docs/固定外网链接-发给同事长期访问.md 完成：tunnel login、tunnel create、DNS、config.yml

set -e
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

CONFIG="${HOME}/.cloudflared/config.yml"
if [ ! -f "$CONFIG" ]; then
  echo "未找到配置文件: $CONFIG"
  echo "请先按 docs/固定外网链接-发给同事长期访问.md 完成隧道创建并写好 config.yml"
  exit 1
fi

# 释放 5002
pid=$(lsof -ti :5002 2>/dev/null)
if [ -n "$pid" ]; then
  echo "释放端口 5002（进程 $pid）..."
  kill -9 $pid 2>/dev/null
  sleep 1
fi

trap 'kill $(jobs -p) 2>/dev/null' EXIT INT TERM

echo "启动看板（127.0.0.1:5002）..."
bash scripts/start_htma.sh &
sleep 4
if ! lsof -i :5002 >/dev/null 2>&1; then
  echo "看板启动失败"
  exit 1
fi

echo "启动固定隧道（外网链接不变，见你在 Cloudflare DNS 里配置的域名）..."
cloudflared tunnel --config "$CONFIG" run htma-dashboard
