#!/usr/bin/env bash
# 每日自动比价 - 按当日（或昨日）销售 TOP 商品比价并推送飞书
# 供 OpenClaw / cron / Cursor 调度，无人值守执行。
# 默认接收人：余为军（8db735f2），可通过 FEISHU_AT_USER_ID 修改。

set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate
echo "执行每日比价（当日销售 TOP → 竞品比价 → 飞书推送）..."
python scripts/htma_nightly_price_compare.py
echo "完成。"
