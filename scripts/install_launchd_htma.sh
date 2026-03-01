#!/bin/bash
# 将好特卖看板 + Cloudflare 隧道安装为 macOS 后台服务，本机不关机即可通过 htma.greatagain.com.cn 一直访问
# 执行: bash scripts/install_launchd_htma.sh
# 有 .tunnel-token 时同时启用隧道；无 token 时只安装看板，创建 token 后执行下方提示命令即可启用隧道

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
DASHBOARD_PLIST="com.htma.dashboard.plist"
TUNNEL_PLIST="com.htma.tunnel.plist"
TOKEN_FILE="$PROJECT_ROOT/.tunnel-token"

mkdir -p "$AGENTS"

# 确保项目使用 .venv（避免系统 Python 的 externally-managed-environment）
if [ ! -f "$PROJECT_ROOT/.venv/bin/python" ]; then
  echo "未找到 .venv，正在创建并安装依赖..."
  bash "$PROJECT_ROOT/scripts/ensure_venv.sh"
fi

HAS_TOKEN=0
[ -f "$TOKEN_FILE" ] && [ -s "$TOKEN_FILE" ] && HAS_TOKEN=1

# 先卸载旧服务（若存在）
launchctl unload "$AGENTS/$DASHBOARD_PLIST" 2>/dev/null || true
launchctl unload "$AGENTS/$TUNNEL_PLIST" 2>/dev/null || true

# 看板服务（用 caffeinate 防睡眠，锁屏/息屏后仍可访问，与 run_tunnel_with_token 成功案例一致）
cat > "$AGENTS/$DASHBOARD_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.dashboard</string>
  <key>ProcessType</key>
  <string>Background</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-s</string>
    <string>-i</string>
    <string>/bin/bash</string>
    <string>$PROJECT_ROOT/scripts/start_htma.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/dashboard.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/dashboard.err.log</string>
</dict>
</plist>
EOF

# 隧道服务（锁屏后继续运行；内置 caffeinate 防止本机睡眠以保持外网可访问）
cat > "$AGENTS/$TUNNEL_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.tunnel</string>
  <key>ProcessType</key>
  <string>Background</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT_ROOT/scripts/run_tunnel_forever.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/tunnel.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/tunnel.err.log</string>
</dict>
</plist>
EOF

mkdir -p "$PROJECT_ROOT/logs"

# 加载看板（始终）；有 token 时加载隧道
launchctl load "$AGENTS/$DASHBOARD_PLIST"
if [ "$HAS_TOKEN" = "1" ]; then
  launchctl load "$AGENTS/$TUNNEL_PLIST"
  echo "已安装并启动看板 + 隧道（本机不关机即可通过 https://htma.greatagain.com.cn 一直访问）。"
  echo "  看板: com.htma.dashboard  → http://127.0.0.1:5002"
  echo "  隧道: com.htma.tunnel     → https://htma.greatagain.com.cn"
  echo "  锁屏/息屏后仍可访问；隧道会阻止本机进入睡眠以保持连接。"
else
  echo "已安装并启动看板服务（隧道未启用：未找到 .tunnel-token）。"
  echo "  看板: com.htma.dashboard  → http://127.0.0.1:5002（本机常驻）"
  echo ""
  echo "要启用外网访问 https://htma.greatagain.com.cn，请："
  echo "  1. 创建 $TOKEN_FILE，内容为一行 Cloudflare 隧道 Token（从 one.dash.cloudflare.com 复制）"
  echo "  2. 执行: launchctl load $AGENTS/$TUNNEL_PLIST"
  echo "  或重新执行: bash scripts/install_launchd_htma.sh"
fi
echo "日志: $PROJECT_ROOT/logs/"
echo ""
echo "常用命令："
echo "  查看状态: launchctl list | grep com.htma"
echo "  停止隧道: launchctl unload $AGENTS/$TUNNEL_PLIST"
echo "  停止看板: launchctl unload $AGENTS/$DASHBOARD_PLIST"
echo "  再次启动: launchctl load $AGENTS/$DASHBOARD_PLIST && launchctl load $AGENTS/$TUNNEL_PLIST"
