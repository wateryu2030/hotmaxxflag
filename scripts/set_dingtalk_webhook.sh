#!/bin/bash
# 将钉钉自定义机器人 Webhook 写入项目 .env，供 notify_util / 报告 / 比价 多通道推送使用
# 用法：
#   1) 只设置 Webhook（安全设置选「自定义关键词」或「IP」时可只用 URL）：
#      bash scripts/set_dingtalk_webhook.sh 'https://oapi.dingtalk.com/robot/send?access_token=xxx'
#   2) 加签模式（安全设置选「加签」时必填 SECRET）：
#      bash scripts/set_dingtalk_webhook.sh 'https://oapi.dingtalk.com/robot/send?access_token=xxx' 'SECxxxxxxxx'
#   3) 从剪贴板读取（macOS）：先复制 Webhook 地址，再执行 bash scripts/set_dingtalk_webhook.sh
#      若选加签，第二行复制 SEC 开头的密钥，脚本会提示输入或第二次粘贴

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

# 第一个参数：Webhook URL
if [ -n "$1" ]; then
  URL="$1"
elif command -v pbpaste >/dev/null 2>&1; then
  URL="$(pbpaste 2>/dev/null | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  if [ -z "$URL" ]; then
    echo "剪贴板为空。请先在钉钉机器人页面复制 Webhook 地址，再执行本脚本。"
    echo "或直接运行: bash scripts/set_dingtalk_webhook.sh '你的webhook地址'"
    exit 1
  fi
  echo "已从剪贴板读取 Webhook（长度 ${#URL} 字符）"
else
  echo "请粘贴钉钉机器人 Webhook 地址（一行）："
  read -r URL
  URL="$(echo "$URL" | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
fi

# 第二个参数：加签密钥（可选）
SECRET="${2:-}"
if [ -z "$SECRET" ] && [ -z "$1" ]; then
  echo "若机器人安全设置选了「加签」，请粘贴 SEC 开头的密钥（没有则直接回车）："
  read -r SECRET
  SECRET="$(echo "$SECRET" | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
fi

if [ -z "$URL" ]; then
  echo "未输入 Webhook，退出。"
  exit 1
fi

# 校验格式
if [[ ! "$URL" =~ ^https://oapi\.dingtalk\.com/robot/send\? ]]; then
  echo "提示：钉钉 Webhook 形如: https://oapi.dingtalk.com/robot/send?access_token=xxx"
  echo "当前将写入: ${URL:0:55}..."
fi

# 写入或更新 .env
mkdir -p "$PROJECT_ROOT"
touch "$ENV_FILE"

remove_var() {
  local key="$1"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    grep -v "^${key}=" "$ENV_FILE" > "${ENV_FILE}.tmp"
    mv "${ENV_FILE}.tmp" "$ENV_FILE"
  fi
}

HAD_DINGTALK=false
remove_var "DINGTALK_WEBHOOK_URL"
remove_var "DINGTALK_SECRET"
if grep -q "^# 钉钉" "$ENV_FILE" 2>/dev/null; then
  HAD_DINGTALK=true
fi

if [ "$HAD_DINGTALK" = false ]; then
  echo "" >> "$ENV_FILE"
  echo "# 钉钉自定义机器人 Webhook（多通道通知）" >> "$ENV_FILE"
fi
echo "DINGTALK_WEBHOOK_URL=$URL" >> "$ENV_FILE"
if [ -n "$SECRET" ]; then
  echo "DINGTALK_SECRET=$SECRET" >> "$ENV_FILE"
  echo "已写入 .env：DINGTALK_WEBHOOK_URL、DINGTALK_SECRET（加签已配置）"
else
  echo "已写入 .env：DINGTALK_WEBHOOK_URL（未加签则无需 DINGTALK_SECRET）"
fi
echo "完成。报告/比价发送时将同时推送到飞书（若已配置）和该钉钉群。"
