#!/bin/bash
# 好特卖运营看板 - 启动脚本
# 执行: bash scripts/start_htma.sh 或 npm run htma:run

set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate

# 确保表结构完整
python scripts/run_add_columns.py 2>/dev/null || true

# 启动服务
cd htma_dashboard && exec python app.py
