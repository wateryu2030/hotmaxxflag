#!/bin/bash
# 在项目根目录创建 .venv 并安装依赖（解决 macOS Homebrew Python 的 externally-managed-environment）
set -e
cd "$(dirname "$0")/.."
if [ -f .venv/bin/python ]; then
    echo "虚拟环境已存在: .venv"
    exit 0
fi
echo "创建虚拟环境 .venv ..."
python3 -m venv .venv
.venv/bin/pip install -q -r htma_dashboard/requirements.txt
echo "完成。之后运行脚本请使用: .venv/bin/python scripts/xxx.py  或  source .venv/bin/activate && python scripts/xxx.py"
