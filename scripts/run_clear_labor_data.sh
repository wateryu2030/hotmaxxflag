#!/bin/bash
# 清空人力成本数据，便于重新导入
# 用法: bash scripts/run_clear_labor_data.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
PY="${PROJECT_ROOT}/.venv/bin/python"
[ -x "$PY" ] || PY=python3
"$PY" scripts/clear_labor_data.py "$@"
