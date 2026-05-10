#!/bin/bash
# 安装每晚 23:00 经营闭环：刷新 daily_category_stats → 规则引擎 → AI 快报（见 scripts/nightly_business_job.py）
# 若已安装 com.htma.daily_cron（凌晨 2 点仅预警+快报），建议 unload 其一，避免 AI 快报一天生成两次。
# 用法: bash scripts/install_launchd_htma_nightly_business.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
PLIST="com.htma.nightly_business.plist"

if [ ! -f "$PROJECT_ROOT/.venv/bin/python3" ]; then
  echo "未找到 .venv，正在创建..."
  bash "$PROJECT_ROOT/scripts/ensure_venv.sh"
fi

mkdir -p "$AGENTS"
mkdir -p "$PROJECT_ROOT/logs"

ENV_KEYS="MYSQL_HOST MYSQL_PORT MYSQL_USER MYSQL_PASSWORD MYSQL_DATABASE HTMA_STORE_ID HTMA_NIGHTLY_STORE_IDS HTMA_NIGHTLY_REFRESH_LOOKBACK_DAYS HTMA_SKIP_MOBILE_JWT HTMA_LLM_PROVIDER HTMA_LLM_API_URL HTMA_LLM_API_KEY HTMA_LLM_MODEL OPENAI_API_KEY OPENAI_API_BASE OPENAI_MODEL DEEPSEEK_API_KEY DEEPSEEK_MODEL HTMA_DEEPSEEK_API_BASE DOUBAO_API_KEY DOUBAO_MODEL DOUBAO_API_BASE VOLCANO_ENGINE_API_KEY HTMA_CRON_WEBHOOK_URL FEISHU_WEBHOOK_URL HTMA_CRON_NOTIFY_SUCCESS HTMA_ALERT_ENGINE_LOW_MARGIN_PCT HTMA_ALERT_ENGINE_LARGE_SHARE_PCT"
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
  <string>com.htma.nightly_business</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PROJECT_ROOT/.venv/bin/python3</string>
    <string>$PROJECT_ROOT/scripts/nightly_business_job.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>23</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/nightly_business.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/nightly_business.err.log</string>
$(echo -e "$ENV_BLOCK")
</dict>
</plist>
PLISTEOF

chmod 600 "$AGENTS/$PLIST" 2>/dev/null || true

launchctl load "$AGENTS/$PLIST"
echo "Installed: $AGENTS/$PLIST (daily 23:00, logs: $PROJECT_ROOT/logs/nightly_business.*.log)"
echo "Manual: cd $PROJECT_ROOT && .venv/bin/python3 scripts/nightly_business_job.py"
echo "If com.htma.daily_cron is also loaded, consider: launchctl unload \"$AGENTS/com.htma.daily_cron.plist\""
