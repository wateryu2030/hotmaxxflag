#!/bin/bash
# 好特卖运营看板 - 独立版一键部署（不依赖 JimuReport）
# 执行: bash scripts/deploy_htma_standalone.sh

set -e
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== 1. 检查 MySQL 与数据 ==="
MYSQL_OPTS="-h 127.0.0.1 -u root -p62102218"
mysql $MYSQL_OPTS -e "
  SELECT 'stock' AS tbl, COUNT(*) AS cnt FROM htma_dashboard.t_htma_stock
  UNION ALL SELECT 'sale', COUNT(*) FROM htma_dashboard.t_htma_sale
  UNION ALL SELECT 'profit', COUNT(*) FROM htma_dashboard.t_htma_profit;
" 2>/dev/null || { echo "MySQL 连接失败，请确保 MySQL 运行且 htma_dashboard 已建表"; exit 1; }

echo ""
echo "=== 2. 安装 Python 依赖 ==="
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r htma_dashboard/requirements.txt

echo ""
echo "=== 3. 启动看板服务（端口 5002）==="
pkill -f "htma_dashboard/app.py" 2>/dev/null || true
sleep 1
cd htma_dashboard && python app.py &
APP_PID=$!
cd ..
sleep 3

echo ""
echo "=== 4. 验证 API ==="
HEALTH=$(curl -s "http://127.0.0.1:5002/api/health" 2>/dev/null || echo "")
if echo "$HEALTH" | grep -q '"status":"ok"'; then
  echo "API 正常: $HEALTH"
else
  echo "API 异常: $HEALTH"
  kill $APP_PID 2>/dev/null || true
  exit 1
fi

echo ""
echo "=========================================="
echo "好特卖运营看板已启动"
echo "访问: http://127.0.0.1:5002"
echo "=========================================="

# 尝试打开浏览器
if command -v open &>/dev/null; then
  open "http://127.0.0.1:5002" 2>/dev/null || true
elif command -v xdg-open &>/dev/null; then
  xdg-open "http://127.0.0.1:5002" 2>/dev/null || true
fi
