#!/usr/bin/env bash
# ============================================================
# OpenClaw 人力分析自动化检查
# 校验：人力分析页可访问；categories / mapping / overview / by_category / management 接口
# 用法（项目根目录）:
#   bash scripts/openclaw_labor_analysis_check.sh
#   bash scripts/openclaw_labor_analysis_check.sh http://127.0.0.1:5002
# 可选环境：.env 中 HTMA_PUBLIC_URL 可指定远程 base（脚本参数优先）
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_URL="${1:-http://127.0.0.1:5002}"
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$ROOT/.env" 2>/dev/null || true
  set +a
  # 未传参数时用 .env 中的 HTMA_PUBLIC_URL
  if [ -z "$1" ] && [ -n "${HTMA_PUBLIC_URL:-}" ]; then
    BASE_URL="${HTMA_PUBLIC_URL}"
  fi
fi
BASE_URL="${BASE_URL%/}"

# 日期：最近 30 天
END_DATE=$(date +%Y-%m-%d)
START_DATE=$(date -v-30d +%Y-%m-%d 2>/dev/null || date -d "30 days ago" +%Y-%m-%d 2>/dev/null || echo "2026-01-01")

echo "=============================================="
echo "OpenClaw：人力分析接口与页面检查"
echo "=============================================="
echo "BASE_URL: $BASE_URL"
echo "时间段: $START_DATE ~ $END_DATE"
echo ""

FAIL=0

# 检查 HTTP 状态并可选检查 JSON success
check_api() {
  local name="$1"
  local url="$2"
  local expect_success="${3:-true}"
  local code
  code=$(curl -s -o /tmp/la_check_$$.json -w "%{http_code}" --connect-timeout 5 "$url" 2>/dev/null || echo "000")
  if [ "$code" = "200" ] || [ "$code" = "403" ]; then
    if [ "$expect_success" = "true" ] && [ "$code" = "200" ]; then
      if command -v jq >/dev/null 2>&1; then
        if jq -e '.success == true' /tmp/la_check_$$.json >/dev/null 2>&1; then
          echo "  [OK] $name (HTTP $code, success=true)"
        else
          echo "  [WARN] $name (HTTP $code, JSON 无 success 或非 true)"
        fi
      else
        echo "  [OK] $name (HTTP $code)"
      fi
    else
      echo "  [OK] $name (HTTP $code)"
    fi
  else
    echo "  [FAIL] $name (HTTP $code)"
    FAIL=1
  fi
  rm -f /tmp/la_check_$$.json
}

echo ">>> 1. 页面"
check_api "GET /labor_analysis" "$BASE_URL/labor_analysis" "false"

echo ""
echo ">>> 2. 接口（未登录可能 403，视为端点存在）"
check_api "GET /api/labor_analysis/categories" "$BASE_URL/api/labor_analysis/categories" "true"
check_api "GET /api/labor_analysis/labor_positions" "$BASE_URL/api/labor_analysis/labor_positions" "true"
check_api "GET /api/labor_analysis/mapping" "$BASE_URL/api/labor_analysis/mapping" "true"
check_api "GET /api/labor_analysis/overview" "$BASE_URL/api/labor_analysis/overview?start_date=$START_DATE&end_date=$END_DATE" "true"
check_api "GET /api/labor_analysis/by_category" "$BASE_URL/api/labor_analysis/by_category?start_date=$START_DATE&end_date=$END_DATE" "true"
check_api "GET /api/labor_analysis/management" "$BASE_URL/api/labor_analysis/management?start_date=$START_DATE&end_date=$END_DATE" "true"

echo ""
if [ $FAIL -eq 0 ]; then
  echo "=============================================="
  echo "人力分析检查通过"
  echo "=============================================="
  echo "配置说明：类目–人力映射由人工在「类目–人力映射配置」中完成：(1) 经营/管理归属；(2) 销售大类与经营人力岗位映射。"
  echo "文档: docs/人力分析Tab设计文档.md"
  exit 0
else
  echo "=============================================="
  echo "人力分析检查未通过（见上方 [FAIL]）"
  echo "=============================================="
  exit 1
fi
