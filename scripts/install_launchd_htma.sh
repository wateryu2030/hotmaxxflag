#!/bin/bash
# 将好特卖看板 + Cloudflare 隧道安装为 macOS 后台服务，关掉终端也继续跑
# 执行: bash scripts/install_launchd_htma.sh
# 首次运行需在项目根目录创建 .tunnel-token 并写入隧道 Token（一行）

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
DASHBOARD_PLIST="com.htma.dashboard.plist"
TUNNEL_PLIST="com.htma.tunnel.plist"
TOKEN_FILE="$PROJECT_ROOT/.tunnel-token"

mkdir -p "$AGENTS"

# 检查 Token 文件
if [ ! -f "$TOKEN_FILE" ]; then
  echo "=============================================="
  echo "未找到隧道 Token 文件。请先创建："
  echo "  $TOKEN_FILE"
  echo "内容为一行：Cloudflare 隧道 Token（从 one.dash.cloudflare.com 复制）。"
  echo "创建后重新执行: bash scripts/install_launchd_htma.sh"
  echo "=============================================="
  exit 1
fi

# 先卸载旧服务（若存在）
launchctl unload "$AGENTS/$DASHBOARD_PLIST" 2>/dev/null || true
launchctl unload "$AGENTS/$TUNNEL_PLIST" 2>/dev/null || true

# 看板服务
cat > "$AGENTS/$DASHBOARD_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.dashboard</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>ProgramArguments</key>
  <array>
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

# 隧道服务
cat > "$AGENTS/$TUNNEL_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.tunnel</string>
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

# 加载服务
launchctl load "$AGENTS/$DASHBOARD_PLIST"
launchctl load "$AGENTS/$TUNNEL_PLIST"

echo "已安装并启动后台服务（关掉终端也会继续跑）。"
echo "  看板: com.htma.dashboard  → http://127.0.0.1:5002"
echo "  隧道: com.htma.tunnel     → https://htma.greatagain.com.cn"
echo "日志: $PROJECT_ROOT/logs/"
echo ""
echo "常用命令："
echo "  查看状态: launchctl list | grep com.htma"
echo "  停止隧道: launchctl unload $AGENTS/$TUNNEL_PLIST"
echo "  停止看板: launchctl unload $AGENTS/$DASHBOARD_PLIST"
echo "  再次启动: launchctl load $AGENTS/$DASHBOARD_PLIST && launchctl load $AGENTS/$TUNNEL_PLIST"
