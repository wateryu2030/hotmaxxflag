#!/bin/bash
# 删除销售/库存/毛利表中的「合计/总计/小计」等汇总行（无商品、仅合并结果），避免重复计算
# 用法: bash scripts/run_delete_summary_rows.sh [--dry-run]
set -e
cd "$(dirname "$0")/.."
if [ ! -f .venv/bin/python ]; then
    echo "未找到 .venv，正在创建并安装依赖..."
    bash scripts/ensure_venv.sh
fi
.venv/bin/python scripts/delete_summary_rows.py "$@"
