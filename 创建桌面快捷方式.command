#!/bin/bash
# 在桌面创建「启动好特卖看板」快捷方式，之后可直接从桌面双击启动（锁屏下仍可用）

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR" && pwd)"
LAUNCHER="$PROJECT_ROOT/启动好特卖看板.command"
DESKTOP="$HOME/Desktop"

if [ ! -f "$LAUNCHER" ]; then
  echo "未找到 启动好特卖看板.command，请确认在项目根目录执行本脚本。"
  read -n 1
  exit 1
fi

chmod +x "$LAUNCHER" 2>/dev/null || true
ln -sf "$LAUNCHER" "$DESKTOP/启动好特卖看板.command"
echo "已在桌面创建快捷方式：$DESKTOP/启动好特卖看板.command"
echo "双击该图标即可启动看板（锁屏后仍可访问，无需打开 Cursor）。"
echo ""
read -n 1 -p "按任意键关闭此窗口..."
