#!/usr/bin/env bash
# OpenClaw 自动化：校验消费洞察走势 API 是否返回 200（GET），避免 405。
# 用法: bash scripts/openclaw_verify_consumer_insight_trend.sh [BASE_URL]
# 例:   bash scripts/openclaw_verify_consumer_insight_trend.sh
#       bash scripts/openclaw_verify_consumer_insight_trend.sh http://127.0.0.1:5002
set -e
BASE_URL="${1:-http://127.0.0.1:5002}"
BASE_URL="${BASE_URL%/}"
API="${BASE_URL}/api/consumer_insight_trend?granularity=day&days=90&period=recent30"

echo ">>> 校验 GET $API"
CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 -X GET "$API" 2>/dev/null) || echo "000"
if [ "$CODE" = "200" ]; then
  echo "    通过: HTTP 200"
  exit 0
fi
if [ "$CODE" = "401" ]; then
  echo "    未登录: HTTP 401（接口存在且允许 GET，需登录后前端才能用）"
  exit 0
fi
echo "    失败: HTTP $CODE（期望 200 或 401，若为 405 请检查 app.py 中 OPTIONS 在 before_request 处理且无 /api/<path> 路由）"
exit 1
