#!/usr/bin/env bash
# 重启看板后运行：校验 /api/consumer_insight 与 /api/consumer_insight_trend 均不返回 405/500。
# 用法: bash scripts/openclaw_verify_consumer_insight_apis.sh [BASE_URL]
# 例:   bash scripts/openclaw_verify_consumer_insight_apis.sh
#       bash scripts/openclaw_verify_consumer_insight_apis.sh http://127.0.0.1:5002
set -e
BASE_URL="${1:-http://127.0.0.1:5002}"
BASE_URL="${BASE_URL%/}"
CI_URL="${BASE_URL}/api/consumer_insight?period=recent30&category=%E6%9C%8D%E8%A3%85"
TREND_URL="${BASE_URL}/api/consumer_insight_trend?granularity=week&days=90&period=recent30"

echo ">>> 1. GET $BASE_URL/api/consumer_insight?..."
CODE_GET=$(curl -s -o /tmp/ci_get.json -w "%{http_code}" --connect-timeout 5 -X GET "$CI_URL" -H "Accept: application/json" 2>/dev/null) || echo "000"
if [ "$CODE_GET" = "405" ]; then
  echo "    失败: HTTP 405（请确认已保存 app.py 并重启看板，OPTIONS 在 before_request 处理且无 /api/<path> 路由）"
  exit 1
fi
if [ "$CODE_GET" = "200" ] || [ "$CODE_GET" = "401" ]; then
  echo "    通过: HTTP $CODE_GET"
else
  echo "    注意: HTTP $CODE_GET（200/401 为正常）"
fi

echo ">>> 2. POST $BASE_URL/api/consumer_insight?..."
CODE_POST=$(curl -s -o /tmp/ci_post.json -w "%{http_code}" --connect-timeout 5 -X POST "$CI_URL" -H "Accept: application/json" 2>/dev/null) || echo "000"
if [ "$CODE_POST" = "405" ]; then
  echo "    失败: HTTP 405"
  exit 1
fi
if [ "$CODE_POST" = "500" ]; then
  echo "    失败: HTTP 500（后端异常，请查看 dashboard.err.log）"
  head -1 /tmp/ci_post.json 2>/dev/null || true
  exit 1
fi
if [ "$CODE_POST" = "200" ] || [ "$CODE_POST" = "401" ]; then
  echo "    通过: HTTP $CODE_POST"
else
  echo "    注意: HTTP $CODE_POST"
fi

echo ">>> 3. GET $BASE_URL/api/consumer_insight_trend?..."
CODE_TREND=$(curl -s -o /tmp/ci_trend.json -w "%{http_code}" --connect-timeout 5 -X GET "$TREND_URL" -H "Accept: application/json" 2>/dev/null) || echo "000"
if [ "$CODE_TREND" = "405" ]; then
  echo "    失败: HTTP 405"
  exit 1
fi
if [ "$CODE_TREND" = "500" ]; then
  echo "    失败: HTTP 500（如 Unknown column distribution_mode，请执行 scripts/20_add_distribution_mode_if_missing.sql）"
  head -c 200 /tmp/ci_trend.json 2>/dev/null || true
  echo ""
  exit 1
fi
if [ "$CODE_TREND" = "200" ] || [ "$CODE_TREND" = "401" ]; then
  echo "    通过: HTTP $CODE_TREND"
else
  echo "    注意: HTTP $CODE_TREND"
fi

echo ""
echo "消费洞察相关 API 校验通过（200/401 视为正常）。可打开: $BASE_URL/?page=insight&category=服装"
