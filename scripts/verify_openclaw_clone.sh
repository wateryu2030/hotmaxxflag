#!/bin/bash
# 验证 openclaw 源码是否已克隆成功
# 用法：bash scripts/verify_openclaw_clone.sh
OPENCLAW_SRC="${OPENCLAW_SRC:-$HOME/openclaw}"
echo "检查: $OPENCLAW_SRC"
if [ ! -d "$OPENCLAW_SRC" ]; then
  echo "失败：目录不存在。请先运行 bash scripts/clone_openclaw_retry.sh"
  exit 1
fi
if [ ! -f "$OPENCLAW_SRC/package.json" ]; then
  echo "失败：package.json 不存在（可能克隆未完成或目录不完整）。"
  exit 1
fi
echo "通过：发现 package.json"
if [ -f "$OPENCLAW_SRC/pnpm-workspace.yaml" ]; then
  echo "通过：发现 pnpm-workspace.yaml（源码完整）"
fi
echo "验证成功。可执行: export PATH=\"\$(npm root -g)/../bin:\$PATH\" && bash scripts/openclaw_build_only.sh"
exit 0
