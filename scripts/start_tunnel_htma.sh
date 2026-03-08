#!/usr/bin/env bash
# 启动或重启 Cloudflare 隧道，使 https://htma.greatagain.com.cn 可访问
# 用法: bash scripts/start_tunnel_htma.sh
# 先结束已有 cloudflared，再以后台方式启动（需项目根目录有 .tunnel-token 或传入 CLOUDFLARE_TUNNEL_TOKEN）

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOKEN_FILE="$ROOT/.tunnel-token"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "=============================================="
echo "Cloudflare 隧道 → https://htma.greatagain.com.cn"
echo "=============================================="

# 结束已有 cloudflared（避免重复或断线后僵死）
if pgrep -x cloudflared >/dev/null 2>&1; then
  echo "[1] 结束已有 cloudflared 进程..."
  pkill -x cloudflared 2>/dev/null || true
  sleep 2
  if pgrep -x cloudflared >/dev/null 2>&1; then
    echo "  无法结束（可能需本机终端执行）: pkill -x cloudflared"
    echo "  或在「活动监视器」中搜索 cloudflared 并结束进程后重试。"
  fi
fi

# 获取 Token
TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -f "$TOKEN_FILE" ]; then
  TOKEN=$(cat "$TOKEN_FILE" | tr -d '\n\r ')
fi
if [ -z "$TOKEN" ]; then
  echo "[FAIL] 未找到隧道 Token。请任选其一："
  echo "  1. 在项目根目录创建 .tunnel-token，内容为一行 Cloudflare 隧道 Token"
  echo "  2. 或执行: export CLOUDFLARE_TUNNEL_TOKEN='eyJ...' ; bash scripts/start_tunnel_htma.sh"
  echo "  Token 获取: https://one.dash.cloudflare.com → 网络 → 隧道 → 对应隧道 → 复制「使用令牌运行」"
  exit 1
fi

# 确保看板在跑（隧道会转发到 5002）
if ! lsof -i :5002 >/dev/null 2>&1; then
  echo "[提示] 端口 5002 未监听，请先启动看板: bash scripts/deploy_and_verify_labor.sh 或 launchctl load ~/Library/LaunchAgents/com.htma.dashboard.plist"
fi

echo "[2] 启动 cloudflared 隧道（后台）..."
cd "$ROOT"
mkdir -p logs
nohup env CLOUDFLARE_TUNNEL_TOKEN="$TOKEN" bash scripts/run_tunnel_with_token.sh > logs/tunnel.out.log 2> logs/tunnel.err.log &
sleep 3
if pgrep -x cloudflared >/dev/null 2>&1; then
  echo "  隧道已启动。稍等几秒后访问: https://htma.greatagain.com.cn"
  echo "  日志: tail -f $ROOT/logs/tunnel.err.log"
else
  echo "  启动可能失败，请查看: tail -20 $ROOT/logs/tunnel.err.log"
  exit 1
fi
