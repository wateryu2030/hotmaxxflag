#!/bin/bash
# 好特卖运营看板 - API 契约 smoke（根目录 tests/）
# 请使用项目 .venv：系统 python3 往往未装 pymysql，会出现 skipped=全部。
# 执行: bash scripts/run_htma_tests.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

export HTMA_UNITTEST_DISABLE_AUTH="${HTMA_UNITTEST_DISABLE_AUTH:-1}"
export HTMA_SKIP_MOBILE_JWT="${HTMA_SKIP_MOBILE_JWT:-1}"
export HTMA_DISABLE_APSCHEDULER="${HTMA_DISABLE_APSCHEDULER:-1}"

if [ -x "$ROOT/.venv/bin/python3" ]; then
  PY="$ROOT/.venv/bin/python3"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  echo "错误: 未找到 $ROOT/.venv 。请先:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r htma_dashboard/requirements.txt" >&2
  exit 1
fi

echo "使用: $PY"
exec "$PY" -m unittest discover -s tests -p "test_*.py" -v
