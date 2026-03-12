#!/bin/bash
# 当已手动将 openclaw 源码放到 ~/openclaw 时，仅执行构建与 link（不卸载、不克隆）
# 用法：export PATH="$(npm root -g)/../bin:$PATH" && bash scripts/openclaw_build_only.sh
set -e
OPENCLAW_SRC="${OPENCLAW_SRC:-$HOME/openclaw}"
if [ ! -d "$OPENCLAW_SRC" ] || [ ! -f "$OPENCLAW_SRC/package.json" ]; then
  echo "错误：未找到 $OPENCLAW_SRC 或其中无 package.json"
  echo "请先从 https://github.com/openclaw/openclaw 下载 ZIP，解压后把文件夹改名为 openclaw 放到 $HOME/openclaw"
  exit 1
fi
echo "使用源码目录: $OPENCLAW_SRC"
pnpm setup 2>/dev/null || true
export PNPM_HOME="${PNPM_HOME:-$HOME/Library/pnpm}"
export PATH="$PNPM_HOME:$PATH"
cd "$OPENCLAW_SRC"
pnpm install
pnpm run ui:build 2>/dev/null || pnpm ui:build 2>/dev/null || true
pnpm run build 2>/dev/null || pnpm build
pnpm link --global
echo "完成。请执行: openclaw --version 与 clawhub run --help"
