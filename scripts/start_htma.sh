#!/bin/bash
# 好特卖运营看板 - 启动脚本
# 执行: bash scripts/start_htma.sh 或 npm run htma:run（launchd 下用 .venv 绝对路径，不依赖 source activate）

set -e
# 使用脚本所在目录解析项目根（launchd 下 $0 为绝对路径）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# launchd 启动时卷可能尚未挂载，最多等 30 秒
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
  [ -x "$ROOT/.venv/bin/python" ] && break
  sleep 1
done
cd "$ROOT"
# 确保 logs 存在并记录启动（launchd 下若不见日志可查 /tmp/start_htma.log）
mkdir -p "$ROOT/logs"
LOG_LINE="[$(date '+%Y-%m-%d %H:%M:%S')] start_htma.sh started ROOT=$ROOT PWD=$PWD"
echo "$LOG_LINE" >> "$ROOT/logs/start_htma.log" 2>/dev/null || true
echo "$LOG_LINE" >> /tmp/start_htma.log 2>/dev/null || true
# 先加载 .env，使 MYSQL_* 等对后续 mysql 命令和 Python 生效
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" 2>/dev/null && set +a
PYTHON_BIN="$ROOT/.venv/bin/python"
[ ! -x "$PYTHON_BIN" ] && echo "[start_htma] .venv not found: $ROOT/.venv" >> "$ROOT/logs/dashboard.err.log" && exit 78

# 确保表结构完整
"$PYTHON_BIN" "$ROOT/scripts/run_add_columns.py" 2>/dev/null || true
# 确保平台商品表、品类毛利汇总表存在（不执行 13：该脚本会 DROP 人力表，仅首次安装时手工执行一次）
mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" htma_dashboard < "$ROOT/scripts/08_create_platform_products.sql" 2>/dev/null || true
mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" htma_dashboard < "$ROOT/scripts/11_create_category_profit_summary.sql" 2>/dev/null || true
mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" htma_dashboard < "$ROOT/scripts/15_create_external_access_table.sql" 2>/dev/null || true
mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" htma_dashboard < "$ROOT/scripts/16_create_labor_category_mapping.sql" 2>/dev/null || true
mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" htma_dashboard < "$ROOT/scripts/20_add_distribution_mode_if_missing.sql" 2>/dev/null || true
mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" htma_dashboard < "$ROOT/scripts/21_add_consumer_insight_indexes.sql" 2>/dev/null || true
mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" htma_dashboard < "$ROOT/scripts/26_full_invoice_raw_tables.sql" 2>/dev/null || true

# 导出 .env 中的变量，确保飞书登录等配置被 Python 读到（含 launchd 等场景）
if [ -f "$ROOT/.env" ]; then
  set -a
  . "$ROOT/.env" 2>/dev/null || true
  set +a
  [ -z "$FEISHU_APP_ID" ] && export FEISHU_APP_ID="$(grep -m1 '^FEISHU_APP_ID=' "$ROOT/.env" 2>/dev/null | sed 's/^FEISHU_APP_ID=//' | tr -d '\r')"
  [ -z "$FEISHU_APP_SECRET" ] && export FEISHU_APP_SECRET="$(grep -m1 '^FEISHU_APP_SECRET=' "$ROOT/.env" 2>/dev/null | sed 's/^FEISHU_APP_SECRET=//' | tr -d '\r')"
  [ -z "$HTMA_PUBLIC_URL" ] && export HTMA_PUBLIC_URL="$(grep -m1 '^HTMA_PUBLIC_URL=' "$ROOT/.env" 2>/dev/null | sed 's/^HTMA_PUBLIC_URL=//' | tr -d '\r')"
fi
"$PYTHON_BIN" "$ROOT/scripts/check_feishu_env.py" 2>/dev/null || true
# 启动服务：-u 使 Python 立即输出便于 launchd 写日志
# 若 5002 被占用，请先执行: lsof -ti:5002 | xargs kill -9；再 launchctl unload + load 看板
echo "[$(date '+%Y-%m-%d %H:%M:%S')] starting python app.py" >> "$ROOT/logs/start_htma.log" 2>/dev/null || true
cd "$ROOT/htma_dashboard" && exec env FEISHU_APP_ID="${FEISHU_APP_ID}" FEISHU_APP_SECRET="${FEISHU_APP_SECRET}" HTMA_PUBLIC_URL="${HTMA_PUBLIC_URL}" "$PYTHON_BIN" -u app.py
