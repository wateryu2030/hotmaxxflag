#!/bin/bash
# 使用项目虚拟环境运行去重脚本（避免系统 Python 无 pymysql）
set -e
cd "$(dirname "$0")/.."
if [ ! -f .venv/bin/python ]; then
    echo "未找到 .venv，正在创建并安装依赖..."
    bash scripts/ensure_venv.sh
fi
.venv/bin/python scripts/dedup_htma_tables.py "$@"
