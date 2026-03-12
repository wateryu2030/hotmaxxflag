#!/bin/bash
# 安装「百度 Skill 定时重试」launchd 任务：每隔一段时间执行一次 retry_baidu_skill_until_done.sh，直至安装成功。
# 执行: bash scripts/install_launchd_retry_baidu_skill.sh
# 完成后脚本会创建 .baidu_skill_installed，定时任务仍会运行但会直接退出 0；若要重新尝试可删除该文件。

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
PLIST="com.htma.retry_baidu_skill.plist"
INTERVAL_SEC=900

mkdir -p "$AGENTS"
mkdir -p "$PROJECT_ROOT/logs"

# 注入 PATH 以便找到 clawhub
PATH_VAL="$HOME/.npm-global/bin:/usr/local/bin:/usr/bin:/bin"
PATH_ESC=$(echo "$PATH_VAL" | sed 's/&/\&amp;/g;s/</\&lt;/g;s/>/\&gt;/g;s/"/\&quot;/g')
ENV_BLOCK="  <key>EnvironmentVariables</key>\n  <dict>\n    <key>PATH</key>\n    <string>${PATH_ESC}</string>\n  </dict>"

cat > "$AGENTS/$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.retry_baidu_skill</string>
  <key>ProcessType</key>
  <string>Background</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT_ROOT/scripts/retry_baidu_skill_until_done.sh</string>
  </array>
$(echo -e "$ENV_BLOCK")
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>$INTERVAL_SEC</integer>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/retry_baidu_skill.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/retry_baidu_skill.err.log</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$AGENTS/$PLIST" 2>/dev/null || true
launchctl load "$AGENTS/$PLIST"

echo "已安装定时重试任务：每 $((INTERVAL_SEC/60)) 分钟执行一次，直至百度 Skill 安装成功。"
echo "  Label: com.htma.retry_baidu_skill"
echo "  脚本: $PROJECT_ROOT/scripts/retry_baidu_skill_until_done.sh"
echo "  日志: $PROJECT_ROOT/logs/retry_baidu_skill.log 与 .out.log / .err.log"
echo "  完成标记: $PROJECT_ROOT/.baidu_skill_installed（成功后创建；删除后可再次重试）"
echo ""
echo "常用命令："
echo "  查看状态: launchctl list | grep com.htma.retry_baidu_skill"
echo "  停止:     launchctl unload $AGENTS/$PLIST"
echo "  再次启用: launchctl load $AGENTS/$PLIST"
echo "  手动跑一次: bash $PROJECT_ROOT/scripts/retry_baidu_skill_until_done.sh"
