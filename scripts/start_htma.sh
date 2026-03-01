#!/bin/bash
# 好特卖运营看板 - 启动脚本
# 执行: bash scripts/start_htma.sh 或 npm run htma:run

set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate

# 确保表结构完整
python scripts/run_add_columns.py 2>/dev/null || true
# 确保平台商品表、品类毛利汇总表存在
mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" htma_dashboard < scripts/08_create_platform_products.sql 2>/dev/null || true
mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" htma_dashboard < scripts/11_create_category_profit_summary.sql 2>/dev/null || true

# 导出 .env 中的变量，确保飞书登录等配置被 Python 读到（含 launchd 等场景）
if [ -f .env ]; then
  set -a
  . ./.env 2>/dev/null || true
  set +a
  # 若 source 未导出，则用 grep 显式导出飞书相关（避免 shell 语法差异）
  [ -z "$FEISHU_APP_ID" ] && export FEISHU_APP_ID="$(grep -m1 '^FEISHU_APP_ID=' .env 2>/dev/null | sed 's/^FEISHU_APP_ID=//' | tr -d '\r')"
  [ -z "$FEISHU_APP_SECRET" ] && export FEISHU_APP_SECRET="$(grep -m1 '^FEISHU_APP_SECRET=' .env 2>/dev/null | sed 's/^FEISHU_APP_SECRET=//' | tr -d '\r')"
  [ -z "$HTMA_PUBLIC_URL" ] && export HTMA_PUBLIC_URL="$(grep -m1 '^HTMA_PUBLIC_URL=' .env 2>/dev/null | sed 's/^HTMA_PUBLIC_URL=//' | tr -d '\r')"
fi
# 启动前检查飞书配置（不阻塞启动，仅提示）
python scripts/check_feishu_env.py 2>/dev/null || true
# 启动服务：显式传入飞书变量，避免通过 npm 等启动时子进程未继承 env
cd htma_dashboard && exec env FEISHU_APP_ID="${FEISHU_APP_ID}" FEISHU_APP_SECRET="${FEISHU_APP_SECRET}" HTMA_PUBLIC_URL="${HTMA_PUBLIC_URL}" python app.py
