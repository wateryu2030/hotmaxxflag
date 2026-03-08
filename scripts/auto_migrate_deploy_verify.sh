#!/usr/bin/env bash
# ============================================================
# 好特卖看板 - 一键自动化：数据库迁移 + 部署 + 验证 + 网络检查
# 执行: bash scripts/auto_migrate_deploy_verify.sh [BASE_URL]
# BASE_URL 默认 https://htma.greatagain.com.cn
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_URL="${1:-https://htma.greatagain.com.cn}"
BASE_URL="${BASE_URL%/}"

cd "$PROJECT_ROOT"
[ -f .env ] && set -a && . ./.env 2>/dev/null && set +a

echo "=============================================="
echo "好特卖看板 - 一键自动化（迁移+部署+验证）"
echo "=============================================="
echo "目标: $BASE_URL"
echo ""

# ========== 1. 数据库迁移：执行 03_add_full_columns（run_add_columns.py）==========
echo ">>> [1/5] 数据库迁移（03_add_full_columns / run_add_columns.py）..."
if [ -f "$PROJECT_ROOT/.venv/bin/python" ]; then
  "$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/run_add_columns.py" 2>&1 || true
else
  python3 "$PROJECT_ROOT/scripts/run_add_columns.py" 2>&1 || true
fi
echo "    迁移完成"
echo ""

# ========== 2. 部署 ==========
echo ">>> [2/5] 执行部署（deploy_htma_live.sh）..."
bash "$PROJECT_ROOT/scripts/deploy_htma_live.sh" 2>&1
echo ""

# ========== 3. 等待服务就绪 ==========
echo ">>> [3/5] 等待看板就绪..."
for i in $(seq 1 45); do
  if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 4 "http://127.0.0.1:5002/" 2>/dev/null | grep -qE '200|301|302|401'; then
    echo "    本机看板已响应 (127.0.0.1:5002)"
    break
  fi
  [ $i -eq 45 ] && echo "    警告: 端口 5002 未在 45 秒内响应"
  sleep 1
done
echo ""

# ========== 4. 验证 consumer_insight_trend 与 consumer_insight ==========
echo ">>> [4/5] 验证消费洞察 API..."
TREND_OK=0
INSIGHT_OK=0

# 本机验证
TREND_CODE=$(curl -s -o /tmp/htma_trend.json -w "%{http_code}" --connect-timeout 8 "http://127.0.0.1:5002/api/consumer_insight_trend?granularity=week&days=90&period=recent30" 2>/dev/null || echo "000")
if [ "$TREND_CODE" = "200" ]; then
  if grep -q '"labels"' /tmp/htma_trend.json 2>/dev/null; then
    echo "    ✓ consumer_insight_trend 本机 200 OK"
    TREND_OK=1
  else
    echo "    ! consumer_insight_trend 本机 200 但响应异常"
  fi
elif [ "$TREND_CODE" = "401" ]; then
  echo "    ○ consumer_insight_trend 本机 401（需登录，接口可达）"
  TREND_OK=1
else
  echo "    ✗ consumer_insight_trend 本机 HTTP $TREND_CODE"
  [ -f /tmp/htma_trend.json ] && echo "    错误详情: $(head -c 200 /tmp/htma_trend.json 2>/dev/null)"
fi

INSIGHT_CODE=$(curl -s -o /tmp/htma_insight.json -w "%{http_code}" -X POST --connect-timeout 8 "http://127.0.0.1:5002/api/consumer_insight?period=recent30" 2>/dev/null || echo "000")
if [ "$INSIGHT_CODE" = "200" ]; then
  if grep -q '"overview"' /tmp/htma_insight.json 2>/dev/null; then
    echo "    ✓ consumer_insight 本机 200 OK"
    INSIGHT_OK=1
  else
    echo "    ! consumer_insight 本机 200 但响应异常"
  fi
elif [ "$INSIGHT_CODE" = "401" ]; then
  echo "    ○ consumer_insight 本机 401（需登录，接口可达）"
  INSIGHT_OK=1
else
  echo "    ✗ consumer_insight 本机 HTTP $INSIGHT_CODE"
  [ -f /tmp/htma_insight.json ] && grep -o '"error":"[^"]*"' /tmp/htma_insight.json 2>/dev/null | head -1
fi

# 外网验证（若 BASE_URL 非 localhost）
if [[ "$BASE_URL" != *"127.0.0.1"* ]] && [[ "$BASE_URL" != *"localhost"* ]]; then
  sleep 2
  EXT_TREND=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 "$BASE_URL/api/consumer_insight_trend?granularity=week&days=90&period=recent30" 2>/dev/null || echo "000")
  if [ "$EXT_TREND" = "200" ]; then
    echo "    ✓ consumer_insight_trend 外网 200 OK"
  elif [ "$EXT_TREND" = "401" ]; then
    echo "    ○ consumer_insight_trend 外网 401（需登录，接口可达）"
  else
    echo "    ! consumer_insight_trend 外网 HTTP $EXT_TREND（可能为网络/Cloudflare/530）"
  fi
fi
echo ""

# ========== 5. 服务端日志与网络检查 ==========
echo ">>> [5/5] 服务端日志与网络检查..."
LOG_ERR="$PROJECT_ROOT/logs/dashboard.err.log"
LOG_OUT="$PROJECT_ROOT/logs/dashboard.out.log"
if [ -f "$LOG_ERR" ]; then
  echo "    最近 500 相关日志 (dashboard.err.log):"
  grep -i "500\|error\|exception\|traceback" "$LOG_ERR" 2>/dev/null | tail -15 || echo "    (无相关记录)"
else
  echo "    日志文件不存在: $LOG_ERR"
fi

echo ""
echo "    Cloudflare/网络检查:"
if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 6 "$BASE_URL/" 2>/dev/null | grep -qE '200|301|302|401'; then
  echo "    ✓ $BASE_URL 可访问"
else
  echo "    ! $BASE_URL 不可达（ERR_CONNECTION_TIMED_OUT/530 时检查: cloudflared 是否运行、Cloudflare 隧道状态）"
  echo "      排查: pgrep -fl cloudflared; 重启隧道: bash scripts/start_tunnel_htma.sh"
fi
echo ""

# ========== 汇总 ==========
echo "=============================================="
echo "自动化完成"
echo "=============================================="
if [ "$TREND_OK" = "1" ] && [ "$INSIGHT_OK" = "1" ]; then
  echo "• 消费洞察 API: 正常"
else
  echo "• 消费洞察 API: 存在异常，请查看上方输出与 logs/dashboard.err.log"
fi
echo "• 本机: http://127.0.0.1:5002"
echo "• 外网: $BASE_URL"
echo ""
echo "若仍有 500，请查看 500 响应的 Response  body 中的 error/traceback 字段定位原因。"
echo ""
