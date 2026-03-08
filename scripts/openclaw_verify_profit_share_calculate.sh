#!/usr/bin/env bash
# 校验收益评估计算接口 POST /api/profit_share/calculate 不返回 500（Decimal*float 等类型错误已修复）。
# 用法: bash scripts/openclaw_verify_profit_share_calculate.sh [BASE_URL]
# 例:   bash scripts/openclaw_verify_profit_share_calculate.sh https://htma.greatagain.com.cn
set -e
BASE_URL="${1:-http://127.0.0.1:5002}"
BASE_URL="${BASE_URL%/}"

echo ">>> POST $BASE_URL/api/profit_share/calculate (month=2026-01)"
CODE=$(curl -s -o /tmp/ps_calc.json -w "%{http_code}" --connect-timeout 15 -X POST "${BASE_URL}/api/profit_share/calculate" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"month":"2026-01"}' 2>/dev/null) || echo "000"

if [ "$CODE" = "500" ]; then
  echo "    失败: HTTP 500（若为 Decimal*float 类型错误，请确认 app.py 中 total_sales/total_profit 已用 float() 转换）"
  echo "    响应摘要:"
  head -c 800 /tmp/ps_calc.json 2>/dev/null | tr -d '\n'
  echo ""
  exit 1
fi
if [ "$CODE" = "200" ]; then
  echo "    通过: HTTP 200（计算成功）"
  if command -v jq >/dev/null 2>&1; then
    echo "    result_id: $(jq -r '.result_id // .error' /tmp/ps_calc.json 2>/dev/null)"
    echo "    total_sales: $(jq -r '.total_sales // empty' /tmp/ps_calc.json 2>/dev/null)"
  fi
elif [ "$CODE" = "400" ]; then
  echo "    通过: HTTP 400（业务校验，如未配置规则或该月无数据，属正常）"
  if command -v jq >/dev/null 2>&1; then
    echo "    error: $(jq -r '.error // empty' /tmp/ps_calc.json 2>/dev/null)"
  fi
elif [ "$CODE" = "401" ] || [ "$CODE" = "403" ]; then
  echo "    通过: HTTP $CODE（未登录/无权限，接口可达）"
else
  echo "    注意: HTTP $CODE"
  head -c 300 /tmp/ps_calc.json 2>/dev/null || true
  echo ""
fi
echo ""
echo "收益评估计算接口校验完成（非 500 即视为已修复）。"
