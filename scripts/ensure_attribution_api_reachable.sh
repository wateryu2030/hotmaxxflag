#!/usr/bin/env bash
# 自动化检查归因接口是否可达（部署/网关自检）。
# 用法: BASE_URL=https://htma.greatagain.com.cn bash scripts/ensure_attribution_api_reachable.sh
# 未传 BASE_URL 时默认 http://127.0.0.1:5002
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${BASE_URL:-http://127.0.0.1:5002}"
Q="start_date=2026-01-01&end_date=2026-01-31"
code() { curl -s -o /dev/null -w "%{http_code}" --connect-timeout 8 "${BASE}$1" 2>/dev/null || echo "000"; }

echo "检查归因 API: BASE=$BASE"
A=$(code "/api/mobile/analysis/attribution?${Q}")
B=$(code "/api/mobile/attribution?${Q}")
C=$(code "/api/wechat/mini/attribution?${Q}")
echo "  /api/mobile/analysis/attribution -> $A"
echo "  /api/mobile/attribution          -> $B"
echo "  /api/wechat/mini/attribution     -> $C (无 JWT 时 401 正常)"

if [ "$A" = "404" ] && [ "$B" = "404" ] && [ "$C" = "404" ]; then
  echo ""
  echo "失败: 三条路径均为 404。请在服务器同步本仓库代码并重启看板进程，然后重试。"
  echo "  参考: bash $ROOT/scripts/restart_dashboard_for_new_apis.sh"
  exit 1
fi
echo "OK: 至少一条路径非 404（生产需带小程序 JWT 测 200）。"
exit 0
