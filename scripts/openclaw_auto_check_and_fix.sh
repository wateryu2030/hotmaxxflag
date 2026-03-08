#!/usr/bin/env bash
# ============================================================
# OpenClaw 自动检查并修改完善
# 1. 运行人力成本+飞书检查（若本地未启动会跳过 [2][3]）
# 2. 部署并验证看板（重启 5002、校验接口）
# 3. 再次运行检查，确认 [2][3] 通过
# 4. KPI 自定义日期检查
# 5. 人力成本与 KPI 剥离校验（主导航无人力 Tab，入口为数据导入·人力成本）
# 6. 消费洞察走势 API 校验（GET /api/consumer_insight_trend 须为 200/401，不得 405）
# 7. 消费洞察页校验（打开 ?page=insight&category=服装，检查无 500/加载失败文案）
#
# 用法（项目根目录）:
#   bash scripts/openclaw_auto_check_and_fix.sh
#   bash scripts/openclaw_auto_check_and_fix.sh https://htma.greatagain.com.cn
# 或: npm run htma:openclaw-check
# ============================================================

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

echo "=============================================="
echo "OpenClaw：自动检查并修改完善"
echo "=============================================="

echo ""
echo ">>> [1/7] 人力成本 + 飞书 检查（首次）"
echo ""
if [ -n "${1:-}" ]; then
  .venv/bin/python scripts/openclaw_labor_feishu_check.py "$1" || true
else
  .venv/bin/python scripts/openclaw_labor_feishu_check.py || true
fi

echo ""
echo ">>> [2/7] 部署并验证看板（重启 5002、校验 /api/labor_cost）"
echo ""
if [ -n "${1:-}" ]; then
  bash scripts/openclaw_labor_modify_and_check.sh "$1"
else
  bash scripts/openclaw_labor_modify_and_check.sh
fi

echo ""
echo ">>> [3/7] 人力成本 + 飞书 检查（再次，确认本地 [2] 通过）"
echo ""
if [ -n "${1:-}" ]; then
  .venv/bin/python scripts/openclaw_labor_feishu_check.py "$1" || true
else
  .venv/bin/python scripts/openclaw_labor_feishu_check.py || true
fi

echo ""
echo ">>> [4/7] KPI 自定义时间起点检查（需已安装 Playwright 浏览器）"
echo ""
BASE_URL="${1:-https://htma.greatagain.com.cn}"
if node scripts/openclaw_check_kpi_custom_date.mjs "$BASE_URL" 2>/dev/null; then
  echo "KPI 自定义日期检查通过。"
else
  echo "未执行或未通过。可先运行: npx playwright install chromium"
  echo "再执行: npm run htma:check-kpi-date 或 node scripts/openclaw_check_kpi_custom_date.mjs $BASE_URL"
fi

echo ""
echo ">>> [5/7] 人力成本与 KPI 剥离校验（主导航无人力 Tab，入口为数据导入·人力成本）"
echo ""
if node scripts/openclaw_verify_labor_stripped.mjs "$BASE_URL" 2>/dev/null; then
  echo "人力成本剥离设计校验通过。"
else
  echo "未执行或未通过。可执行: node scripts/openclaw_verify_labor_stripped.mjs $BASE_URL"
fi

echo ""
echo ">>> [6/7] 消费洞察走势 API（GET 不得 405）"
echo ""
LOCAL_URL="http://127.0.0.1:5002"
if bash scripts/openclaw_verify_consumer_insight_trend.sh "$LOCAL_URL" 2>/dev/null; then
  echo "消费洞察走势 API 校验通过。"
else
  echo "未通过。请确认已保存 app.py 并重启看板，再执行: bash scripts/openclaw_verify_consumer_insight_trend.sh $LOCAL_URL"
  exit 1
fi

echo ""
echo ">>> [7/7] 消费洞察页（打开 ?page=insight&category=服装 检查无 500/加载失败）"
echo ""
if node scripts/openclaw_verify_consumer_insight_page.mjs "$LOCAL_URL" 2>/dev/null; then
  echo "消费洞察页校验通过。"
else
  echo "未通过或未执行（需 node + playwright）。可执行: node scripts/openclaw_verify_consumer_insight_page.mjs $LOCAL_URL"
fi

echo ""
echo "=============================================="
echo "OpenClaw 自动检查并修改完善 已完成。"
echo "  看板: http://127.0.0.1:5002"
echo "  若 [4] 明细表无数据，请到「数据导入」上传人力成本 Excel 或运行 scripts/openclaw_labor_import_and_notify.py"
echo "=============================================="
