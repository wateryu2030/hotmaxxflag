#!/bin/bash
# OpenClaw 自动化：修复看板日志目录与 launchd 启动，并验证 5002 / labor_analysis
# 执行: bash scripts/openclaw_fix_dashboard_and_verify.sh
# 在项目根目录执行，或传入项目根路径为第一个参数
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${1:-$(cd "$SCRIPT_DIR/.." && pwd)}"
cd "$ROOT"
AGENTS="$HOME/Library/LaunchAgents"
DASHBOARD_PLIST="com.htma.dashboard.plist"

echo "=============================================="
echo "OpenClaw: 修复看板启动与日志并验证"
echo "=============================================="
echo "项目根: $ROOT"
echo ""

# 1. 确保 logs 目录存在
echo ">>> 1. 创建 logs 目录"
mkdir -p "$ROOT/logs"
touch "$ROOT/logs/.keep" 2>/dev/null || true
echo "    logs: $ROOT/logs"
echo ""

# 2. 重新安装 launchd（会 mkdir logs 并生成 plist）
echo ">>> 2. 重新安装 launchd 服务"
bash "$ROOT/scripts/install_launchd_htma.sh"
echo ""

# 3. 仅重启看板（unload + load）
echo ">>> 3. 重启看板进程"
launchctl unload "$AGENTS/$DASHBOARD_PLIST" 2>/dev/null || true
sleep 2
launchctl load "$AGENTS/$DASHBOARD_PLIST"
echo ""

# 4. 等待进程启动并写日志（launchd 含 5 秒延迟，故多等一会）
echo ">>> 4. 等待看板启动（最多 45 秒）"
for i in $(seq 1 45); do
  if [ -f "$ROOT/logs/start_htma.log" ]; then
    echo "    start_htma.log 已生成"
    break
  fi
  [ $i -eq 45 ] && echo "    警告: 未发现 start_htma.log，请检查 launchd 与脚本路径"
  sleep 1
done
for i in $(seq 1 35); do
  if command -v curl >/dev/null 2>&1 && curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "http://127.0.0.1:5002/" 2>/dev/null | grep -q '200\|301\|302\|401'; then
    echo "    看板已响应 (HTTP 200/302)"
    break
  fi
  [ $i -eq 35 ] && echo "    警告: 5002 未在 35 秒内响应"
  sleep 1
done
echo ""

# 5. 输出日志位置与最近内容
echo ">>> 5. 日志文件"
if [ -f /tmp/start_htma.log ]; then
  echo "    /tmp/start_htma.log (launchd 下脚本至少执行过):"
  tail -10 /tmp/start_htma.log 2>/dev/null | sed 's/^/    /'
  echo ""
fi
for f in start_htma.log dashboard.out.log dashboard.err.log; do
  p="$ROOT/logs/$f"
  if [ -f "$p" ]; then
    echo "    存在: $p"
    echo "    --- 最后 5 行 ---"
    tail -5 "$p" 2>/dev/null | sed 's/^/    /'
  else
    echo "    不存在: $p"
  fi
  echo ""
done

# 6. 验证端口、labor_analysis、消费洞察走势 API（GET 不得 405）
echo ">>> 6. 验证接口"
CODE_ROOT=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://127.0.0.1:5002/" 2>/dev/null) || echo "000"
CODE_LABOR=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://127.0.0.1:5002/labor_analysis" 2>/dev/null) || echo "000"
echo "    /         -> HTTP $CODE_ROOT"
echo "    /labor_analysis -> HTTP $CODE_LABOR"
if bash "$ROOT/scripts/openclaw_verify_consumer_insight_trend.sh" "http://127.0.0.1:5002" 2>/dev/null; then
  echo "    /api/consumer_insight_trend (GET) -> 通过"
else
  echo "    /api/consumer_insight_trend (GET) -> 未通过（405 等）"
fi
echo ""

if [ "$CODE_ROOT" = "200" ] || [ "$CODE_ROOT" = "302" ] || [ "$CODE_ROOT" = "401" ]; then
  echo "=============================================="
  echo "看板已就绪"
  echo "=============================================="
  echo "本机: http://127.0.0.1:5002/"
  echo "人力分析: http://127.0.0.1:5002/labor_analysis"
  echo "日志: $ROOT/logs/"
  echo ""
  [ "$CODE_LABOR" != "200" ] && [ "$CODE_LABOR" != "302" ] && [ "$CODE_LABOR" != "403" ] && echo "提示: /labor_analysis 返回 $CODE_LABOR，若需 200 请确认已部署最新代码并仅由 launchd 占用 5002。"
  exit 0
else
  echo "=============================================="
  echo "看板未就绪 (HTTP $CODE_ROOT)"
  echo "=============================================="
  echo "请查看: tail -50 $ROOT/logs/dashboard.err.log"
  echo "        tail -50 $ROOT/logs/start_htma.log"
  echo "        cat /tmp/start_htma.log   # launchd 下脚本是否执行"
  echo "若 5002 被占用: lsof -ti:5002 | xargs kill -9 后重新执行本脚本"
  exit 1
fi
