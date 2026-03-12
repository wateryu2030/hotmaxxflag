#!/bin/bash
# 确保当前 shell 和今后新开终端都能找到 clawhub（npm 全局 bin 加入 PATH）
# 用法：source scripts/ensure_clawhub_path.sh  或  bash scripts/ensure_clawhub_path.sh

NPM_BIN="$HOME/.npm-global/bin"
if [ -d "$NPM_BIN" ]; then
  export PATH="$NPM_BIN:$PATH"
  # 若未写入 .zshrc 则追加
  if [ -f "$HOME/.zshrc" ] && ! grep -q '\.npm-global/bin' "$HOME/.zshrc" 2>/dev/null; then
    echo "" >> "$HOME/.zshrc"
    echo "# npm 全局 bin（clawhub 等）" >> "$HOME/.zshrc"
    echo "[ -d \"\$HOME/.npm-global/bin\" ] && export PATH=\"\$HOME/.npm-global/bin:\$PATH\"" >> "$HOME/.zshrc"
    echo "已写入 ~/.zshrc，新开终端将自动生效。"
  fi
  echo "当前 shell PATH 已包含 $NPM_BIN，可直接运行: clawhub -h"
else
  echo "未找到 $NPM_BIN，请先执行: npm install -g clawhub"
  exit 1
fi
