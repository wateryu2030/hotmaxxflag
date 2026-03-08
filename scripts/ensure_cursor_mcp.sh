#!/usr/bin/env bash
# 在当前项目下确保 .cursor/mcp.json 存在，使 Cursor 可调用浏览器自动化（OpenClaw/Playwright MCP）。
# 用法：在项目根目录执行 bash scripts/ensure_cursor_mcp.sh

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURSOR_DIR="$REPO_ROOT/.cursor"
MCP_JSON="$CURSOR_DIR/mcp.json"

mkdir -p "$CURSOR_DIR"
if [[ -f "$MCP_JSON" ]]; then
  echo "已存在 $MCP_JSON，无需覆盖。"
  exit 0
fi

cat > "$MCP_JSON" << 'EOF'
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"]
    }
  }
}
EOF
echo "已创建 $MCP_JSON"
echo "请完全重启 Cursor（如 Cmd+Q 后重新打开），并在 设置 → MCP 中确认 playwright 为绿色。"
