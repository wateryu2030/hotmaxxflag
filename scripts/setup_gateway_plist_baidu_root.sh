#!/usr/bin/env bash
# 向 OpenClaw 网关 launchd plist 注入 OPENCLAW_BAIDU_PROJECT_ROOT，使 baidu-price-tools 插件能调 runner。
# 用法: bash scripts/setup_gateway_plist_baidu_root.sh
# 执行后需重启网关: launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST="${OPENCLAW_GATEWAY_PLIST:-$HOME/Library/LaunchAgents/ai.openclaw.gateway.plist}"

if [[ ! -f "$PLIST" ]]; then
  echo "未找到网关 plist: $PLIST"
  echo "请先执行 openclaw gateway install 或 node \$HOME/openclaw/openclaw.mjs gateway install"
  exit 1
fi

/usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:OPENCLAW_BAIDU_PROJECT_ROOT string $PROJECT_ROOT" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :EnvironmentVariables:OPENCLAW_BAIDU_PROJECT_ROOT $PROJECT_ROOT" "$PLIST" 2>/dev/null

echo "已设置 OPENCLAW_BAIDU_PROJECT_ROOT=$PROJECT_ROOT"
echo "请重启网关: launchctl bootout gui/\$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist && launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist"
