#!/bin/bash
# 首页数据链路自动化验证：静态 SQL 守卫 + 经营/运维 API 契约
# 用法: bash scripts/verify_homepage_api_chain.sh
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
  echo "错误: 未找到 $ROOT/.venv" >&2
  exit 1
fi

echo "使用: $PY"
"$PY" -m unittest \
  tests.test_biz_enhanced_store_id_guard.TestBizEnhancedStoreIdGuard \
  tests.test_api_contract.TestApiContract.test_homepage_biz_summary_category_slow_movers_ops_labor \
  -v
echo "verify_homepage_api_chain: OK"
