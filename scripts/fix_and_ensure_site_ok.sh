#!/bin/bash
# 一键修复并确保 https://htma.greatagain.com.cn 与飞书登录可用
# 会：重新安装 launchd（注入 .env）→ 重启看板+隧道 → 健康检查 → 成功则飞书通知余为军
# 用法: bash scripts/fix_and_ensure_site_ok.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."
AGENTS="$HOME/Library/LaunchAgents"
DASHBOARD_PLIST="$AGENTS/com.htma.dashboard.plist"
TUNNEL_PLIST="$AGENTS/com.htma.tunnel.plist"

echo "=== 1. 重新安装 launchd（注入 .env，确保飞书与公网域名生效）==="
bash "$SCRIPT_DIR/install_launchd_htma.sh"

echo ""
echo "=== 2. 等待看板就绪并自检 ==="
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if lsof -i :5002 >/dev/null 2>&1; then
    break
  fi
  echo "  等待端口 5002 ... ($i/15)"
  sleep 1
done
if ! lsof -i :5002 >/dev/null 2>&1; then
  echo "  失败: 端口 5002 未监听。请查看: tail -50 logs/dashboard.err.log"
  exit 1
fi
sleep 2
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:5002/api/health" 2>/dev/null || echo "000")
if [ "$HTTP" != "200" ]; then
  echo "  警告: /api/health 返回 $HTTP，请检查 logs/dashboard.err.log"
  exit 1
fi
echo "  本地看板正常: http://127.0.0.1:5002 (health $HTTP)"

echo ""
echo "=== 3. 飞书通知余为军（看板已恢复）==="
[ -f .env ] && set -a && . ./.env 2>/dev/null && set +a
if [ -x .venv/bin/python ]; then
  .venv/bin/python "$SCRIPT_DIR/notify_feishu_site_recovered.py" 2>/dev/null || echo "  飞书通知跳过（未配置 FEISHU_WEBHOOK_URL 或发送失败）"
else
  python3 "$SCRIPT_DIR/notify_feishu_site_recovered.py" 2>/dev/null || true
fi

echo ""
echo "=== 完成 ==="
echo "  看板: http://127.0.0.1:5002"
echo "  外网: https://htma.greatagain.com.cn （隧道已随 install 启动则可用）"
echo "  已尝试飞书通知余为军，请验证站点与飞书登录。"
echo "  日志: tail -f logs/dashboard.out.log logs/dashboard.err.log"
