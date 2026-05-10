#!/bin/bash
# 安装每日 02:00：规则引擎 + AI 快报（不含分类日表刷新）。
# 推荐主方案：bash scripts/install_launchd_htma_nightly_business.sh（23:00 刷新+预警+快报），
# 再执行 launchctl unload ~/Library/LaunchAgents/com.htma.daily_cron.plist 避免重复跑 AI。
# 用法: bash scripts/install_launchd_htma_daily_cron.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
PLIST="com.htma.daily_cron.plist"

if [ ! -f "$PROJECT_ROOT/.venv/bin/python3" ]; then
  echo "未找到 .venv，正在创建..."
  bash "$PROJECT_ROOT/scripts/ensure_venv.sh"
fi

mkdir -p "$AGENTS"
mkdir -p "$PROJECT_ROOT/logs"

ENV_KEYS="MYSQL_HOST MYSQL_PORT MYSQL_USER MYSQL_PASSWORD MYSQL_DATABASE HTMA_STORE_ID HTMA_SKIP_MOBILE_JWT HTMA_LLM_PROVIDER HTMA_LLM_API_URL HTMA_LLM_API_KEY HTMA_LLM_MODEL OPENAI_API_KEY OPENAI_API_BASE OPENAI_MODEL DEEPSEEK_API_KEY DEEPSEEK_MODEL HTMA_DEEPSEEK_API_BASE DOUBAO_API_KEY DOUBAO_MODEL DOUBAO_API_BASE VOLCANO_ENGINE_API_KEY HTMA_CRON_WEBHOOK_URL FEISHU_WEBHOOK_URL HTMA_CRON_NOTIFY_SUCCESS HTMA_ALERT_ENGINE_LOW_MARGIN_PCT HTMA_ALERT_ENGINE_LARGE_SHARE_PCT"
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

launchctl unload "$AGENTS/$PLIST" 2>/dev/null || true

cat > "$AGENTS/$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.daily_cron</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PROJECT_ROOT/.venv/bin/python3</string>
    <string>$PROJECT_ROOT/scripts/daily_cron_job.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>2</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/daily_cron.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/daily_cron.err.log</string>
$(echo -e "$ENV_BLOCK")
</dict>
</plist>
PLISTEOF

chmod 600 "$AGENTS/$PLIST" 2>/dev/null || true

launchctl load "$AGENTS/$PLIST"
echo "Installed and loaded: $AGENTS/$PLIST (runs daily at 02:00; logs: $PROJECT_ROOT/logs/daily_cron.*.log)"
echo "Manual run: cd $PROJECT_ROOT && .venv/bin/python3 scripts/daily_cron_job.py"
echo "Note: secrets from .env are copied into this plist; chmod 600 \"$AGENTS/$PLIST\" if others use this account."
