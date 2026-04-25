#!/usr/bin/env bash
# 重启看板使新增 API（brand_categories、supplier_categories、price_band_categories 等）生效，解决外网 404
# 在跑看板的那台机器上执行: bash scripts/restart_dashboard_for_new_apis.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

echo "=============================================="
echo "重启看板以使新 API 生效（解决 404）"
echo "=============================================="
bash "$SCRIPT_DIR/openclaw_restart_dashboard_and_verify.sh"

echo ""
echo ">>> 验证新 API 是否已注册"
BASE="${1:-http://127.0.0.1:5002}"
CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "$BASE/api/brand_categories?period=recent30&brand=test" 2>/dev/null) || echo "000"
if [ "$CODE" = "404" ]; then
  echo "    /api/brand_categories -> 404（仍未生效，请确认已重启且无旧进程占 5002）"
  exit 1
fi
# 200=有数据或空数组，401=未登录，均表示路由已存在
echo "    /api/brand_categories -> HTTP $CODE（非 404 表示新路由已生效）"
CODE2=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "$BASE/tax_analysis" 2>/dev/null) || echo "000"
echo "    /tax_analysis（税务分析） -> HTTP $CODE2"
echo "=============================================="
echo "完成。外网访问: https://htma.greatagain.com.cn"
echo "税务分析: https://htma.greatagain.com.cn/tax_analysis"
echo "=============================================="
