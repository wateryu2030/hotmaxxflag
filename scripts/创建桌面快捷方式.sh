#!/bin/bash
# 将两个 .command 启动器复制到当前用户桌面，便于双击打开
cd "$(dirname "$0")/.."
DESKTOP="${HOME}/Desktop"
if [ ! -d "$DESKTOP" ]; then
  DESKTOP="${HOME}/桌面"
fi
if [ ! -d "$DESKTOP" ]; then
  echo "未找到桌面目录（Desktop 或 桌面）。"
  echo "请手动将以下文件复制到桌面并双击运行："
  echo "  $(pwd)/启动好特卖看板.command"
  echo "  $(pwd)/启动好特卖看板+外网访问.command"
  exit 1
fi
cp -f "$(pwd)/启动好特卖看板.command" "$DESKTOP/"
cp -f "$(pwd)/启动好特卖看板+外网访问.command" "$DESKTOP/"
chmod +x "$DESKTOP/启动好特卖看板.command" "$DESKTOP/启动好特卖看板+外网访问.command"
echo "已在桌面创建快捷方式："
echo "  - 启动好特卖看板"
echo "  - 启动好特卖看板+外网访问"
echo "双击即可运行。"
