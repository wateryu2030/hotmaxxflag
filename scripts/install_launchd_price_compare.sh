#!/bin/bash
# 安装「定时比价」launchd 任务：每周一凌晨 2 点执行 batch_price_compare，由 OpenClaw/系统自动化调度。
# 执行: bash scripts/install_launchd_price_compare.sh
# 依赖：已执行 scripts/23_create_t_price_compare.sql、clawhub install baidu-ecommerce-skill、.venv 与 .env（含 MYSQL_*）

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
PLIST="com.htma.price_compare.plist"

mkdir -p "$AGENTS"
mkdir -p "$PROJECT_ROOT/logs"

if [ ! -f "$PROJECT_ROOT/.venv/bin/python" ]; then
  echo "未找到 .venv，正在创建并安装依赖..."
  bash "$PROJECT_ROOT/scripts/ensure_venv.sh"
fi

# 从 .env 读取环境变量（MySQL、门店、比价参数）
ENV_KEYS="MYSQL_HOST MYSQL_PORT MYSQL_USER MYSQL_PASSWORD MYSQL_DATABASE HTMA_STORE_ID PRICE_COMPARE_TOP_N PRICE_COMPARE_MIN_PRICE PRICE_COMPARE_DELAY"
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

# 每周一 02:00 执行（StartCalendarInterval Weekday=1 为周一）
cat > "$AGENTS/$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.price_compare</string>
  <key>ProcessType</key>
  <string>Background</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT_ROOT/scripts/run_price_compare_cron.sh</string>
  </array>
$(echo -e "$ENV_BLOCK")
  <key>RunAtLoad</key>
  <false/>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>1</integer>
    <key>Hour</key>
    <integer>2</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/price_compare_cron.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/price_compare_cron.err.log</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$AGENTS/$PLIST" 2>/dev/null || true
launchctl load "$AGENTS/$PLIST"

echo "已安装定时比价任务（OpenClaw 自动化）：每周一凌晨 2:00 执行 batch_price_compare。"
echo "  Label: com.htma.price_compare"
echo "  脚本: $PROJECT_ROOT/scripts/run_price_compare_cron.sh"
echo "  日志: $PROJECT_ROOT/logs/price_compare_cron.log 与 .out.log / .err.log"
echo ""
echo "常用命令："
echo "  查看状态: launchctl list | grep com.htma.price_compare"
echo "  停止:     launchctl unload $AGENTS/$PLIST"
echo "  再次启用: launchctl load $AGENTS/$PLIST"
echo "  手动跑一次: bash $PROJECT_ROOT/scripts/run_price_compare_cron.sh"
