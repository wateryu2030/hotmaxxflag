#!/usr/bin/env bash
# 验证本机/服务器看板已部署含 /api/mobile/* 的新路由（非 404 即表示 Flask 已加载 routes_mobile）
# 用法: bash scripts/verify_mobile_api_routes.sh
# 可选: BASE_URL=http://127.0.0.1:5002 bash scripts/verify_mobile_api_routes.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

BASE="${BASE_URL:-http://127.0.0.1:5002}"
Q="start_date=2020-01-01&end_date=2026-12-31"

code() {
  curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "${BASE}$1" 2>/dev/null || echo "000"
}

echo "检查 Mobile API: BASE=$BASE"
C1=$(code "/api/mobile/dashboard?days=7")
C2=$(code "/api/mobile/category_large?${Q}")
C3=$(code "/api/mobile/trend?metric=sale&days=7")
C4=$(code "/api/mobile/analysis/attribution?start_date=2026-01-01&end_date=2026-01-31")
C4b=$(code "/api/mobile/attribution?start_date=2026-01-01&end_date=2026-01-31")
C5=$(code "/api/mobile/alerts/list?days=7")
C6=$(code "/api/mobile/ai_daily/latest")
C7=$(code "/api/wechat/mini/attribution?start_date=2026-01-01&end_date=2026-01-31")
echo "  /api/mobile/dashboard?days=7     -> HTTP $C1"
echo "  /api/mobile/category_large?...  -> HTTP $C2"
echo "  /api/mobile/trend?...           -> HTTP $C3"
echo "  /api/mobile/analysis/attribution -> HTTP $C4"
echo "  /api/mobile/attribution (alias)  -> HTTP $C4b"
echo "  /api/mobile/alerts/list         -> HTTP $C5"
echo "  /api/mobile/ai_daily/latest     -> HTTP $C6"
echo "  /api/wechat/mini/attribution    -> HTTP $C7 (无 Cookie 时 401 亦可接受)"

# 200=正常；401/403=鉴权；501=如缺表仍表示「路由在」
for v in "$C1" "$C2" "$C3" "$C4" "$C4b" "$C5" "$C6"; do
  if [ "$v" = "404" ]; then
    echo ""
    echo "失败: 存在 HTTP 404。请在跑看板的那台机子上 git pull/同步本仓库，然后:"
    echo "  bash $ROOT/scripts/openclaw_restart_dashboard_and_verify.sh"
    echo "或（若用 launchd）: launchctl unload/ load com.htma.dashboard 或 bash scripts/restart_dashboard_for_new_apis.sh"
    exit 1
  fi
done
echo "OK: 无 404，mobile 路由已注册。"
exit 0
