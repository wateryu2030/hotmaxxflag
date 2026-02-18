#!/usr/bin/env bash
# OpenClaw 可执行：拼多多比价配置与测试
# 1. 打开蚂蚁星球申请页（需人工申请 apikey）
# 2. 执行 price_compare 测试
set -e
cd "$(dirname "$0")/.."
echo "=========================================="
echo "拼多多比价 - 配置与测试"
echo "=========================================="
echo ""
echo "步骤1：申请 apikey"
echo "  请打开 https://www.haojingke.com/open-api/pdd 注册并申请"
echo "  申请成功后，将 apikey 填入 .env 的 PDD_HOJINGKE_APIKEY="
echo ""
if command -v open &>/dev/null; then
  open "https://www.haojingke.com/open-api/pdd" 2>/dev/null || true
fi
echo "步骤2：执行比价测试"
echo ""
source .venv/bin/activate 2>/dev/null || true
npm run htma:price_compare
echo ""
echo "=========================================="
echo "完成"
echo "=========================================="
