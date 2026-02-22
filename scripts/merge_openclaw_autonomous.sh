#!/usr/bin/env bash
# 将本项目「全自动、无需确认」配置合并到 ~/.openclaw/openclaw.json
# 执行：bash scripts/merge_openclaw_autonomous.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OPENCLAW_JSON="${OPENCLAW_CONFIG:-$HOME/.openclaw/openclaw.json}"
SOURCE_JSON="$PROJECT_ROOT/config/openclaw-htma-autonomous.json"

if [[ ! -f "$SOURCE_JSON" ]]; then
  echo "错误: 未找到 $SOURCE_JSON"
  exit 1
fi

mkdir -p "$(dirname "$OPENCLAW_JSON")"

if [[ -f "$OPENCLAW_JSON" ]]; then
  # 简单合并：用 jq 深度合并（若没有 jq 则提示手动合并）
  if command -v jq &>/dev/null; then
    echo "合并 $SOURCE_JSON 到 $OPENCLAW_JSON"
    jq -s '.[0] * .[1]' "$OPENCLAW_JSON" "$SOURCE_JSON" > "${OPENCLAW_JSON}.tmp" && mv "${OPENCLAW_JSON}.tmp" "$OPENCLAW_JSON"
    echo "完成。请重启 OpenClaw 或重新加载配置使 exec.ask=off 生效。"
  else
    echo "未安装 jq，无法自动合并。请手动将以下文件内容合并到 $OPENCLAW_JSON："
    echo "  $SOURCE_JSON"
    echo "重点保证: tools.exec.ask = \"off\""
    exit 1
  fi
else
  cp "$SOURCE_JSON" "$OPENCLAW_JSON"
  echo "已创建 $OPENCLAW_JSON（全自动配置）。请重启 OpenClaw。"
fi
