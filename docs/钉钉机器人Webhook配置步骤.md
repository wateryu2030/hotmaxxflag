# 钉钉机器人 Webhook 配置步骤（先解决钉钉）

报告/比价等多通道推送需要钉钉群机器人 Webhook，按下面做一次即可，其他项目可复用同一套方式。

---

## 一、在钉钉里添加群机器人（约 2 分钟）

1. 打开 **钉钉**（手机或电脑均可），进入要接收报告的 **群聊**。
2. 点击右上角 **「···」** → **「群设置」**。
3. 找到 **「智能群助手」** 或 **「群机器人」** → **「添加机器人」**。
4. 选择 **「自定义」**（通过 Webhook 接入）。
5. 设置机器人名称（如「好特卖看板通知」），可选头像。
6. **安全设置**（三选一，推荐「加签」更安全）：
   - **加签**：钉钉会给出一个 **SEC 开头的密钥**，请复制保存，后面脚本要填。
   - 自定义关键词：例如填「报告」「看板」，消息里含该词才会发送（可选）。
   - IP 地址：限制只有指定服务器 IP 能发（有固定 IP 时可用）。
7. 完成创建后，钉钉会显示 **Webhook 地址**，形如：  
   `https://oapi.dingtalk.com/robot/send?access_token=xxxxxxxx`  
   **复制整段 URL**。

---

## 二、写入项目 .env（一次设置）

在项目根目录执行（二选一）：

**方式 A：直接传入 URL（加签时再传 SECRET）**

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag

# 仅 Webhook（未加签或用的关键词/IP）
bash scripts/set_dingtalk_webhook.sh 'https://oapi.dingtalk.com/robot/send?access_token=你复制的token'

# 加签模式（把 SEC 开头的密钥也填上）
bash scripts/set_dingtalk_webhook.sh 'https://oapi.dingtalk.com/robot/send?access_token=xxx' 'SECxxxxxxxx'
```

**方式 B：从剪贴板读取（macOS）**

1. 在钉钉页面复制 Webhook 地址。
2. 执行：`bash scripts/set_dingtalk_webhook.sh`
3. 若选了加签，脚本会提示输入 SEC 密钥，粘贴后回车即可。

脚本会把 `DINGTALK_WEBHOOK_URL`（和可选的 `DINGTALK_SECRET`）写入 `.env`。

---

## 三、验证

- 触发一次「发送报告」或「每日比价并推送」（例如看板里点发送、或调 API `?send=1` / `send_feishu: true`）。
- 钉钉群应收到同一条消息；若未收到，检查 .env 里 URL 和加签密钥是否正确、钉钉安全设置是否允许（加签必须填 `DINGTALK_SECRET`）。

---

## 四、小结

| 步骤       | 操作 |
|------------|------|
| 钉钉群添加机器人 | 群设置 → 智能群助手 → 添加机器人 → 自定义 → 复制 Webhook，加签则复制 SEC 密钥 |
| 写入 .env  | `bash scripts/set_dingtalk_webhook.sh 'WebhookURL' ['SEC密钥']` 或从剪贴板读取 |
| 生效       | 报告/比价发送时会同时推到飞书（若已配置）和该钉钉群 |

企业微信权限不够时，只配钉钉即可先解决钉钉推送；企微有权限后再配 `WECOM_WEBHOOK_URL` 即可三端齐发。
