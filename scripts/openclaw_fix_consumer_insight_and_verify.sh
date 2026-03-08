#!/usr/bin/env bash
# OpenClaw 自动化：修复消费洞察（distribution_mode / 占位符）并验证。
# 1. 重启看板使代码生效
# 2. 校验 /api/consumer_insight 与 /api/consumer_insight_trend 不返回 500，无 405
# 3. 可选：打开消费洞察页做页面校验（需 node + playwright）
#
# 用法（项目根目录）:
#   bash scripts/openclaw_fix_consumer_insight_and_verify.sh
#   bash scripts/openclaw_fix_consumer_insight_and_verify.sh http://127.0.0.1:5002
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"
BASE_URL="${1:-http://127.0.0.1:5002}"
BASE_URL="${BASE_URL%/}"

echo "=============================================="
echo "OpenClaw: 消费洞察修复与验证"
echo "=============================================="
echo "项目根: $ROOT"
echo "看板:   $BASE_URL"
echo ""

echo ">>> 0. 确保 distribution_mode 列存在（t_htma_product_master）"
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" 2>/dev/null && set +a
if mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" "${MYSQL_DATABASE:-htma_dashboard}" < "$ROOT/scripts/20_add_distribution_mode_if_missing.sql" 2>/dev/null; then
  echo "    已执行 20_add_distribution_mode_if_missing.sql"
else
  echo "    mysql 执行失败，尝试 Python 补齐..."
  "$ROOT/.venv/bin/python" -c "
from htma_dashboard.db_config import get_conn
from htma_dashboard.import_logic import _ensure_product_master_distribution_mode
_ensure_product_master_distribution_mode(get_conn())
print('    Python 已补齐 distribution_mode 列')
" 2>/dev/null || true
fi
echo ""

echo ">>> 1. 重启看板（launchd）"
AGENTS="$HOME/Library/LaunchAgents"
PLIST="com.htma.dashboard.plist"
launchctl unload "$AGENTS/$PLIST" 2>/dev/null || true
sleep 2
launchctl load "$AGENTS/$PLIST"
echo "    已执行 launchctl unload/load"
echo ""

echo ">>> 2. 等待看板就绪（最多 25 秒）"
for i in $(seq 1 25); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "$BASE_URL/" 2>/dev/null) || echo "000"
  if [ "$CODE" = "200" ] || [ "$CODE" = "302" ] || [ "$CODE" = "401" ]; then
    echo "    就绪 (HTTP $CODE)"
    break
  fi
  [ $i -eq 25 ] && { echo "    超时"; exit 1; }
  sleep 1
done
echo ""

echo ">>> 3. 校验消费洞察相关 API（不允许 405/500）"
if bash "$ROOT/scripts/openclaw_verify_consumer_insight_apis.sh" "$BASE_URL"; then
  echo "    API 校验通过"
else
  echo "    API 校验未通过，请检查 app.py 并重启"
  exit 1
fi
echo ""

echo ">>> 4. 消费洞察页校验（打开 ?page=insight&category=服装）"
if node "$ROOT/scripts/openclaw_verify_consumer_insight_page.mjs" "$BASE_URL" 2>/dev/null; then
  echo "    页面校验通过"
else
  echo "    页面校验未执行或未通过（需 node + playwright）"
fi
echo ""

echo "=============================================="
echo "消费洞察修复与验证 已完成"
echo "  若仍出现「Unknown column distribution_mode」或「not all arguments converted」，请确认："
echo "  1. app.py 已保存且无未提交修改"
echo "  2. 已执行本脚本完成重启"
echo "  3. 浏览器强制刷新（Ctrl+Shift+R）或清缓存后重试"
echo "=============================================="
