#!/usr/bin/env bash
# 校验税务分析接口：发票月份列表、12 月发票明细能正确返回数据（导入 12 月后前端能带出发票明细）
# 用法: bash scripts/openclaw_verify_tax_analysis.sh [BASE_URL]
# 例:   bash scripts/openclaw_verify_tax_analysis.sh https://htma.greatagain.com.cn
# 例:   bash scripts/openclaw_verify_tax_analysis.sh http://127.0.0.1:5002
set -e
BASE_URL="${1:-http://127.0.0.1:5002}"
BASE_URL="${BASE_URL%/}"

echo "=============================================="
echo "OpenClaw：税务分析接口校验（12 月发票明细）"
echo "=============================================="
echo "BASE_URL: $BASE_URL"
echo ""

echo ">>> [1] GET /api/tax_analysis/invoice_months"
CODE_M=$(curl -s -o /tmp/tax_months.json -w "%{http_code}" --connect-timeout 10 "${BASE_URL}/api/tax_analysis/invoice_months" 2>/dev/null) || echo "000"
if [ "$CODE_M" = "401" ] || [ "$CODE_M" = "403" ]; then
  echo "    HTTP $CODE_M（需登录/权限，接口可达，请在浏览器登录后导入 12 月再查看发票明细）"
elif [ "$CODE_M" = "200" ]; then
  echo "    HTTP 200"
  if command -v jq >/dev/null 2>&1; then
    MONTHS=$(jq -r '.months | length' /tmp/tax_months.json 2>/dev/null)
    HAS_12=$(jq -r '.months[] | select(. == "2025-12")' /tmp/tax_months.json 2>/dev/null)
    echo "    已导入月份数: $MONTHS"
    if [ -n "$HAS_12" ]; then
      echo "    包含 2025-12（12 月），继续校验明细接口"
    else
      echo "    未包含 2025-12，请先导入 12 月发票 Excel 后再校验明细"
    fi
  fi
else
  echo "    HTTP $CODE_M"
  head -c 200 /tmp/tax_months.json 2>/dev/null || true
  echo ""
fi
echo ""

echo ">>> [2] GET /api/tax_analysis/invoice_detail?period_month=2025-12"
CODE_D=$(curl -s -o /tmp/tax_detail_12.json -w "%{http_code}" --connect-timeout 10 "${BASE_URL}/api/tax_analysis/invoice_detail?period_month=2025-12" 2>/dev/null) || echo "000"
if [ "$CODE_D" = "401" ] || [ "$CODE_D" = "403" ]; then
  echo "    HTTP $CODE_D（需登录/权限，接口可达）"
elif [ "$CODE_D" = "200" ]; then
  echo "    HTTP 200"
  if command -v jq >/dev/null 2>&1; then
    ROWS=$(jq -r '.rows | length' /tmp/tax_detail_12.json 2>/dev/null)
    OK=$(jq -r '.success' /tmp/tax_detail_12.json 2>/dev/null)
    echo "    success: $OK, rows: $ROWS"
    if [ "$ROWS" != "null" ] && [ "${ROWS:-0}" -gt 0 ]; then
      echo "    通过：12 月发票明细有 $ROWS 条，前端「发票明细」选 2025-12 点查询应能显示"
    else
      echo "    12 月暂无明细数据，请先在「税务分析」-「发票导入」上传 2025年12月发票.xlsx 并选择账期 2025-12"
    fi
  fi
else
  echo "    HTTP $CODE_D"
  head -c 300 /tmp/tax_detail_12.json 2>/dev/null || true
  echo ""
fi
echo ""

echo "=============================================="
echo "税务分析校验完成。若 [1][2] 为 200 且 rows>0，前端导入 12 月后应能自动带出发票明细。"
echo "=============================================="
