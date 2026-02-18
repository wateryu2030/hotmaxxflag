#!/usr/bin/env bash
# OpenClaw 全权限自动执行：拼多多蚂蚁星球 apikey 申请与比价测试
# 使用 wateryu2030@gmail.com 注册
set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"
EMAIL="wateryu2030@gmail.com"

echo "=========================================="
echo "拼多多蚂蚁星球 - 自动申请与测试"
echo "=========================================="
echo ""

# 1. 打开开发者中心（京东联盟、淘宝授权、拼多多）
DEV_CENTER="https://www.haojingke.com/v1/member/openapi/index"
JD_URL="https://www.haojingke.com/index/api"
PDD_URL="https://www.haojingke.com/open-api/pdd"
echo "步骤1：打开开发者中心（京东、淘宝、拼多多授权）"
if command -v open &>/dev/null; then
  open "$DEV_CENTER" 2>/dev/null || true
  sleep 1
  open "$JD_URL" 2>/dev/null || true
  sleep 1
  open "$PDD_URL" 2>/dev/null || true
fi
echo "  请在开发者中心完成：京东联盟设置、淘宝授权设置、多多进宝设置"
echo ""

# 2. 检查 .env 是否已配置 apikey
ENV_FILE="$PROJECT_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  if grep -q "PDD_HOJINGKE_APIKEY=.\+" "$ENV_FILE" 2>/dev/null; then
    echo "步骤2：.env 已配置 PDD_HOJINGKE_APIKEY，执行比价测试"
    source .venv/bin/activate 2>/dev/null || true
    npm run htma:price_compare
  else
    echo "步骤2：请在 .env 中填入 apikey 后重新执行"
    echo "  PDD_HOJINGKE_APIKEY=你的apikey"
    echo ""
    echo "或执行: npm run htma:price_compare"
  fi
else
  echo "步骤2：.env 不存在，请从 .env.example 复制并配置"
  cp -n .env.example .env 2>/dev/null || true
  echo "  填入 PDD_HOJINGKE_APIKEY 后执行: npm run htma:price_compare"
fi

echo ""
echo "=========================================="
echo "完成"
echo "=========================================="
