#!/bin/bash
# 使用项目 .venv 清空看板历史数据（便于重新上传）
set -e
cd "$(dirname "$0")/.."
if [ ! -f .venv/bin/python ]; then
    echo "未找到 .venv，请先运行: bash scripts/ensure_venv.sh"
    exit 1
fi
.venv/bin/python scripts/clear_htma_data.py "$@"
