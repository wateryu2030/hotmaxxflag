#!/bin/bash
# 用 Cloudflare 控制台给的 Token 运行隧道（不需要 cert.pem / tunnel login）
# 使用: 先在本机启动看板，再执行: bash scripts/run_tunnel_with_token.sh <你的token>
# 或: export CLOUDFLARE_TUNNEL_TOKEN="eyJ..." ; bash scripts/run_tunnel_with_token.sh

set -e
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

TOKEN="${1:-$CLOUDFLARE_TUNNEL_TOKEN}"
if [ -z "$TOKEN" ]; then
  echo "用法: bash scripts/run_tunnel_with_token.sh <Cloudflare隧道Token>"
  echo "或: export CLOUDFLARE_TUNNEL_TOKEN='eyJ...' ; bash scripts/run_tunnel_with_token.sh"
  echo ""
  echo "Token 获取: 登录 https://one.dash.cloudflare.com → 网络 → 隧道 → 创建隧道"
  echo "创建后复制「安装命令」里的 --token 后面的整段。"
  exit 1
fi

# 确保看板在跑
if ! lsof -i :5002 >/dev/null 2>&1; then
  echo "端口 5002 无服务。请先在一个终端运行: bash 启动好特卖看板.command"
  echo "或: bash scripts/start_htma.sh"
  exit 1
fi

echo "正在启动隧道（外网地址: https://htma.greatagain.com.cn）..."
echo "已启用防睡眠（锁屏/息屏不影响外网访问）。关闭本窗口将断开隧道。"
# -s 防止系统睡眠 -i 防止空闲睡眠，锁屏后隧道不断线
exec caffeinate -s -i -- cloudflared tunnel run --token "$TOKEN"
