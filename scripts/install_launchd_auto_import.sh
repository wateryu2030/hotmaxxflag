#!/bin/bash
# 安装「从下载目录自动导入」定时任务（每日 6:00 执行，使用 ~/Downloads）
# 执行: bash scripts/install_launchd_auto_import.sh
# 卸载: launchctl unload ~/Library/LaunchAgents/com.htma.auto_import.plist
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
PLIST="com.htma.auto_import.plist"
DOWNLOADS="${DOWNLOADS:-$HOME/Downloads}"

if [ ! -f "$PROJECT_ROOT/.venv/bin/python" ]; then
  echo "未找到 .venv，正在创建并安装依赖..."
  bash "$PROJECT_ROOT/scripts/ensure_venv.sh"
fi

mkdir -p "$AGENTS"
launchctl unload "$AGENTS/$PLIST" 2>/dev/null || true

# 每日 6:00 执行；WorkingDirectory 与环境变量使脚本使用 ~/Downloads
cat > "$AGENTS/$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.auto_import</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT_ROOT/scripts/run_auto_import.sh</string>
    <string>$DOWNLOADS</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>DOWNLOADS</key>
    <string>$DOWNLOADS</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>6</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/auto_import.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/auto_import.err.log</string>
</dict>
</plist>
EOF

mkdir -p "$PROJECT_ROOT/logs"
launchctl load "$AGENTS/$PLIST"
echo "已安装定时任务：每日 6:00 从 $DOWNLOADS 自动导入 Excel（有文件则导入、去重、刷新）。"
echo "  查看: launchctl list | grep com.htma.auto_import"
echo "  卸载: launchctl unload $AGENTS/$PLIST"
echo "  日志: $PROJECT_ROOT/logs/auto_import.out.log"
echo "  若希望锁屏/息屏后 6:00 仍能执行，请先执行: bash scripts/install_launchd_htma.sh（含防睡眠服务）"
