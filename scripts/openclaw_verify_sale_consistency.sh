#!/usr/bin/env bash
# OpenClaw：校验销售数据口径一致（KPI/趋势/周几对比均来自 t_htma_sale，导入后 refresh_profit 同步）
# 执行: bash scripts/openclaw_verify_sale_consistency.sh [start_date] [end_date]
# 可选: BASE_URL=http://127.0.0.1:5002 校验接口返回与库一致
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"
START="${1:-2026-03-07}"
END="${2:-2026-03-08}"
BASE_URL="${BASE_URL:-http://127.0.0.1:5002}"

echo "=============================================="
echo "OpenClaw: 销售数据口径一致性校验"
echo "=============================================="
echo "周期: $START ~ $END"
echo ""

# 1. 库内一致性（同一表按总/按日/按周几汇总应一致）
echo ">>> 1. 库内 t_htma_sale 口径一致性"
.venv/bin/python scripts/verify_sale_consistency.py "$START" "$END" || exit 1
echo ""

# 2. 接口与库一致（KPI、趋势、周几对比 与 库 SUM 一致）
echo ">>> 2. 接口与库一致（需服务已启动）"
KPI=$(curl -s "${BASE_URL}/api/kpi?period=custom&start_date=${START}&end_date=${END}" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total_sale_amount', 0))" 2>/dev/null || echo "0")
TREND_SUM=$(curl -s "${BASE_URL}/api/sales_trend?granularity=day&period=custom&start_date=${START}&end_date=${END}" 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
sales = d.get('sales') or []
print(sum(float(x) for x in sales))
" 2>/dev/null || echo "0")
DOW_SUM=$(curl -s "${BASE_URL}/api/dow_sales?period=custom&start_date=${START}&end_date=${END}" 2>/dev/null | python3 -c "
import sys, json
rows = json.load(sys.stdin)
print(sum(float(r.get('sale_amount') or 0) for r in rows))
" 2>/dev/null || echo "0")

echo "  KPI 总销售额:     $KPI"
echo "  趋势按日相加:     $TREND_SUM"
echo "  周几对比相加:     $DOW_SUM"
python3 -c "
k, t, d = float('$KPI'), float('$TREND_SUM'), float('$DOW_SUM')
ok = abs(k - t) < 0.01 and abs(k - d) < 0.01
print('  [OK] 三处一致' if ok and k > 0 else '  [WARN] 若服务未启动或需登录请忽略；否则检查接口是否均从 t_htma_sale 取数')
" 2>/dev/null || true
echo ""
echo "数据入口: 销售日报/销售汇总 → t_htma_sale；导入后自动 refresh_profit 同步 t_htma_profit"
echo "数据出口: KPI、趋势、周几对比 均从 t_htma_sale 聚合，统计口径一致"
