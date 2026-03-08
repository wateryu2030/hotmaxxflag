#!/bin/bash
# 好特卖运营看板 - 自动化测试
# 执行: bash scripts/run_htma_tests.sh 或 npm run htma:test（若已配置）

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [ -d "$ROOT/.venv" ]; then
  "$ROOT/.venv/bin/python" -m pytest htma_dashboard/tests/ -v "$@"
else
  echo "未找到 .venv，使用当前环境 python3 -m pytest"
  python3 -m pytest htma_dashboard/tests/ -v "$@"
fi
