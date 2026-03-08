#!/usr/bin/env bash
# 将本项目「全自动、无需确认」配置合并到 ~/.openclaw/openclaw.json
# 会将 __PROJECT_ROOT__ 替换为当前项目根目录，使 skills 指向本项目
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

# 将 __PROJECT_ROOT__ 替换为当前项目路径，生成临时配置
TMP_JSON="${OPENCLAW_JSON}.htma-merge.tmp"
sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" "$SOURCE_JSON" > "$TMP_JSON"

if [[ -f "$OPENCLAW_JSON" ]]; then
  if command -v jq &>/dev/null; then
    echo "合并 $SOURCE_JSON 到 $OPENCLAW_JSON（skills 目录: $PROJECT_ROOT/skills）"
    jq -s '.[0] * .[1]' "$OPENCLAW_JSON" "$TMP_JSON" > "${OPENCLAW_JSON}.tmp" && mv "${OPENCLAW_JSON}.tmp" "$OPENCLAW_JSON"
    rm -f "$TMP_JSON"
    echo "完成。请重启 OpenClaw 或重新加载配置使 exec.ask=off 与 skills 生效。"
  else
    rm -f "$TMP_JSON"
    echo "未安装 jq，无法自动合并。请手动将 $SOURCE_JSON 内容合并到 $OPENCLAW_JSON，并将 __PROJECT_ROOT__ 改为: $PROJECT_ROOT"
    echo "重点保证: tools.exec.ask = \"off\"，skills.load.extraDirs 含 \"$PROJECT_ROOT/skills\""
    exit 1
  fi
else
  mv "$TMP_JSON" "$OPENCLAW_JSON"
  echo "已创建 $OPENCLAW_JSON（全自动配置，skills: $PROJECT_ROOT/skills）。请重启 OpenClaw。"
fi
