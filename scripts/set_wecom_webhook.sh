#!/bin/bash
# 将企业微信群机器人 Webhook 写入项目 .env，供 notify_util / 报告 / 比价 多通道推送使用
# 用法：
#   1) 复制 webhook 后执行（会从剪贴板读取，仅 macOS）：
#      bash scripts/set_wecom_webhook.sh
#   2) 或直接传入 URL：
#      bash scripts/set_wecom_webhook.sh 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx'

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

# 获取 webhook：参数 > 剪贴板(macOS) > 提示输入
if [ -n "$1" ]; then
  URL="$1"
elif command -v pbpaste >/dev/null 2>&1; then
  URL="$(pbpaste 2>/dev/null | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  if [ -z "$URL" ]; then
    echo "剪贴板为空。请先在企业微信机器人页面复制 Webhook，再重新执行本脚本。"
    echo "或直接运行: bash scripts/set_wecom_webhook.sh '你的webhook地址'"
    exit 1
  fi
  echo "已从剪贴板读取 Webhook（长度 ${#URL} 字符）"
else
  echo "请粘贴企业微信机器人 Webhook 地址（一行，回车结束）："
  read -r URL
  URL="$(echo "$URL" | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
fi

if [ -z "$URL" ]; then
  echo "未输入 Webhook，退出。"
  exit 1
fi

# 校验格式
if [[ ! "$URL" =~ ^https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key= ]]; then
  echo "提示：企微群机器人 Webhook 通常形如: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
  echo "当前将写入: ${URL:0:60}..."
fi

# 写入或更新 .env（避免 URL 中的 & 等字符破坏 sed）
mkdir -p "$PROJECT_ROOT"
touch "$ENV_FILE"

HAD_WECOM=false
if grep -q '^WECOM_WEBHOOK_URL=' "$ENV_FILE" 2>/dev/null; then
  HAD_WECOM=true
  grep -v '^WECOM_WEBHOOK_URL=' "$ENV_FILE" > "${ENV_FILE}.tmp"
  mv "${ENV_FILE}.tmp" "$ENV_FILE"
fi
if [ "$HAD_WECOM" = false ]; then
  echo "" >> "$ENV_FILE"
  echo "# 企业微信群机器人 Webhook（多通道通知）" >> "$ENV_FILE"
fi
echo "WECOM_WEBHOOK_URL=$URL" >> "$ENV_FILE"
echo "已写入 .env：WECOM_WEBHOOK_URL（报告/比价将同时推送到该企微群）"

echo "完成。报告/比价发送时将同时推送到飞书（若已配置）和该企业微信群。"
