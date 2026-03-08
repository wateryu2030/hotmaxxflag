#!/usr/bin/env bash
# 重建人力成本表、清空数据、从下载目录导入 Excel，并刷新汇总。供 OpenClaw 或终端一键执行。
# 用法: bash scripts/openclaw_labor_rebuild_and_import.sh [报表月份...]
# 例:   bash scripts/openclaw_labor_rebuild_and_import.sh 2026-01 2025-12
#       多个月份时按文件名匹配（1月→*1月*，12月→*12月*）一一对应；否则用目录下最新一个 Excel。
# 注意: 请用 .venv/bin/python 或 bash 本脚本，系统自带的 python 可能未配置。

set -e
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
export DOWNLOADS="${IMPORT_DOWNLOADS_DIR:-${DOWNLOADS:-$HOME/Downloads}}"

echo "=============================================="
echo "人力成本：重建表 + 从下载目录导入"
echo "=============================================="
echo "下载目录: $DOWNLOADS"
echo ""

# 多个月份时：按月份在下载目录找对应 Excel（2026-01→*1月*，2025-12→*12月*），保证 1 月/12 月用不同文件
FILE_ARGS=()
if [ $# -ge 2 ]; then
  for m in "$@"; do
    num="${m##*-}"
    num=$((10#$num))
    found=""
    for pat in "*${num}月*.xlsx" "*${num}月*.xls"; do
      for f in "$DOWNLOADS"/$pat; do
        [ -f "$f" ] && found="$f" && break 2
      done
    done
    [ -n "$found" ] && FILE_ARGS+=(-f "$found")
  done
fi

if [ $# -eq 0 ]; then
  "$PYTHON" scripts/openclaw_labor_import_from_downloads.py --rebuild --yes 2026-01
elif [ $# -eq "${#FILE_ARGS[@]}" ] && [ $# -ge 2 ]; then
  "$PYTHON" scripts/openclaw_labor_import_from_downloads.py --rebuild --yes "${FILE_ARGS[@]}" "$@"
else
  "$PYTHON" scripts/openclaw_labor_import_from_downloads.py --rebuild --yes "$@"
fi
echo ""
echo "完成。请打开 /labor 查看（正式职工/其他人力分列、类目表格点击到人）。"
