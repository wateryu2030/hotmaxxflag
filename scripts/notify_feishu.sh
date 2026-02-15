#!/bin/bash
# 飞书通知脚本 - 导入完成后调用
# 使用: ./scripts/notify_feishu.sh "数据导入完成，销售额/毛利统计已更新"
# 可通过 FEISHU_WEBHOOK_URL 覆盖默认 webhook
msg="${1:-数据导入完成}"
url="${FEISHU_WEBHOOK_URL:-https://open.feishu.cn/open-apis/bot/v2/hook/1b21bad3-22cb-4d9d-8f38-32526bd69d49}"
curl -s -X POST "$url" \
  -H "Content-Type: application/json" \
  -d "{\"msg_type\":\"text\",\"content\":{\"text\":\"$msg\"}}"
