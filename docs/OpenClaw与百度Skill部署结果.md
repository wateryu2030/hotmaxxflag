# OpenClaw 与百度 Skill 部署结果

本文记录本次自主检查与部署的执行结果及后续步骤。

---

## 已完成

1. **OpenClaw 源码**
   - 目录：`~/openclaw`（已从 GitHub 完整克隆）
   - 构建：`pnpm install`（使用用户可写缓存 `~/.npm-cache-user` 规避 npm 缓存 EACCES）、`pnpm run ui:build`、`pnpm run build`、`pnpm link --global`
   - 命令：`openclaw`、`clawhub` 已通过 `pnpm link --global` 安装到 `~/Library/pnpm`，需保证该目录在 PATH 中（如 `export PATH="$HOME/Library/pnpm:$PATH"`）

2. **OpenClaw 网关**
   - 已执行 `openclaw gateway install` 与 `openclaw gateway start`
   - 配置：`~/.openclaw/openclaw.json` 中已设置 `gateway.mode: "local"`，并自动生成 `gateway.auth.token`
   - 网关地址：`http://127.0.0.1:18789`，控制台需带 token 访问（见下）

3. **看板/自检与 Token**
   - 看板与自检脚本会**自动从 `~/.openclaw/openclaw.json` 读取 `gateway.auth.token`**，无需在 `.env` 中配置 `OPENCLAW_GATEWAY_TOKEN`（若已配置则优先使用环境变量）
   - 自检脚本 PATH 已包含 `~/Library/pnpm` 与 `~/.npm-global/bin`

---

## 默认模型：OpenAI 为主 + 国内/百炼回退（已修正 403 与 Unknown model）

因当前环境调用百炼（Anthropic）接口返回 **HTTP 403 forbidden: Request not allowed**（多为区域或账号策略限制），已将 **主模型改为 OpenAI**，保证 Chat 能正常回复；百炼仍放在回退链中，待 403 解决后可继续使用。

- **~/.openclaw/openclaw.json**：
  - `agents.defaults.model.primary` = `openai/gpt-4o-mini`
  - `agents.defaults.model.fallbacks` = `["volcengine/doubao-seed-1-8-251228", "volcengine/deepseek-v3-2-251201", "google/gemini-2.0-flash", "anthropic/claude-sonnet-4-5"]`
  - 说明：`google/gemini-pro` 已改为 `google/gemini-2.0-flash`（避免 Unknown model）；国内模型优先于 Google/百炼回退。
- **auth-profiles.json**：已配置 `anthropic:default`、`openai:default`（Key 来自项目 `.env`）
- **LaunchAgent plist**：已注入 `.env` 中所有用作备份的 API Key（含 ANTHROPIC、OPENAI、GEMINI、DEEPSEEK、VOLCANO_ENGINE）

请**完全关闭并重新打开 Chat 标签页**（或使用无痕窗口）访问：  
`http://127.0.0.1:18789/#token=0f93518130967e91396cf9000c57418e0cd3dac36791c5e8`  
再输入：**「请帮我安装百度电商比价 Skill」**。主模型为 OpenAI；若超时或失败会依次回退到豆包、DeepSeek、Gemini、百炼。

---

## 若出现 403 或 No API key

- **HTTP 403 forbidden: Request not allowed**：多为百炼/Anthropic 区域或账号策略限制，当前已改为 **OpenAI 为主模型**，可先正常使用 Chat；若需继续用百炼，请检查 Key 是否有效、是否需在控制台开通/绑定区域。
- **No API key found for provider "anthropic"**：见下方「解决 Chat 报错」配置 Key 或 plist 环境变量。

---

## 解决 Chat 报错：No API key found for provider anthropic

（当前主模型为 OpenAI，以下为需要单独使用 Anthropic 时的配置方式。）

在网页 Chat 里输入「请帮我安装百度电商比价 Skill」时，若出现 **"Agent failed before reply: No API key found for provider \"anthropic\"."**，说明当前 Agent 使用的对话模型（Anthropic/Claude）尚未配置 API Key，需要先配置再使用 Chat。

任选其一即可：

### 方式一：命令行粘贴 API Key（推荐）

在终端执行（需保证 `openclaw` 在 PATH 中，如 `export PATH="$HOME/Library/pnpm:$PATH"`）：

```bash
openclaw models auth paste-token --provider anthropic
```

按提示粘贴你的 **Anthropic API Key**（以 `sk-ant-` 开头）。完成后重启网关：

