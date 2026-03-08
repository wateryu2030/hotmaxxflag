#!/bin/bash
# 将好特卖看板 + Cloudflare 隧道安装为 macOS 后台服务，本机不关机即可通过 htma.greatagain.com.cn 一直访问
# 执行: bash scripts/install_launchd_htma.sh
# 有 .tunnel-token 时同时启用隧道；无 token 时只安装看板，创建 token 后执行下方提示命令即可启用隧道

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
KEEPAWAKE_PLIST="com.htma.keepawake.plist"
DASHBOARD_PLIST="com.htma.dashboard.plist"
TUNNEL_PLIST="com.htma.tunnel.plist"
TOKEN_FILE="$PROJECT_ROOT/.tunnel-token"

mkdir -p "$AGENTS"
mkdir -p "$PROJECT_ROOT/logs"

# 确保项目使用 .venv（避免系统 Python 的 externally-managed-environment）
if [ ! -f "$PROJECT_ROOT/.venv/bin/python" ]; then
  echo "未找到 .venv，正在创建并安装依赖..."
  bash "$PROJECT_ROOT/scripts/ensure_venv.sh"
fi

HAS_TOKEN=0
[ -f "$TOKEN_FILE" ] && [ -s "$TOKEN_FILE" ] && HAS_TOKEN=1

# 先卸载旧服务（若存在）
launchctl unload "$AGENTS/$KEEPAWAKE_PLIST" 2>/dev/null || true
launchctl unload "$AGENTS/$DASHBOARD_PLIST" 2>/dev/null || true
launchctl unload "$AGENTS/$TUNNEL_PLIST" 2>/dev/null || true

# 从 .env 读取关键变量并生成 launchd EnvironmentVariables，确保看板与飞书登录在后台能拿到配置
ENV_KEYS="HTMA_PUBLIC_URL FEISHU_APP_ID FEISHU_APP_SECRET FLASK_SECRET_KEY MYSQL_HOST MYSQL_PORT MYSQL_USER MYSQL_PASSWORD MYSQL_DATABASE HTMA_SUPER_ADMIN_OPEN_ID FEISHU_WEBHOOK_URL"
ENV_XML=""
if [ -f "$PROJECT_ROOT/.env" ]; then
  for k in $ENV_KEYS; do
    v=$(grep -m1 "^${k}=" "$PROJECT_ROOT/.env" 2>/dev/null | sed "s/^${k}=//" | tr -d '\r' | sed 's/^["'\'']//;s/["'\'']$//')
    [ -z "$v" ] && continue
    v_escaped=$(echo "$v" | sed 's/&/\&amp;/g;s/</\&lt;/g;s/>/\&gt;/g;s/"/\&quot;/g')
    ENV_XML="${ENV_XML}    <key>${k}</key>\n    <string>${v_escaped}</string>\n"
  done
fi
if [ -n "$ENV_XML" ]; then
  ENV_BLOCK="  <key>EnvironmentVariables</key>\n  <dict>\n${ENV_XML}  </dict>"
else
  ENV_BLOCK=""
fi

# 防睡眠服务（锁屏/息屏后本机功能照常执行：阻止系统睡眠，看板/隧道/定时任务才能持续运行）
cat > "$AGENTS/$KEEPAWAKE_PLIST" << KEEPAWAKEEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.keepawake</string>
  <key>ProcessType</key>
  <string>Background</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-s</string>
    <string>-i</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/keepawake.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/keepawake.err.log</string>
</dict>
</plist>
KEEPAWAKEEOF

# 看板服务（用 caffeinate 防睡眠；注入 .env 关键变量保证飞书与公网域名可用）
cat > "$AGENTS/$DASHBOARD_PLIST" << PLISTEOF
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
    <string>-c</string>
    <string>sleep 5 &amp;&amp; exec $PROJECT_ROOT/scripts/start_htma.sh</string>
  </array>
$(echo -e "$ENV_BLOCK")
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
PLISTEOF

# 隧道服务（锁屏后继续运行；caffeinate -s -i 防止本机睡眠以保持外网可访问）
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
    <string>/usr/bin/caffeinate</string>
    <string>-s</string>
    <string>-i</string>
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

# 先加载防睡眠（锁屏后本机定时任务与看板/隧道照常运行），再加载看板与隧道
launchctl load "$AGENTS/$KEEPAWAKE_PLIST"
launchctl load "$AGENTS/$DASHBOARD_PLIST"
if [ "$HAS_TOKEN" = "1" ]; then
  launchctl load "$AGENTS/$TUNNEL_PLIST"
  echo "已安装并启动：防睡眠 + 看板 + 隧道（锁屏/息屏后本机功能正常执行、外网可访问）。"
  echo "  防睡眠: com.htma.keepawake（阻止系统睡眠）"
  echo "  看板:   com.htma.dashboard  → http://127.0.0.1:5002"
  echo "  隧道:   com.htma.tunnel     → https://htma.greatagain.com.cn"
else
  echo "已安装并启动：防睡眠 + 看板（隧道未启用：未找到 .tunnel-token）。"
  echo "  防睡眠: com.htma.keepawake（锁屏后定时任务与看板照常运行）"
  echo "  看板:   com.htma.dashboard  → http://127.0.0.1:5002"
  echo ""
  echo "要启用外网访问 https://htma.greatagain.com.cn，请："
  echo "  1. 创建文件 .tunnel-token（在项目根目录），内容为一行 Cloudflare 隧道 Token（从 one.dash.cloudflare.com 复制）"
  echo "  2. 执行: launchctl load $AGENTS/$TUNNEL_PLIST"
  echo "  或重新执行: bash scripts/install_launchd_htma.sh"
fi
echo "日志: $PROJECT_ROOT/logs/"
echo ""
echo "常用命令："
echo "  查看状态: launchctl list | grep com.htma"
echo "  停止隧道: launchctl unload $AGENTS/$TUNNEL_PLIST"
echo "  停止看板: launchctl unload $AGENTS/$DASHBOARD_PLIST"
echo "  停止防睡眠: launchctl unload $AGENTS/$KEEPAWAKE_PLIST"
echo "             （停止防睡眠后，锁屏时系统可能进入睡眠）"
echo "  再次启动: launchctl load $AGENTS/$KEEPAWAKE_PLIST && launchctl load $AGENTS/$DASHBOARD_PLIST && launchctl load $AGENTS/$TUNNEL_PLIST"
