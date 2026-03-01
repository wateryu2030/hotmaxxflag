# OpenClaw 飞书 + 企业微信 + 钉钉 三通道配置与复用

一次设置，OpenClaw 与各业务项目均可使用：**飞书、企业微信、钉钉** 传递信息，无需把全部应用迁到飞书。

---

## 一、两种使用场景

| 场景 | 说明 | 配置位置 |
|------|------|----------|
| **A. OpenClaw 对话通道** | 在企微/钉钉/飞书群里与 OpenClaw 对话、收发言 | `~/.openclaw/openclaw.json` 的 `channels` + 对应插件 |
| **B. 项目多通道推送** | 报告、比价、导入完成等消息同时发到飞书+企微+钉钉 | 项目 `.env` + 本仓库 `notify_util.py` |

A 负责「人和 AI 在哪聊」，B 负责「系统通知发到哪些群」。可只做 A、只做 B，或两者都做。

---

## 二、A. OpenClaw 通道配置（对话用）

### 2.1 飞书（你已启用）

- 插件：`@m1heng-clawd/feishu`，已在 `~/.openclaw/openclaw.json` 的 `channels.feishu` 与 `plugins.entries.feishu` 中启用。
- 需保留：`appId`、`appSecret`，`connectionMode: "websocket"`。

### 2.2 企业微信（你已启用）

- 插件：`openclaw-plugin-wecom`（扩展目录下为 `openclaw-plugin-wecom`，wecom 为软链）。
- 配置：`channels.wecom` 中 `token`、`encodingAesKey`（来自企微应用「接收消息」配置）。
- 若收/发异常：检查企微应用「接收消息」URL 是否指向 OpenClaw 网关（如 `http(s)://你的域名:18789` 或内网 IP），并确认 IP 白名单。

### 2.3 钉钉（按需启用）

- OpenClaw 支持钉钉通道（Stream 模式，无需公网回调）。
- **安装**：在 OpenClaw 管理界面（默认 `http://127.0.0.1:18789`）→ Channels → 添加 DingTalk，或命令行：
  ```bash
  openclaw config set channels.dingtalk.clientId <你的钉钉应用 ClientID>
  openclaw config set channels.dingtalk.clientSecret <你的钉钉应用 ClientSecret>
  ```
- **创建钉钉应用**：钉钉开放平台 → 应用开发 → 企业内部应用 → 创建（机器人/H5 等），获取 ClientID / ClientSecret，并开通「接收消息」等权限。
- 在 `openclaw.json` 中确保 `plugins.entries.dingtalk` 与 `channels.dingtalk` 启用（若使用插件形式，以官方文档为准）。

**一次配置**：上述 `openclaw.json` 与插件安装好后，所有使用该 OpenClaw 实例的项目都能在飞书/企微/钉钉里与 AI 对话，无需按项目再配。

---

## 三、B. 项目多通道推送（报告/通知发到三个渠道）

适用于：进销存报告、比价结果、导入完成等「同一条消息希望飞书+企微+钉钉都收到」。

### 3.1 本仓库已提供的工具

- **`htma_dashboard/notify_util.py`**  
  - `send_feishu(...)`：飞书（沿用现有 `feishu_util`）  
  - `send_wecom(text)`：企业微信群机器人  
  - `send_dingtalk(text)`：钉钉自定义机器人  
  - `notify_all(text, title=...)`：**一次调用，按 .env 配置同时发飞书+企微+钉钉**

### 3.2 环境变量（.env，复制自 .env.example）

| 变量 | 说明 | 示例 |
|------|------|------|
| `FEISHU_WEBHOOK_URL` | 飞书群机器人 Webhook | `https://open.feishu.cn/open-apis/bot/v2/hook/xxx` |
| `FEISHU_AT_USER_ID` | 飞书 @ 的人 open_id | `ou_8db735f2` |
| `FEISHU_AT_USER_NAME` | 飞书 @ 显示名 | `余为军` |
| `WECOM_WEBHOOK_URL` | 企微群机器人 Webhook | `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx` |
| `DINGTALK_WEBHOOK_URL` | 钉钉机器人 Webhook（含 access_token） | `https://oapi.dingtalk.com/robot/send?access_token=xxx` |
| `DINGTALK_SECRET` | 钉钉加签密钥（安全设置选「加签」时必填） | `SECxxxx` |

### 3.3 获取 Webhook（一次设置）

**飞书**  
- 群设置 → 群机器人 → 添加自定义机器人 → 复制 Webhook URL。

**企业微信**  
- 群聊 → 右键「添加群机器人」→ 新建机器人 → 复制 Webhook（形如 `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx`）。

**钉钉**  
- 群设置 → 智能群助手 → 添加机器人 → 自定义 → 安全设置选「加签」并保存密钥；复制 Webhook URL（含 `access_token`）。  
- 若选加签，在 .env 中填 `DINGTALK_SECRET`，`notify_util` 会自动签名。

### 3.4 在代码里使用（本项目与其他项目）

**只发飞书（保持现有逻辑）：**  
- 继续用 `feishu_util.send_feishu` 或 `notify_util.send_feishu` 即可。

**同时发飞书 + 企微 + 钉钉：**  
```python
from htma_dashboard.notify_util import notify_all

results, all_ok = notify_all("进销存报告：今日销售额 xxx，毛利 xxx……", title="好特卖进销存营销分析")
# results["feishu"], results["wecom"], results["dingtalk"] 分别为 (True/False, None/错误信息)
```

其他项目：复制 `notify_util.py` 到该项目，按 3.2 配置 .env，同样调用 `notify_all(...)` 即可复用。

### 3.5 与 OpenClaw / 脚本的配合

- **OpenClaw 定时任务**：可执行 `scripts/openclaw_send_marketing_report.sh` 等；若脚本或 API 内部改为调用 `notify_all`，则报告会同时到飞书+企微+钉钉。
- **API**：例如营销报告接口在「发送」分支里改为 `notify_all(report, title="…")`，即可多通道推送。

---

## 四、小结

- **OpenClaw 对话**：在 `~/.openclaw/openclaw.json` 配好飞书/企微/钉钉通道与插件，一次设置，所有项目共享该 OpenClaw 的对话能力。  
- **项目通知**：在项目 .env 中配置三个 Webhook（可选只配其中一两个），使用本仓库的 `notify_util.notify_all`，即可一次发送到飞书+企微+钉钉；其他项目复制 `notify_util.py` 与 .env 示例即可复用。

这样无需把基于微信/钉钉的应用迁到飞书，OpenClaw 与业务脚本都能自动衔接三端。
