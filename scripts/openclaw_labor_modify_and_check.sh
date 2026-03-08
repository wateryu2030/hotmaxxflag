#!/usr/bin/env bash
# ============================================================
# OpenClaw 自动完成：人力成本修改及检查
# 1. 人力成本 Tab 前端修改已合入本仓库（index.html），本脚本通过部署使修改生效
# 2. 释放 5002 → 启动看板 → 验证 /api/labor_cost、/api/labor_cost_status
# 3. 可选：验证生产环境（传 base_url 或设置 HTMA_PUBLIC_URL）
#
# 用法（项目根目录）:
#   bash scripts/openclaw_labor_modify_and_check.sh
#   bash scripts/openclaw_labor_modify_and_check.sh https://htma.greatagain.com.cn
# 或由 OpenClaw 在对话中说「让 openclaw 自动完成人力成本修改及检查」后执行本脚本
# ============================================================

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

# 生产 base_url：优先脚本参数，否则用 .env 中的 HTMA_PUBLIC_URL（仅取 origin，不含路径）
BASE_REMOTE="${1:-}"
if [ -z "$BASE_REMOTE" ] && [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$PROJECT_ROOT/.env" 2>/dev/null || true
  set +a
  if [ -n "${HTMA_PUBLIC_URL:-}" ]; then
    BASE_REMOTE="${HTMA_PUBLIC_URL}"
  fi
fi

echo "=============================================="
echo "OpenClaw：人力成本修改及检查"
echo "=============================================="
echo ""
echo "说明：人力成本 Tab 前端修改（401 提示、滚动、无数据说明等）已合入 htma_dashboard/static/index.html"
echo "      本脚本将重启看板使修改生效，并校验接口与数据状态。"
echo ""

bash "$PROJECT_ROOT/scripts/deploy_and_verify_labor.sh" ${BASE_REMOTE:+"$BASE_REMOTE"}

echo ""
echo "OpenClaw 人力成本修改及检查 已完成。"
echo "  若需浏览器内验证：打开 http://127.0.0.1:5002 → 登录 → 点击「人力成本」Tab，报表月份留空点「查询」查看最近月份。"
echo "=============================================="
