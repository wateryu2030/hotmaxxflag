#!/usr/bin/env bash
# 重新部署好特卖看板并验证（环比联动、走势与同比、K线）
set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

echo "=== 1. 释放 5002 并重启看板 ==="
pid=$(lsof -ti :5002 2>/dev/null || true)
if [ -n "$pid" ]; then
  echo "  结束占用 5002 的进程: $pid"
  kill "$pid" 2>/dev/null || true
  sleep 2
fi

source "$PROJECT_ROOT/.venv/bin/activate" 2>/dev/null || { echo "请先创建 .venv"; exit 1; }
cd "$PROJECT_ROOT/htma_dashboard"
nohup python app.py > /tmp/htma_dashboard.log 2>&1 &
echo "  看板已在后台启动，等待就绪..."
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:5002/" 2>/dev/null | grep -q 200; then
    echo "  就绪 (${i}s)"
    break
  fi
  sleep 1
  if [ "$i" -eq 10 ]; then echo "  启动超时，查看: tail -20 /tmp/htma_dashboard.log"; exit 1; fi
done

echo ""
echo "=== 2. 验证接口 ==="
BASE="http://127.0.0.1:5002"

# 2.1 环比与 KPI 周期联动：period=recent30 应返回本期/上期为日期区间
echo -n "  环比(period=recent30): "
resp=$(curl -s "${BASE}/api/trend_analysis?granularity=day&period=recent30")
if echo "$resp" | grep -q '"current_period"'; then
  curr=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); p=d.get('period_over_period'); print(p.get('current_period','') if p else '')" 2>/dev/null || echo "")
  if echo "$curr" | grep -q '~'; then
    echo "OK (本期=$curr)"
  else
    echo "WARN (本期非区间: $curr)"
  fi
else
  echo "FAIL (无 period_over_period)"
fi

# 2.2 走势与同比：应有 trend 或 trend_summary 或 data_points
echo -n "  走势与同比: "
if echo "$resp" | grep -q '"trend"'; then
  echo "OK (含 trend)"
else
  echo "WARN (无 trend)"
fi

# 2.3 销售趋势(按日)：返回日数据供 K 线
echo -n "  销售趋势(按日): "
st=$(curl -s "${BASE}/api/sales_trend?granularity=day&period=recent30")
if echo "$st" | grep -q 'sale_amount'; then
  len=$(echo "$st" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)" 2>/dev/null || echo "0")
  echo "OK (${len} 天)"
else
  echo "FAIL"
fi

echo ""
echo "=== 完成 ==="
echo "  看板: http://127.0.0.1:5002"
echo "  日志: tail -f /tmp/htma_dashboard.log"
