#!/bin/bash
# 安装「比价可用性检查」launchd 任务：每日 8:00 执行自检，由 OpenClaw 自动化检查平台比价是否可用。
# 执行: bash scripts/install_launchd_price_compare_healthcheck.sh
# 日志: logs/price_compare_healthcheck.log（自检输出）、.out.log / .err.log（launchd）

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
PLIST="com.htma.price_compare_healthcheck.plist"

mkdir -p "$AGENTS"
mkdir -p "$PROJECT_ROOT/logs"

# PATH 与 run_selfserve_price_compare_debug 一致，便于找到 openclaw/clawhub
PATH_VAL="${HOME}/Library/pnpm:${HOME}/.npm-global/bin:/usr/local/bin:/usr/bin:/bin"
ENV_XML="    <key>PATH</key>\n    <string>${PATH_VAL}</string>\n"
ENV_XML="${ENV_XML}    <key>OPENCLAW_GATEWAY_URL</key>\n    <string>http://127.0.0.1:18789</string>\n"
if [ -f "$PROJECT_ROOT/.env" ]; then
  for k in OPENCLAW_GATEWAY_TOKEN MYSQL_HOST MYSQL_PORT MYSQL_USER MYSQL_PASSWORD MYSQL_DATABASE; do
    v=$(grep -m1 "^${k}=" "$PROJECT_ROOT/.env" 2>/dev/null | sed "s/^${k}=//" | tr -d '\r' | sed 's/^["'\'']//;s/["'\'']$//')
    [ -z "$v" ] && continue
    v_escaped=$(echo "$v" | sed 's/&/\&amp;/g;s/</\&lt;/g;s/>/\&gt;/g;s/"/\&quot;/g')
    ENV_XML="${ENV_XML}    <key>${k}</key>\n    <string>${v_escaped}</string>\n"
  done
fi

cat > "$AGENTS/$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.price_compare_healthcheck</string>
  <key>ProcessType</key>
  <string>Background</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
$(echo -e "$ENV_XML")
  </dict>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT_ROOT/scripts/run_price_compare_healthcheck.sh</string>
  </array>
  <key>RunAtLoad</key>
  <false/>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>8</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/price_compare_healthcheck.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/price_compare_healthcheck.err.log</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$AGENTS/$PLIST" 2>/dev/null || true
launchctl load "$AGENTS/$PLIST"

echo "已安装「比价可用性检查」定时任务（OpenClaw 自动化）：每日 8:00 执行自检。"
echo "  Label: com.htma.price_compare_healthcheck"
echo "  脚本: $PROJECT_ROOT/scripts/run_price_compare_healthcheck.sh"
echo "  日志: $PROJECT_ROOT/logs/price_compare_healthcheck.log 与 .out.log / .err.log"
echo ""
echo "常用命令："
echo "  查看状态: launchctl list | grep com.htma.price_compare_healthcheck"
echo "  停止:     launchctl unload $AGENTS/$PLIST"
echo "  再次启用: launchctl load $AGENTS/$PLIST"
echo "  手动跑一次: bash $PROJECT_ROOT/scripts/run_price_compare_healthcheck.sh"
