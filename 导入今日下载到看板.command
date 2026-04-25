#!/bin/bash
# 将「下载」文件夹中**今天**修改的好特卖 Excel 导入 MySQL（销售日报/汇总/实时库存/分店商品档案，各取今日最新）
# 双击本文件即可执行，无需打开终端手动输入命令。

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

echo "=========================================="
echo "  好特卖 — 导入今日下载（~/Downloads）"
echo "=========================================="
echo ""

PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  echo "未找到 $PYTHON_BIN，请先在本机创建虚拟环境。"
  read -n 1
  exit 78
fi

[ -f "$PROJECT_ROOT/.env" ] && set -a && . "$PROJECT_ROOT/.env" 2>/dev/null && set +a

"$PYTHON_BIN" "$PROJECT_ROOT/scripts/auto_import_from_downloads.py" --today
EXIT_CODE=$?

# 导入脚本内已会去重并清理合计行；此处再执行一次可清掉历史误导入的汇总行（幂等）
if [ -f "$PROJECT_ROOT/scripts/run_delete_summary_rows.sh" ]; then
  echo ""
  echo "--- 再次清理数据库中的合计/汇总行（幂等）---"
  /bin/bash "$PROJECT_ROOT/scripts/run_delete_summary_rows.sh" || true
fi

echo ""
if [ "$EXIT_CODE" -eq 0 ]; then
  echo "完成。可在浏览器打开 http://127.0.0.1:5002 查看看板。"
else
  echo "导入结束（退出码 $EXIT_CODE）。请查看上方输出。"
fi
read -n 1 -p "按任意键关闭此窗口..."
