#!/bin/bash
# 人力成本一键导入：自动使用项目 .venv，避免手工执行时 ModuleNotFoundError
# 用法（项目根目录或任意目录均可）:
#   bash scripts/run_labor_import.sh
#   bash scripts/run_labor_import.sh 2026-01
#   bash scripts/run_labor_import.sh 2026-01 /path/to/12月薪资表.xlsx
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  PY="$PROJECT_ROOT/.venv/bin/python"
else
  PY=python3
fi

DEFAULT_EXCEL="$PROJECT_ROOT/12月薪资表-沈阳金融中心.xlsx"
REPORT_MONTH="${1:-2025-12}"
EXCEL_PATH="${2:-$DEFAULT_EXCEL}"

if [ ! -f "$EXCEL_PATH" ]; then
  echo "文件不存在: $EXCEL_PATH"
  echo "用法: bash scripts/run_labor_import.sh [报表月份] [Excel路径]"
  exit 1
fi

"$PY" scripts/import_labor_excel_and_analyze.py "$EXCEL_PATH" "$REPORT_MONTH"
