#!/usr/bin/env bash
# 用「直连、不走系统代理」的方式启动 Google Chrome 打开飞书授权页，
# 解决 Chrome 报 ERR_CONNECTION_CLOSED、而终端 curl 正常的问题（多为 Chrome/扩展走了 127.0.0.1 代理）。
#
# 用法（项目根，需本机看板已跑在 5002 或公网可访问）:
#   bash scripts/open_feishu_login_chrome_direct.sh
# 或手动指定完整授权 URL（与浏览器地址栏一致）:
#   bash scripts/open_feishu_login_chrome_direct.sh 'https://accounts.feishu.cn/open-apis/authen/v1/authorize?...'
#
# 环境变量:
#   HTMA_PUBLIC_URL  若本机 5002 不可用，用其拉取 /api/auth/feishu_url（如 https://htma.greatagain.com.cn）
#   NEXT_PATH        默认 /login，传给 feishu_url 的 next 参数
set -euo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ -f "$ROOT/.env" ]; then set -a && . "$ROOT/.env" 2>/dev/null && set +a; fi

NEXT="${NEXT_PATH:-/login}"
AUTH_URL=""

if [ -n "${1:-}" ]; then
  AUTH_URL="$1"
else
  for base in "http://127.0.0.1:5002" "${HTMA_PUBLIC_URL:-}"; do
    [ -z "$base" ] && continue
    base="${base%/}"
    code="$(curl -sS -G -o /tmp/feishu_auth.json -w "%{http_code}" --connect-timeout 5 --max-time 15 \
      --data-urlencode "next=$NEXT" "$base/api/auth/feishu_url" 2>/dev/null || echo "000")"
    if [ "$code" = "200" ] && python3 -c "import json; d=json.load(open('/tmp/feishu_auth.json')); import sys; sys.exit(0 if d.get('success') and d.get('url') else 1)" 2>/dev/null; then
      AUTH_URL="$(python3 -c "import json; print(json.load(open('/tmp/feishu_auth.json'))['url'])")"
      echo "已从 $base 获取授权链接"
      break
    fi
  done
  rm -f /tmp/feishu_auth.json
fi

if [ -z "$AUTH_URL" ]; then
  echo "错误: 无法获取飞书授权 URL。请：" >&2
  echo "  1) 启动看板: bash scripts/restart_htma_dashboard.sh" >&2
  echo "  2) 或将完整 authorize 链接作为第一个参数传入本脚本" >&2
  exit 1
fi

CHROME=""
for c in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"; do
  if [ -x "$c" ]; then CHROME="$c"; break; fi
done
if [ -z "$CHROME" ]; then
  echo "错误: 未找到 Google Chrome（请安装到 /Applications）" >&2
  exit 1
fi

echo "正在以「无代理」方式启动 Chrome（新窗口）…"
echo "若仍失败，请在 Chrome 地址栏打开: chrome://settings/system 关闭「使用计算机的代理设置」。"

# --no-proxy-server: 忽略系统/环境代理，与终端 curl 行为接近
# --new-window: 单独窗口便于扫码
# 可选 CHROME_EXTRA_ARGS 追加，例如: CHROME_EXTRA_ARGS="--disable-extensions" bash ...
# shellcheck disable=SC2086
"$CHROME" --no-proxy-server --new-window ${CHROME_EXTRA_ARGS:-} "$AUTH_URL" &
echo "已在后台启动 Chrome（无代理）。若未弹出窗口，请从「聚焦」或程序坞点开 Chrome。"
