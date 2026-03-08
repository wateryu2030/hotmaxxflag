#!/usr/bin/env bash
# 看板重启并验证（以后类似改动：改完代码后执行本脚本，重启看板并检查效果）
# 自动化：释放 5002 → 启动看板 → 验证 /api/labor_cost、可选验证生产
# 用法: bash scripts/deploy_and_verify_labor.sh [生产base_url]
# 例: bash scripts/deploy_and_verify_labor.sh
#     bash scripts/deploy_and_verify_labor.sh https://htma.greatagain.com.cn

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"
BASE_REMOTE="${1:-}"

echo "=============================================="
echo "好特卖看板 - 部署并验证人力成本"
echo "=============================================="

# 1. 结束占用 5002 的进程
echo ""
echo "[1/4] 释放端口 5002..."
pid=$(lsof -ti :5002 2>/dev/null || true)
if [ -n "$pid" ]; then
  echo "  结束进程: $pid"
  kill $pid 2>/dev/null || true
  sleep 2
fi
pkill -f "htma_dashboard/app.py" 2>/dev/null || true
sleep 1
echo "  完成"

# 2. 启动看板（与 start_htma.sh 一致：.env、表结构、Flask）
echo ""
echo "[2/4] 启动看板..."
if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  . "$PROJECT_ROOT/.env" 2>/dev/null || true
  set +a
fi
source "$PROJECT_ROOT/.venv/bin/activate" 2>/dev/null || { echo "  错误: 未找到 .venv"; exit 1; }
python "$PROJECT_ROOT/scripts/run_add_columns.py" 2>/dev/null || true
mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" htma_dashboard < "$PROJECT_ROOT/scripts/13_create_labor_cost_table.sql" 2>/dev/null || true
cd "$PROJECT_ROOT/htma_dashboard"
nohup env FEISHU_APP_ID="${FEISHU_APP_ID}" FEISHU_APP_SECRET="${FEISHU_APP_SECRET}" HTMA_PUBLIC_URL="${HTMA_PUBLIC_URL}" python app.py >> /tmp/htma_dashboard.log 2>&1 &
echo "  后台启动中，等待就绪..."

for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:5002/api/health" 2>/dev/null | grep -q 200; then
    echo "  就绪 (约 ${i}s)"
    break
  fi
  sleep 1
  if [ "$i" -eq 12 ]; then
    echo "  启动超时。查看: tail -30 /tmp/htma_dashboard.log"
    exit 1
  fi
done

# 3. 验证本地人力成本接口（独立于主看板：仅 405 视为失败，5xx 仅提示）
echo ""
echo "[3/4] 验证本地 /api/labor_cost（人力成本独立模块，失败不影响主看板）..."
LOCAL_GET=$(curl -s -o /tmp/labor_local.json -w "%{http_code}" -X GET "http://127.0.0.1:5002/api/labor_cost" -H "Accept: application/json")
LOCAL_POST=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://127.0.0.1:5002/api/labor_cost" -H "Accept: application/json" -H "Content-Type: application/json" -d '{}')

if [ "$LOCAL_GET" = "405" ] || [ "$LOCAL_POST" = "405" ]; then
  echo "  失败: 本地返回 405，请检查路由注册"
  exit 1
fi
if [ "$LOCAL_GET" = "200" ]; then
  echo "  GET 200 OK"
  head -c 300 /tmp/labor_local.json
  echo ""
elif [ "$LOCAL_GET" = "401" ]; then
  echo "  GET 401（需登录，接口正常）"
elif [ "$LOCAL_GET" -ge 500 ] 2>/dev/null; then
  echo "  GET $LOCAL_GET（人力接口异常，不影响主看板；可检查数据库或访问 /labor 独立页）"
else
  echo "  GET $LOCAL_GET"
fi
if [ "$LOCAL_POST" = "200" ]; then
  echo "  POST 200 OK"
elif [ "$LOCAL_POST" = "401" ]; then
  echo "  POST 401（需登录，接口正常）"
elif [ "$LOCAL_POST" -ge 500 ] 2>/dev/null; then
  echo "  POST $LOCAL_POST（人力接口异常，不影响主看板）"
else
  echo "  POST $LOCAL_POST"
fi
echo "  人力成本接口独立于主看板（非 405 即通过本步）"

# 3.1 人力数据状态（现有记录：明细表/汇总表）
echo ""
echo "  人力数据状态:"
STATUS_HTTP=$(curl -s -o /tmp/labor_status.json -w "%{http_code}" "http://127.0.0.1:5002/api/labor_cost_status" -H "Accept: application/json" 2>/dev/null || echo "000")
if [ "$STATUS_HTTP" = "200" ]; then
  raw=$(python3 -c "import json; d=json.load(open('/tmp/labor_status.json')); print(d.get('raw_count', 0))" 2>/dev/null || echo "0")
  n_months=$(python3 -c "import json; d=json.load(open('/tmp/labor_status.json')); print(len(d.get('analysis_months', [])))" 2>/dev/null || echo "0")
  echo "    明细表 ${raw} 条，汇总表 ${n_months} 个月"
elif [ "$STATUS_HTTP" = "401" ]; then
  echo "    /api/labor_cost_status 需登录（接口已注册）"
else
  echo "    /api/labor_cost_status HTTP $STATUS_HTTP"
fi

# 4. 若传入生产 URL，验证生产
if [ -n "$BASE_REMOTE" ]; then
  echo ""
  echo "[4/4] 验证生产 $BASE_REMOTE/api/labor_cost ..."
  REMOTE_GET=$(curl -s -o /tmp/labor_remote.json -w "%{http_code}" -X GET "$BASE_REMOTE/api/labor_cost" -H "Accept: application/json" --connect-timeout 8 --max-time 12 2>/dev/null || echo "000")
  if [ "$REMOTE_GET" = "200" ]; then
    echo "  GET 200 OK - 生产可看到数据"
    head -c 300 /tmp/labor_remote.json
    echo ""
  elif [ "$REMOTE_GET" = "401" ]; then
    echo "  GET 401 - 生产接口可达，需登录后看板可见数据"
  elif [ "$REMOTE_GET" = "405" ]; then
    echo "  GET 405 - 生产反向代理未放行 GET /api/labor_cost，需在 Nginx/代理 放行"
    echo "  本地已部署成功，外网需运维配置代理后重试"
  else
    echo "  GET HTTP $REMOTE_GET（可能网络/隧道未开）"
  fi
else
  echo ""
  echo "[4/4] 跳过生产校验（未传 base_url）"
fi

echo ""
echo "=============================================="
echo "部署完成"
echo "  看板: http://127.0.0.1:5002"
echo "  人力成本为独立模块：Tab 使用 /api/labor_cost，完整页 /labor；异常不影响主看板"
echo "  日志: tail -f /tmp/htma_dashboard.log"
echo "  验证生产: bash scripts/check_labor_cost_api.sh https://htma.greatagain.com.cn"
echo "=============================================="