```bash
openclaw gateway stop
openclaw gateway start
```

然后重新打开 `http://127.0.0.1:18789/#token=<你的 gateway.auth.token>`，在 Chat 中再次输入「请帮我安装百度电商比价 Skill」。

### 方式二：交互式添加

```bash
openclaw models auth add
```

按提示选择 provider（anthropic）并输入或粘贴 API Key。完成后同样执行 `openclaw gateway stop` 再 `openclaw gateway start`。

### 方式三：环境变量（供 launchd 网关使用）

若希望网关进程通过环境变量读 Key，可在 **LaunchAgent plist** 中注入（不提交到仓库）：

- 编辑 `~/Library/LaunchAgents/ai.openclaw.gateway.plist`，在 `<dict>` 内增加：
  ```xml
  <key>EnvironmentVariables</key>
  <dict>
    <key>ANTHROPIC_API_KEY</key>
    <string>sk-ant-你的Key</string>
  </dict>
  ```
- 然后执行：
  ```bash
  launchctl unload ~/Library/LaunchAgents/ai.openclaw.gateway.plist
  launchctl load ~/Library/LaunchAgents/ai.openclaw.gateway.plist
  ```

**说明**：API Key 会写入 `~/.openclaw/agents/main/agent/auth-profiles.json`（方式一、二），或仅通过环境变量传给网关（方式三）。取得 Anthropic Key 可前往 [Anthropic 控制台](https://console.anthropic.com/)。

---

## 待你本地完成（百度 Skill）

- **CLI 安装**：`clawhub install baidu-preferred` / `clawhub install baidu-ecommerce-skill` 当前在注册中心返回「Skill not found」或「Rate limit exceeded」，因此未通过脚本自动安装。
- **推荐**：在 **OpenClaw 网页控制台** 用自然语言安装并启用百度电商/比价 Skill（**需先按上文配置好 Anthropic API Key**）：
  1. 在浏览器打开（将 `TOKEN` 替换为 `~/.openclaw/openclaw.json` 里 `gateway.auth.token` 的值）：
     ```text
     http://127.0.0.1:18789/#token=TOKEN
     ```
  2. 在对话框中输入例如：「请帮我安装百度电商比价 Skill」或「安装电商比价功能」。
  3. 安装并启用后，看板货盘比价会优先走网关 HTTP；若网关未暴露比价 tool，仍可在该 Chat 中让 AI 执行比价。

---

## 自检与看板

- **比价自检**（项目根目录执行）：
  ```bash
  bash scripts/run_selfserve_price_compare_debug.sh
  ```
  若网关已启动但未安装百度 Skill，步骤1 会提示「网关未找到可用比价 tool」；安装并启用 Skill 后再次运行自检即可验证。

- **看板 launchd**：若使用 `install_launchd_htma.sh`，请确保 PATH 含 `~/.npm-global/bin` 与 `~/Library/pnpm`，以便进程内可调用 `clawhub`/`openclaw`（见 [人力成本API与部署说明.md](./人力成本API与部署说明.md)）。

---

## 频道（Channel）与飞书、企业微信

OpenClaw 网关 **控制 → 频道** 中，内置支持的通道包括：

- **Telegram**、**Slack**、**Discord**、**WhatsApp**、**Google Chat**、**Signal**、**iMessage**、**Nostr** 等

在仪表盘 **设置 → 配置** 中可编辑 `channels.*`（如 `channels.slack`、`channels.telegram`），按 OpenClaw 文档为对应平台配置 Bot Token、Webhook 等即可接入。

**飞书、企业微信**：OpenClaw 当前**未内置**飞书或企业微信频道插件。本项目的做法是：

- **飞书**：由 **htma_dashboard 看板** 独立实现（登录、消息、审批等），见 `.env` 中 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 及 [人力成本API与部署说明.md](./人力成本API与部署说明.md)。若需 OpenClaw 与飞书打通，可考虑通过 OpenClaw 的 **Webhook/Inbound** 或自定义 Skill 对接飞书 API。
- **企业微信**：同样可在看板侧配置 `WECOM_WEBHOOK_URL` 等做通知；若需从企业微信触发 OpenClaw 对话，需自建中间服务（企业微信 → 你的服务 → OpenClaw 网关 API）。

---

## 参考

- [百度Skill比价环境说明.md](./百度Skill比价环境说明.md)
- [OpenClaw完整版重装方案.md](./OpenClaw完整版重装方案.md)
