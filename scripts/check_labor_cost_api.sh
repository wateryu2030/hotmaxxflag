#!/bin/bash
# 检查人力成本数据与 API：数据库记录数 + 本地/远程 GET 是否 200
# 用法: ./scripts/check_labor_cost_api.sh [base_url]
# 例: ./scripts/check_labor_cost_api.sh
#     ./scripts/check_labor_cost_api.sh https://htma.greatagain.com.cn

set -e
cd "$(dirname "$0")/.."
BASE="${1:-http://127.0.0.1:5002}"

echo "=== 数据库 t_htma_labor_cost 记录（本机 MySQL，与 BASE 是否一致取决于部署方式）==="
.venv/bin/python -c "
import os, sys
sys.path.insert(0, '.')
try:
    from dotenv import load_dotenv
    load_dotenv('.env')
except Exception: pass
from htma_dashboard.db_config import get_conn
conn = get_conn()
cur = conn.cursor()
cur.execute('SELECT report_month, position_type, COUNT(*) AS cnt FROM t_htma_labor_cost GROUP BY report_month, position_type ORDER BY report_month, position_type')
rows = cur.fetchall()
if not rows:
    print('  无数据')
else:
    for r in rows:
        print(' ', r[0], r[1], r[2], '条')
cur.execute('SELECT DISTINCT report_month FROM t_htma_labor_cost ORDER BY report_month DESC LIMIT 5')
months = [r[0] for r in cur.fetchall()]
print('  最近月份:', months or '无')
conn.close()
"

echo ""
echo "=== GET $BASE/api/labor_cost ==="
HTTP_GET=$(curl -s -o /tmp/labor_resp.json -w "%{http_code}" -X GET "$BASE/api/labor_cost" -H "Accept: application/json")
echo "HTTP $HTTP_GET"
if [ "$HTTP_GET" = "200" ]; then
  echo "响应摘要:"
  head -c 500 /tmp/labor_resp.json
  echo ""
elif [ -s /tmp/labor_resp.json ]; then
  head -c 400 /tmp/labor_resp.json
  echo ""
fi

echo ""
echo "=== POST $BASE/api/labor_cost ==="
HTTP_POST=$(curl -s -o /tmp/labor_post.json -w "%{http_code}" -X POST "$BASE/api/labor_cost" -H "Accept: application/json" -H "Content-Type: application/json" -d '{}')
echo "HTTP $HTTP_POST"

if [ "$HTTP_GET" = "405" ] || [ "$HTTP_POST" = "405" ]; then
  echo ""
  echo "说明: 405 Method Not Allowed 表示反向代理未放行 GET/POST /api/labor_cost。"
  echo "请在 nginx/代理 中对该路径允许 GET 与 POST。"
fi
if [ "$HTTP_GET" = "200" ] || [ "$HTTP_POST" = "200" ]; then
  echo ""
  echo "OK: 人力成本接口可访问（200）。"
fi
if [ "$HTTP_GET" = "401" ] || [ "$HTTP_POST" = "401" ]; then
  echo ""
  echo "说明: 401 表示需登录，接口路由正常。登录后看板「人力成本」Tab 会拉取数据；若仍无记录，请在生产服务器上执行人力成本导入（或确认生产库与本地为同一库且已导入）。"
fi
