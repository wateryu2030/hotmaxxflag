#!/bin/bash
# 好特卖看板 - 一键上线部署（含锁屏防睡眠、看板与隧道重启、自检与可选飞书通知）
# 执行: bash scripts/deploy_htma_live.sh
# 保证：锁屏/息屏状态下防睡眠服务保持运行，看板与隧道照常可用。
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
KEEPAWAKE_PLIST="com.htma.keepawake.plist"
DASHBOARD_PLIST="com.htma.dashboard.plist"
TUNNEL_PLIST="com.htma.tunnel.plist"
TOKEN_FILE="$PROJECT_ROOT/.tunnel-token"

cd "$PROJECT_ROOT"
[ -f .env ] && set -a && . ./.env 2>/dev/null && set +a

echo "=============================================="
echo "好特卖看板 - 一键上线部署"
echo "=============================================="

# 1. 虚拟环境与依赖
if [ ! -f "$PROJECT_ROOT/.venv/bin/python" ]; then
  echo ">>> 创建 .venv 并安装依赖..."
  bash "$PROJECT_ROOT/scripts/ensure_venv.sh"
else
  echo ">>> .venv 已存在"
fi

# 2. 数据库表结构（仅建表/加列，不清空业务数据）
# 注意：不执行 13_create_labor_cost_table.sql（内含 DROP TABLE，会清空人力明细）；人力表仅首次安装时手工执行一次，日常部署用 run_add_columns 补列即可。
echo ">>> 执行数据库迁移与建表（保留历史数据）..."
python scripts/run_add_columns.py 2>/dev/null || true
for sql in scripts/08_create_platform_products.sql scripts/11_create_category_profit_summary.sql scripts/15_create_external_access_table.sql scripts/16_create_labor_category_mapping.sql scripts/17_add_labor_mapping_sales_category_mid.sql scripts/18_add_labor_mapping_category_codes.sql scripts/20_add_distribution_mode_if_missing.sql scripts/21_add_consumer_insight_indexes.sql; do
  [ -f "$PROJECT_ROOT/$sql" ] && mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" "${MYSQL_DATABASE:-htma_dashboard}" < "$PROJECT_ROOT/$sql" 2>/dev/null || true
done
echo "    表结构已就绪（人力明细表未触碰，历史数据保留）"

# 3. 安装/更新 launchd 服务（防睡眠 + 看板 + 隧道），并重启以加载新代码
echo ">>> 安装 launchd 服务并重启（保证锁屏状态下系统不睡眠、看板与隧道可用）..."
bash "$PROJECT_ROOT/scripts/install_launchd_htma.sh"

# 4. 等待服务就绪（给足时间：MySQL/导入较慢时需 20–30 秒）
echo ">>> 等待看板端口就绪..."
for i in $(seq 1 30); do
  if command -v curl >/dev/null 2>&1 && curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://127.0.0.1:5002/" 2>/dev/null | grep -q '200\|301\|302\|401'; then
    echo "    看板已响应 (127.0.0.1:5002)"
    break
  fi
  [ $i -eq 30 ] && echo "    警告: 端口 5002 未在 30 秒内响应，请检查 logs/dashboard.err.log 并确认无其他进程占用 5002"
  sleep 1
done
echo ">>> 校验人力分析页..."
LABOR_ANALYSIS_CODE=""
for _ in 1 2 3 4 5; do
  sleep 2
  if command -v curl >/dev/null 2>&1; then
    LABOR_ANALYSIS_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 4 "http://127.0.0.1:5002/labor_analysis" 2>/dev/null) || true
    [ -z "$LABOR_ANALYSIS_CODE" ] && LABOR_ANALYSIS_CODE="000"
  fi
  if [ "$LABOR_ANALYSIS_CODE" = "200" ] || [ "$LABOR_ANALYSIS_CODE" = "302" ] || [ "$LABOR_ANALYSIS_CODE" = "403" ]; then
    echo "    人力分析页正常 (HTTP $LABOR_ANALYSIS_CODE)"
    break
  fi
  [ "$LABOR_ANALYSIS_CODE" != "" ] && echo "    重试中... HTTP $LABOR_ANALYSIS_CODE"
done
if [ "$LABOR_ANALYSIS_CODE" != "200" ] && [ "$LABOR_ANALYSIS_CODE" != "302" ] && [ "$LABOR_ANALYSIS_CODE" != "403" ]; then
  printf '    提示: /labor_analysis 返回 HTTP %s（若看板已能访问，可忽略；否则请查看 logs/dashboard.err.log）\n' "$LABOR_ANALYSIS_CODE"
  # 不 exit 1，避免部署“成功”但看板已起来时仍报错退出
fi

# 5. 可选：飞书通知（企业外审批功能已启用）
if [ -n "$(grep -m1 '^FEISHU_WEBHOOK_URL=' .env 2>/dev/null | sed 's/^FEISHU_WEBHOOK_URL=//' | tr -d '\r')" ]; then
  echo ">>> 发送飞书上线通知..."
  .venv/bin/python scripts/notify_feishu_external_approval_feature_done.py 2>/dev/null || true
else
  echo ">>> 未配置 FEISHU_WEBHOOK_URL，跳过飞书通知"
fi

echo ""
echo "=============================================="
echo "部署完成"
echo "=============================================="
echo "• 防睡眠: 已启用（锁屏/息屏后本机不睡眠，看板与隧道持续运行）"
echo "• 看板:    http://127.0.0.1:5002"
echo "• 外网:    https://htma.greatagain.com.cn（已配置隧道时）"
echo "• 审批:    https://htma.greatagain.com.cn/approval（仅超级管理员）"
echo "• 人力分析: https://htma.greatagain.com.cn/labor_analysis"
echo ""
echo "锁屏状态下可正常使用：防睡眠服务会阻止系统睡眠，请勿手动停止 com.htma.keepawake。"
echo "若外网访问 /labor_analysis 仍 404，请在本机（运行看板的那台机器）执行本部署脚本以重启进程并加载新代码。"
echo ""
