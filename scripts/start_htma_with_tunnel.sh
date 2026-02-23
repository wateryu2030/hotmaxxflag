#!/bin/bash
# 好特卖看板 + 外网隧道（Cloudflare）一并启动，供桌面图标或终端执行
# 关闭本窗口时会同时停止看板与隧道

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$PWD"

# 确保能找到 cloudflared（双击 .command 时 PATH 可能不含 Homebrew）
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
CLOUDFLARED=""
for p in cloudflared /opt/homebrew/bin/cloudflared /usr/local/bin/cloudflared; do
  if command -v "$p" >/dev/null 2>&1; then
    CLOUDFLARED="$p"
    break
  fi
done
if [ -z "$CLOUDFLARED" ]; then
  echo "未找到 cloudflared，请先安装: brew install cloudflared"
  exit 1
fi

# 释放 5002 端口（可能是上次未关的进程或 Docker）
free_port() {
  local pid
  pid=$(lsof -ti :5002 2>/dev/null)
  if [ -n "$pid" ]; then
    echo "正在释放端口 5002（进程 $pid）..."
    kill -9 $pid 2>/dev/null || true
    sleep 1
  fi
}

free_port

# 关闭本窗口时同时结束后台看板进程
trap 'echo "正在停止看板..."; kill $(jobs -p) 2>/dev/null; exit 0' EXIT INT TERM

# 后台启动看板
echo "正在启动好特卖看板（端口 5002）..."
bash scripts/start_htma.sh &
APP_PID=$!
sleep 4

# 检查看板是否起来
if ! lsof -i :5002 >/dev/null 2>&1; then
  echo "看板启动失败，请检查上方日志。"
  kill $APP_PID 2>/dev/null
  exit 1
fi

# 外网隧道（会打印外网链接，可复制到手机/外网浏览器）
echo "=============================================="
echo "  正在启动外网隧道，稍候会显示外网访问地址"
echo "  格式: https://xxxx.trycloudflare.com"
echo "  请复制该链接，在手机或外网电脑浏览器打开"
echo "=============================================="
echo ""
"$CLOUDFLARED" tunnel --url http://127.0.0.1:5002
