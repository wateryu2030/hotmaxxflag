#!/usr/bin/env bash
# ============================================================
# OpenClaw 自主执行：比价策略自动运行并重试，直到成功
# 1. 可选同步平台商品表
# 2. 执行货盘比价
# 3. 校验输出含「分析完成」且无致命错误则退出；否则重试（最多 MAX_TRY 次）
# 执行：bash scripts/openclaw_auto_price_compare.sh
# ============================================================

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"
MAX_TRY=3
RETRY_DELAY=15

echo "=========================================="
echo "OpenClaw 自主比价 - 自动重试直到成功"
echo "=========================================="

# 1. 确保表存在（可选，需 MySQL 命令行）
if command -v mysql &>/dev/null; then
  mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" htma_dashboard -e "SELECT 1 FROM t_htma_price_compare LIMIT 1;" 2>/dev/null || true
  [ -f scripts/08_create_platform_products.sql ] && mysql -h "${MYSQL_HOST:-127.0.0.1}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-62102218}" htma_dashboard < scripts/08_create_platform_products.sql 2>/dev/null || true
fi

attempt=1
while [ $attempt -le $MAX_TRY ]; do
  echo ""
  echo "--- 第 $attempt 次执行（共 $MAX_TRY 次）---"
  output=""
  if output=$(bash scripts/openclaw_price_compare.sh 2>&1); then
    if echo "$output" | grep -q "分析完成"; then
      echo "$output"
      echo ""
      echo "=========================================="
      echo "比价策略已成功执行"
      echo "=========================================="
      exit 0
    fi
  fi
  echo "$output"
  echo ""
  echo "未检测到「分析完成」或执行异常，${RETRY_DELAY}s 后重试..."
  [ $attempt -lt $MAX_TRY ] && sleep $RETRY_DELAY
  attempt=$((attempt + 1))
done

echo "=========================================="
echo "已达最大重试次数 $MAX_TRY，请检查 MySQL / .env / 网络"
echo "=========================================="
exit 1
