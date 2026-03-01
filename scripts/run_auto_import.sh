#!/bin/bash
# 从下载目录自动导入 Excel，并完成去重、刷新、数据质量检查（使用项目 .venv）
# 用法: bash scripts/run_auto_import.sh [目录]
# 默认目录: ~/Downloads（或环境变量 DOWNLOADS / IMPORT_DOWNLOADS_DIR）
set -e
cd "$(dirname "$0")/.."
if [ ! -f .venv/bin/python ]; then
    echo "未找到 .venv，正在创建并安装依赖..."
    bash scripts/ensure_venv.sh
fi
.venv/bin/python scripts/auto_import_from_downloads.py "$@"
