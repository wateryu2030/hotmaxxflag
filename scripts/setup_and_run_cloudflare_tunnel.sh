#!/bin/bash
# 使用 greatagain.com.cn 配置 Cloudflare 正式隧道并启动看板
# 需先执行一次: cloudflared tunnel login （在浏览器中选择 greatagain.com.cn 完成授权）

set -e
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

DOMAIN="greatagain.com.cn"
HOSTNAME="htma"
FINAL_URL="https://${HOSTNAME}.${DOMAIN}"
CONFIG_DIR="${HOME}/.cloudflared"
CONFIG_FILE="${CONFIG_DIR}/config.yml"

# 1. 检查是否已登录（存在 origin 证书）
ORIGINCERT=""
for p in "${CONFIG_DIR}/cert.pem" "${HOME}/.cloudflare-warp/cert.pem" "/usr/local/etc/cloudflared/cert.pem"; do
  if [ -f "$p" ]; then
    ORIGINCERT="$p"
    break
  fi
done
if [ -z "$ORIGINCERT" ]; then
  echo "=============================================="
  echo "本机尚未保存 Cloudflare 证书（~/.cloudflared/ 为空）。"
  echo "请按下面做（授权时终端必须一直开着）："
  echo ""
  echo "  1. 在本终端执行: cloudflared tunnel login"
  echo "  2. 浏览器打开后，用 377728157@qq.com 登录，"
  echo "     选择 greatagain.com.cn 并点击「授权」。"
  echo "  3. 不要关掉本终端，等终端里出现登录成功提示。"
  echo "  4. 再执行: bash scripts/setup_and_run_cloudflare_tunnel.sh"
  echo "=============================================="
  exit 1
fi

mkdir -p "$CONFIG_DIR"

# 2. 若隧道不存在则创建
TUNNEL_NAME="htma-dashboard"
if ! cloudflared tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
  echo "正在创建隧道 $TUNNEL_NAME ..."
  cloudflared tunnel create "$TUNNEL_NAME"
fi

# 3. 获取隧道 ID
TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | awk -v n="$TUNNEL_NAME" '$0~n {print $1}' | head -1)
if [ -z "$TUNNEL_ID" ]; then
  TUNNEL_ID=$(ls -t "${CONFIG_DIR}"/*.json 2>/dev/null | head -1)
  TUNNEL_ID=$(basename "$TUNNEL_ID" .json)
fi
if [ -z "$TUNNEL_ID" ] || [ ! -f "${CONFIG_DIR}/${TUNNEL_ID}.json" ]; then
  echo "无法获取隧道 ID，请确认已执行: cloudflared tunnel create $TUNNEL_NAME"
  exit 1
fi

CREDENTIALS_FILE="${CONFIG_DIR}/${TUNNEL_ID}.json"
echo "隧道 ID: $TUNNEL_ID"

# 4. 写入 config.yml
cat > "$CONFIG_FILE" << EOF
tunnel: $TUNNEL_NAME
credentials-file: $CREDENTIALS_FILE

ingress:
  - hostname: ${HOSTNAME}.${DOMAIN}
    service: http://127.0.0.1:5002
  - service: http_status:404
EOF
echo "已写入 $CONFIG_FILE"

# 5. DNS：若设置了 CLOUDFLARE_API_TOKEN 和 CLOUDFLARE_ZONE_ID 则自动添加，否则打印说明
TARGET="${TUNNEL_ID}.cfargotunnel.com"
if [ -n "$CLOUDFLARE_API_TOKEN" ] && [ -n "$CLOUDFLARE_ZONE_ID" ]; then
  echo "正在通过 API 添加 DNS 记录..."
  if curl -s -X POST "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "{\"type\":\"CNAME\",\"name\":\"${HOSTNAME}\",\"content\":\"${TARGET}\",\"ttl\":1,\"proxied\":true}" | grep -q '"success":true'; then
    echo "DNS 已添加: ${HOSTNAME}.${DOMAIN} -> ${TARGET}"
  else
    echo "API 添加 DNS 失败或记录已存在，请手动在 Cloudflare DNS 添加 CNAME: $HOSTNAME -> $TARGET"
  fi
else
  echo ""
  echo "=============================================="
  echo "请在 Cloudflare 添加一条 DNS 记录（若尚未添加）："
  echo "  登录 https://dash.cloudflare.com → 站点 greatagain.com.cn → DNS → 添加记录"
  echo "  类型: CNAME  名称: $HOSTNAME  目标: $TARGET  代理: 已代理"
  echo "=============================================="
  echo ""
fi

# 6. 释放 5002 并启动看板
pid=$(lsof -ti :5002 2>/dev/null)
if [ -n "$pid" ]; then
  echo "释放端口 5002（进程 $pid）..."
  kill -9 $pid 2>/dev/null
  sleep 1
fi

echo "启动看板（127.0.0.1:5002）..."
trap 'kill $(jobs -p) 2>/dev/null' EXIT INT TERM
bash scripts/start_htma.sh &
sleep 4
if ! lsof -i :5002 >/dev/null 2>&1; then
  echo "看板启动失败"
  exit 1
fi

echo "启动隧道（已启用防睡眠，锁屏不影响外网访问）..."
exec caffeinate -s -i -- cloudflared tunnel --config "$CONFIG_FILE" run "$TUNNEL_NAME"
