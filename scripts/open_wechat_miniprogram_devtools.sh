#!/usr/bin/env bash
# 启动微信开发者工具并指向主小程序 miniprogram（可通过 WECHAT_MINI_PROJECT_DIR 覆盖为 miniprogram_example 等）
# 若命令行报「服务端口已关闭」：先手动打开微信开发者工具 → 设置 → 安全设置 → 开启「服务端口」，再执行本脚本。
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJ="${WECHAT_MINI_PROJECT_DIR:-$ROOT/miniprogram}"
APP="/Applications/wechatwebdevtools.app"
CLI="$APP/Contents/MacOS/cli"

if [ ! -d "$PROJ" ]; then
  echo "未找到项目目录: $PROJ"
  exit 1
fi

# 优先用系统 open 拉起工具（不依赖 CLI 服务端口）
if [ -d "$APP" ]; then
  open -a "$APP" "$PROJ" 2>/dev/null || true
fi

if [ -x "$CLI" ]; then
  if "$CLI" open --project "$PROJ" --lang zh 2>/dev/null; then
    echo "已通过 CLI 打开: $PROJ"
    exit 0
  fi
  echo "CLI 未就绪（常见原因：需在开发者工具内开启「服务端口」）。"
fi

echo "请在本机微信开发者工具中：导入项目 → 目录选："
echo "  $PROJ"
echo "AppID 使用测试号或与 project.config.json 中一致。"
