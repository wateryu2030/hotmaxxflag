#!/usr/bin/env bash
# ============================================================
# 好特卖进销存营销分析 - 生成报告并发送飞书
# 供 OpenClaw 定时任务或 cron 调用
# 执行：./scripts/openclaw_send_marketing_report.sh
# 或：  curl "http://127.0.0.1:5002/api/marketing_report?send=1"
# ============================================================

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

# 方式一：直接运行 Python 脚本（推荐，不依赖看板服务）
echo "生成进销存营销分析报告并发送飞书..."
source "$PROJECT_ROOT/.venv/bin/activate" 2>/dev/null || true
python3 "$PROJECT_ROOT/scripts/htma_marketing_report.py" "$@"

# 方式二：若看板已启动，也可通过 API 触发：
# curl -s "http://127.0.0.1:5002/api/marketing_report?send=1" | head -5
