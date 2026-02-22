#!/usr/bin/env bash
# ============================================================
# 货盘价格对比分析 - 4 阶段闭环（OpenCLAW 可调用）
# 执行：./scripts/openclaw_price_compare.sh
# 输出：控制台报告 + 可选保存到 MySQL
# ============================================================

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

echo "=========================================="
echo "货盘价格对比分析 - 4 阶段闭环"
echo "=========================================="

source "$PROJECT_ROOT/.venv/bin/activate" 2>/dev/null || {
  python3 -m venv "$PROJECT_ROOT/.venv" && source "$PROJECT_ROOT/.venv/bin/activate"
}
pip install -q pymysql python-dotenv 2>/dev/null || true
# 加载 .env（若存在）
[ -f "$PROJECT_ROOT/.env" ] && set -a && source "$PROJECT_ROOT/.env" && set +a

cd "$PROJECT_ROOT/htma_dashboard"
# 使用真实 API 执行比价（若 .env 已配置 PDD_HOJINGKE_APIKEY 等）；未配置时自动回退为模拟
python3 -c "
from price_compare import run_full_pipeline, format_report
import pymysql

conn = pymysql.connect(
    host='127.0.0.1', port=3306, user='root', password='62102218',
    database='htma_dashboard', charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor
)
try:
    result = run_full_pipeline(conn, store_id='沈阳超级仓', days=30, use_mock_fetcher=False, fetch_limit=100)
    report = format_report(result)
    print(report)
finally:
    conn.close()
"

echo ""
echo "=========================================="
echo "分析完成"
echo "=========================================="
