#!/bin/bash
# 释放 5002 并重启看板（与 launchd 配合）。双击本文件即可，无需 Cursor。
resolve_project_root() {
  local src="$0"
  while [ -L "$src" ]; do
    local tgt="$(readlink "$src")"
    [[ "$tgt" != /* ]] && tgt="$(cd "$(dirname "$src")" && pwd)/$tgt"
    src="$tgt"
  done
  cd "$(dirname "$src")" && pwd
}
PROJECT_ROOT="$(resolve_project_root)"
cd "$PROJECT_ROOT" || { echo "无法进入项目目录"; read -n 1; exit 1; }

echo "正在重启看板…"
bash "$PROJECT_ROOT/scripts/restart_htma_dashboard.sh"
sleep 1
open "http://127.0.0.1:5002" 2>/dev/null || true
echo "完成。日志: $PROJECT_ROOT/logs/restart_htma_dashboard.log"
read -n 1 -p "按任意键关闭…"
