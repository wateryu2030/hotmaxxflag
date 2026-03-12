# 百度 Skill 比价环境说明

看板「货盘比价」已优先使用**百度优选 Skill** 获取京东/淘宝/唯品会价格，无需配置万邦 OneBound Key。按下列步骤确保本机环境可用即可。

**clawhub 上已无 baidu-preferred**：若你希望**优先用百度 Skill**（如手机端已可用），请直接看 **[百度Skill优先-无clawhub方案.md](./百度Skill优先-无clawhub方案.md)**，通过配置 `OPENCLAW_BAIDU_SKILL_GATEWAY_URL` 指向已可用的网关即可，无需再尝试 `clawhub install baidu-preferred`。

---

## 0. 一键验证（推荐先做）

在项目根目录执行以下脚本，可**不依赖 ClawHub 安装**即确认比价能否出结果（数据来自百度优选 MCP）：

```bash
bash scripts/verify_baidu_skill.sh
```

脚本会：检查 `.env` 中的 `BAIDU_YOUXUAN_TOKEN`、写入 OpenClaw 的 `projectRoot`、并调用 runner 做一次比价测试。若输出「通过: runner 返回了比价数据」，则看板货盘比价已能正常出结果（网关不可用时走同一 runner）。

**可选**：若希望同时尝试从 ClawHub 安装百度 Skill（可能遇限流），可加 `--install`：

```bash
bash scripts/verify_baidu_skill.sh --install
```

限流时稍后重试，或使用下方「通过 OpenClaw 网页版自然语言安装」。

**排查「百度 Skill 被忽略」**：若比价有结果但希望确认当前走的是 Skill 还是百度优选 MCP，可执行：

```bash
bash scripts/diagnose_baidu_skill.sh
```

脚本会检查：网关是否可达、clawhub 是否有 run 子命令、是否已安装 Skill、BAIDU_YOUXUAN_TOKEN 是否配置，并做一次实际调用输出 `source=baidu_skill` 或 `source=baidu_youxuan_mcp`。常见原因与解决办法见脚本末尾总结。

**重要**：网关可达性依赖本机 127.0.0.1，请在**系统终端（沙箱外）**执行上述脚本；在 Cursor 内置终端或沙箱内可能误报「网关不可达」。

**页面「请求失败: Failed to fetch」或 curl 返回 Unauthorized**：看板后端请求网关时必须带正确的 Bearer token。请在项目根目录的 `.env` 中配置：

- `OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789`（看板与网关同机时；若看板在别的机器则填该机可访问的网关地址）
- `OPENCLAW_GATEWAY_TOKEN=<token>`，其中 `<token>` 从 `~/.openclaw/openclaw.json` 的 **gateway.auth.token** 复制，或从 OpenClaw 控制台「Web UI (with token)」链接里 `#token=` 后面的字符串复制。

配置后重启看板进程。验证网关是否接受该 token（在**本机**执行，token 需替换为实际值）：

```bash
curl -sS -X POST http://127.0.0.1:18789/tools/invoke \
  -H "Authorization: Bearer $(node -e "var c=require('fs').readFileSync(process.env.HOME+'/.openclaw/openclaw.json','utf8'); var j=JSON.parse(c); console.log(((j.gateway||{}).auth||{}).token||'')")" \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_price_comparison","args":{"query":"洽洽坚果"}}'
```

若返回中含 `"data"` 和价格则说明 token 正确；若仍为 `{"error":{"type":"unauthorized"}}` 请确认 token 与 openclaw.json 中一致。

**京东/淘宝分平台比价**：当前回退到百度优选 MCP 时，MCP 只返回一个聚合最低价（platform 为「百度优选」），不会单独列出京东、淘宝字段。若需要表格中分别显示「京东最低价」「淘宝最低价」，请使用**完整版 OpenClaw + 百度 Skill**（推荐一键脚本）：

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag   # 或你的项目根目录
bash scripts/setup_full_openclaw_baidu_skill.sh
```

按脚本提示完成 `openclaw onboard --install-daemon` 与 `enable_baidu_skill_gateway.sh --install-skill` 后，`clawhub run` 会返回多平台数据，看板自动解析并展示 jd_min_price、taobao_min_price。详见 [OpenClaw完整版重装方案.md](./OpenClaw完整版重装方案.md) 第 9.1 节。  
若暂不安装完整版，可配置 OneBound（ONEBOUND_KEY/ONEBOUND_SECRET），在百度 Skill 不可用时看板会回退到万邦并同时拉取京东与淘宝（见 `baidu_fetcher.get_configured_fetcher(dual_platform=True)`）。

---

## 让百度 Skill 被调用（京东/淘宝分平台）

**推荐**：在项目根目录执行一键脚本，完成完整版 OpenClaw 安装与百度 Skill 配置，使 `clawhub run` 可用并返回多平台（京东/淘宝等），看板自动展示 jd_min_price、taobao_min_price：

```bash
bash scripts/setup_full_openclaw_baidu_skill.sh
```

按脚本提示完成 `openclaw onboard --install-daemon` 与 `enable_baidu_skill_gateway.sh --install-skill` 即可。

---

若希望**手动**分步操作，可按下述顺序进行。

### 第一步：安装完整版 OpenClaw（本机未安装 openclaw 时必做）

完整版提供 `openclaw`、`clawhub run` 和网关，npm 版只有 `clawhub search/install` 且无网关。

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag   # 或你的项目根目录
bash scripts/reinstall_openclaw_full.sh
```

脚本会：卸载旧版（若有）→ 检查 Node.js 22+ 与 pnpm → 克隆/下载 OpenClaw 源码 → `pnpm install`、`pnpm build`、`pnpm link --global`。若 `openclaw` 仍找不到，把 pnpm 全局 bin 加入 PATH：

```bash
export PATH="$(pnpm root -g)/../bin:$PATH"
# 可写入 ~/.zshrc 后 source ~/.zshrc
```

然后执行**配置向导**（必做一次）：

```bash
openclaw onboard --install-daemon
```

按提示选择 QuickStart、配置 API Key、安装 Skills。详见 [OpenClaw完整版重装方案.md](./OpenClaw完整版重装方案.md)。

### 第二步：启用网关并写入 projectRoot

安装并完成 onboard 后，在项目根目录执行：

```bash
bash scripts/enable_baidu_skill_gateway.sh
```

该脚本会：写入 `~/.openclaw/openclaw.json` 的 `projectRoot`（供 baidu-price-tools 插件调 runner）→ 启动 OpenClaw 网关（`openclaw gateway start`）。可选加 `--install-skill` 尝试安装百度 Skill：

```bash
bash scripts/enable_baidu_skill_gateway.sh --install-skill
```

### 第三步：验证

```bash
bash scripts/diagnose_baidu_skill.sh
```

期望：【1】网关可达；【2】clawhub 有 run；【5】若已安装 Skill 且 run 成功，会显示 `source=baidu_skill`。看板货盘比价会优先请求 `http://127.0.0.1:18789/tools/invoke`，再由网关调用 runner（runner 内先试 clawhub run，再 MCP）。

若 ClawHub 限流导致 `clawhub install baidu-preferred` 失败，可稍后重试，或到 OpenClaw 网页（http://127.0.0.1:18789）用自然语言说「安装百度电商比价 Skill」。

---

## 1. 安装 OpenClaw / ClawHub

任选其一，保证终端可执行 **`clawhub`**（且看板进程的 PATH 中也能找到）。

### 方式 A：官方 OpenClaw 一键安装（含完整运行时时可用时推荐）

```bash
curl -sSL https://openclaw.ai/install | bash
openclaw --version
clawhub -h
```

若该安装页不可用（如返回 404），请改用方式 B。安装成功后 ClawHub 会随 OpenClaw 一起可用，且可能支持通过 OpenClaw 运行时调用 Skill（含「运行」能力）。

### 方式 B：仅安装 ClawHub CLI（npm）

```bash
npm install -g clawhub
```

若执行 `clawhub` 提示「未找到命令」，说明 npm 全局 bin 不在 PATH 中，任选其一：

**方法 1（推荐）— 一键修复当前终端并写入配置：**

```bash
source scripts/ensure_clawhub_path.sh
# 或
bash scripts/ensure_clawhub_path.sh
```

之后执行 `clawhub -h` 即可。

**方法 2 — 手动：**

```bash
export PATH="$HOME/.npm-global/bin:$PATH"   # 当前终端生效
# 长期生效：把上面一行写入 ~/.zshrc 或 ~/.bashrc，然后 source ~/.zshrc
```

**方法 3 — 不改 PATH，用 npx：**

```bash
npx clawhub -h
npx clawhub install <slug>
```

**说明**：当前 npm 版 ClawHub CLI 主要提供 `search`、`install`、`list`、`update` 等，**不包含 `run` 子命令**。看板比价会**优先走网关 HTTP → 再尝试 clawhub run**；当 clawhub run 不可用时，**runner 会自动回退到百度优选 MCP**（需在 `.env` 中配置 `BAIDU_YOUXUAN_TOKEN`），无需万邦即可拿到比价数据。若希望使用完整版 `clawhub run`，请采用**方式 A** 安装完整 OpenClaw。

---

## 2. 安装百度电商 Skill（可选，用于将来 clawhub run 可用时）

在**项目根目录**或希望安装 Skill 的工作目录下执行（可先执行 `bash scripts/verify_baidu_skill.sh --install` 自动尝试）：

```bash
clawhub install baidu-preferred --workdir . --dir skills
# 或
clawhub install baidu-ecommerce-skill --workdir . --dir skills
```

若遇到「Rate limit exceeded」，为 ClawHub 注册中心限流，请**稍后重试**或使用下方「通过 OpenClaw 网页版自然语言安装」。**注意**：当前在 ClawHub 搜索 "baidu" 仅返回 baidu-search、baidu-baike-data、baidu-scholar-search 等，电商比价 Skill 的 slug 可能为 **baidu-preferred** 或已更名。建议：
- **优先用 [OpenClaw 网页版自然语言安装](#通过-openclaw-网页版自然语言安装推荐避免-cli-限流)**（见下方），或  
- 在 [clawhub.ai](https://clawhub.ai/) 搜索「电商」「ecommerce」「比价」等确认百度电商 Skill 的**准确 slug** 后再执行 `clawhub install <准确slug>`。

安装完成后，Skill 会出现在 `./skills/<slug>/`（或你所设 `--dir`）。通过 OpenClaw 会话或官方支持的「运行」方式调用该 Skill。

### 通过 OpenClaw 网页版自然语言安装（推荐，避免 CLI 限流）

若命令行遇到限流或未配置好，可用 **OpenClaw 网页版** 用自然语言让 AI 代为安装：

1. **访问 OpenClaw 网页版**  
   通常是 `http://你的服务器IP:18789`（或你部署的 OpenClaw 地址）。

2. **在对话框中输入**（任选其一）：
   - 明确指定 slug：  
     **「请帮我安装百度电商 Skill，slug 是 baidu-ecommerce-skill」**
   - 或更简单：  
     **「我想安装电商比价功能」**

3. OpenClaw 会自动执行安装；安装完成后，看板货盘比价即可优先使用该 Skill。

**若 127.0.0.1:18789 一直转圈、打不开网页**，可依次排查：

1. **当前没有运行中的容器**（`docker ps` 无输出）且 **端口 18789 被占用**（如被 Docker 占用）  
   本机若是 **npm 安装的 OpenClaw**（`which openclaw` 有输出）：
   - 先释放 18789：关闭占用该端口的程序（如 Docker Desktop），或执行 `lsof -ti :18789 | xargs kill`（确认无重要服务后再杀）；
   - 再启动网关：`openclaw gateway start`（若未安装服务可先执行 `openclaw gateway install`），然后访问 `http://127.0.0.1:18789`。
   - **若本机没有 docker-compose**：说明 OpenClaw 不是用本项目里的 Docker 跑的，不要在本项目目录执行 `docker compose up -d`；用上面的 `openclaw gateway start` 即可。

2. **有容器但页面仍无响应**  
   端口被占用但 HTTP 无响应时：`docker ps` 找到映射 18789 的容器 → `docker logs <容器名>` 看报错 → `docker restart <容器名>` 后重试。

3. **网关启动后马上退出：Missing OPENAI_API_KEY**  
   `openclaw gateway start` 后进程立即退出，且 `~/.openclaw/logs/gateway.err.log` 报 **Missing env var "OPENAI_API_KEY"** 时，说明 launchd 启动的网关没有读到该变量（launchd 不会读项目或用户目录下的 `.env`）。任选其一修复：
   - **做法 A（推荐）**：在 LaunchAgent 的 plist 中注入 `OPENAI_API_KEY`。可从项目 `.env` 取键值并写入 plist：
     ```bash
     # 从项目 .env 读取并添加到 plist（需已安装 openclaw gateway）
     python3 -c "
     import subprocess
     p='/Volumes/ragflow/hotmaxx/hotmaxxflag/.env'
     pl='$HOME/Library/LaunchAgents/ai.openclaw.gateway.plist'
     v=next((l.split('=',1)[1].strip().strip('\"\'') for l in open(p) if l.startswith('OPENAI_API_KEY=')), None)
     subprocess.run(['/usr/libexec/PlistBuddy','-c','Add :EnvironmentVariables:OPENAI_API_KEY string '+v], pl, capture_output=True)
     "
     launchctl unload ~/Library/LaunchAgents/ai.openclaw.gateway.plist
     launchctl load ~/Library/LaunchAgents/ai.openclaw.gateway.plist
     openclaw gateway start
     ```
   - **做法 B**：若 OpenClaw 支持从 `~/.openclaw/.env` 读配置，可把 `OPENAI_API_KEY=sk-...` 写入该文件（注意不要提交到仓库）；然后 `openclaw gateway start`。若仍报错，则需用做法 A 在 plist 中显式注入。

4. **页面能打开但显示 Health Offline、Disconnected、gateway token missing**  
   说明网关进程在跑，但控制台（Control UI）未带令牌，无法通过 WebSocket 认证。任选其一：
   - **推荐**：用**带 token 的地址**打开仪表盘（token 与 `gateway.auth.token` 一致，默认 `123456`）：  
     **http://127.0.0.1:18789/#token=123456**  
     若你改过令牌，先查当前值：`openclaw config get gateway.auth.token`，再把上面 URL 里的 `123456` 换成该值。
   - **一劳永逸**：在 `~/.openclaw/openclaw.json` 的 `gateway` 段中增加 `remote.token`，与 `auth.token` 保持一致，例如：
     ```json
     "gateway": {
       "remote": { "token": "123456" },
       "auth": { "token": "123456" }
     }
     ```
     保存后执行 `openclaw gateway stop` 再 `openclaw gateway start`（或 `launchctl kickstart gui/$UID/ai.openclaw.gateway`），然后仍建议用带 `#token=...` 的 URL 打开仪表盘。

---

## 3. 看板运行环境能调起 clawhub

- 看板进程（或启动脚本）的 **PATH** 里要能找到 `clawhub`（或使用其绝对路径）。
- **若用 launchd 启动看板**：launchd 默认 PATH 可能不包含 npm 全局 bin，需在 plist 的 `EnvironmentVariables` 中设置 `PATH`，或使用 `clawhub` 的**绝对路径**（如 `which clawhub` 或 `$(npm root -g)/../bin/clawhub`）。
- 建议在与看板**相同用户、相同环境**下做自检（见第 5 节）。

---

## 4. 无需再配万邦

- 货盘比价**优先使用百度 Skill**，可不配置或删除 `.env` 中的：
  - `ONEBOUND_KEY`
  - `ONEBOUND_SECRET`
- 即使万邦 Key 过期，只要百度 Skill 可用，比价即可正常显示京东/淘宝/唯品会价格。

---

## 5. 自检

在**与看板相同的运行环境**下（同一用户、若用 launchd 则尽量用相同 PATH）执行：

```bash
clawhub run baidu-ecommerce-skill --query "洽洽坚果"
```

（若本机仅有 npm 版 ClawHub 且无 `run` 命令，该步会报错「未知命令」；此时需按方式 A 安装完整 OpenClaw 或确认官方文档中「运行 Skill」的用法。）

- **若返回内容中包含京东/淘宝等平台价格**：说明百度 Skill 已生效；在前端再执行一次「货盘比价」即可看到竞品价，不再全部「独家款」。
- **若报错「未找到 clawhub」**：需将 `clawhub` 所在目录加入 PATH（见第 1 节方式 B），或使用 `npx clawhub`。
- **若报错 Skill 未安装或调用失败**：请先执行 `clawhub install baidu-ecommerce-skill`，再重试。

---

## 6. 看板 launchd 与 PATH

若看板由 **launchd** 启动（执行过 `bash scripts/install_launchd_htma.sh`），脚本会在 plist 中注入 **PATH**，使看板进程能找到 `clawhub`（要求本机存在 `$HOME/.npm-global/bin`）。重新执行一次安装脚本即可生效：

```bash
bash scripts/install_launchd_htma.sh
```

---

## 7. 自助执行脚本

在项目根目录执行以下脚本，可自动完成「clawhub 检查 → 搜索百度 Skill → 安装 → 说明自检」：

```bash
bash scripts/setup_baidu_skill_selfserve.sh
```

若遇 ClawHub 限流，脚本会提示稍后重试或到 clawhub.ai 查 slug 后手动安装。

### 定时重试（直至完成）

需要**隔一段时间自动重试安装、直至成功**时，可安装 launchd 定时任务：

```bash
bash scripts/install_launchd_retry_baidu_skill.sh
```

- 每 **15 分钟**执行一次 `retry_baidu_skill_until_done.sh`，尝试安装百度电商 Skill。
- **安装成功后**会在项目根目录创建 `.baidu_skill_installed`，之后每次执行直接退出，不再重复安装。
- 若需重新尝试，删除该文件后定时任务会继续重试：`rm .baidu_skill_installed`
- 日志：`logs/retry_baidu_skill.log`、`logs/retry_baidu_skill.out.log`、`logs/retry_baidu_skill.err.log`

### 比价自检（OpenClaw 自助执行与调试）

在项目根目录执行自检脚本，可模拟看板环境验证「网关 HTTP → clawhub run」链是否可用：

```bash
bash scripts/run_selfserve_price_compare_debug.sh
# 或（需 PATH 含 ~/.npm-global/bin）：python3 scripts/selfserve_price_compare_debug.py
```

脚本会执行：步骤1 网关 HTTP 比价 → 步骤2 call_baidu_skill → 步骤3 item_fetcher 单条 → 步骤4 run_full_pipeline 小规模。若当前为 **npm 版 ClawHub + 网关**，网关通常未暴露 `get_price_comparison` 给 HTTP，且 clawhub 无 `run`，自检会提示「当前环境限制」并建议：在 OpenClaw 网页 Chat 中让 AI 执行比价，或配置万邦 Key。详见脚本末尾输出与上文「方式 A / 方式 B」说明。

---

## 8. OpenClaw Chat 常见问题（模型顺序 / LLM 超时 / Skill 脚本）

在 OpenClaw 网页 Chat（如 `http://127.0.0.1:18789/#token=<token>`）中若出现以下情况，可按下述方式排查。

### 8.1 主模型与回退顺序（百炼 → DeepSeek → 豆包 → OpenAI）

- 在 `~/.openclaw/openclaw.json` 的 `agents.defaults.model` 中已配置：
  - **primary**：`anthropic/claude-sonnet-4-5`（百炼）
  - **fallbacks**：`volcengine/deepseek-v3-2-251201`（DeepSeek）→ `volcengine/doubao-seed-1-8-251228`（豆包）→ `openai/gpt-4o-mini`（OpenAI）
- 说明：豆包需在**火山引擎 Ark 控制台**开通对应模型，否则会 404；回退链中已将 DeepSeek 置于豆包前，以便境内优先用 DeepSeek。
- 主模型无响应或失败时，会按上述顺序自动回退。

### 8.2 「LLM request timed out」

- **原因**：当前主模型或回退模型请求超时，多为网络延迟或 API 响应慢。
- **处理**：
  1. 在 Chat 中重发或缩短问题长度；回退链会依次尝试豆包、DeepSeek、OpenAI。
  2. 确认本机网络可访问对应 API；若百炼/OpenAI 不稳定，可依赖豆包、DeepSeek。
  3. 网关日志：`~/.openclaw/logs/gateway.err.log`，可查看 `timeout`、`fallback` 等关键字。

### 8.3 Skill 脚本报错（declare / jq 找不到键 / exit code 2）

- **原因**：OpenClaw 本机 Skill（如 `~/openclaw/skills/baidu-shopping-comparison/baidu-compare.sh`）中 shell 语法或 `jq` 解析与当前 API 返回格式不一致，会导致 `declare` 用法错误、jq 找不到键、Command exited with code 2。
- **处理**：到 `~/openclaw/skills/<skill-name>/` 下检查并修改对应脚本，使 `declare`、`jq` 等与真实返回结构对齐；或暂时使用该 Skill 的模拟输出。
- **重要**：**看板「货盘比价」不依赖 Chat 内这段 Skill 脚本**，只依赖看板后端的**百度 Skill 封装**（`htma_dashboard/baidu_skill_compare.py`）或万邦；Chat 内比价仅用于手动测试或调试。

### 8.4 网关未暴露比价 tool（看板仍全部「独家款」）

- 看板侧**优先走网关** POST `/tools/invoke`（与 Chat 同源）；**网关不可用时自动执行与 Chat 相同的 runner**：`scripts/openclaw_baidu_tools_runner.py get_price_comparison`（即 baidu-price-tools 插件调用的同一脚本），无需网关暴露 tool 也能拿到百度 Skill 比价结果。
- **请务必调通百度 Skill 路径**（其它数据源不可靠时）：
  1. **在 OpenClaw 中加载 baidu-price-tools 并配置 projectRoot**：在项目根目录执行 `bash scripts/setup_openclaw_baidu_tools.sh`，脚本会把 `plugins.load.paths` 与 `plugins["baidu-price-tools"].projectRoot` 写入 `~/.openclaw/openclaw.json`。
  2. **重启网关**：`openclaw gateway restart` 或 launchd 的 `launchctl bootout ... && launchctl bootstrap ...`，使插件生效。
  3. 若网关仍不暴露 tool，看板会**自动用子进程调用同一 runner**，与 Chat 使用百度 Skill 时一致；只要本机能成功执行 `python3 scripts/openclaw_baidu_tools_runner.py get_price_comparison '洽洽坚果'` 且返回 JSON 含 `data`，看板比价即可出数。
- 若仍全部「独家款」：确认 runner 依赖的数据源（百度优选 MCP / OneBound / 聚合 / 蚂蚁星球）至少有一项在 .env 中已配置且有效；或使用 Chat 内让 AI 执行比价作对比。

---

## 9. OpenClaw 可用性检查报告（示例）

以下为一次**彻底检查**的结论，便于对照当前环境。

### 9.1 网关是否可用

- **结论**：OpenClaw 网关**可用**（`http://127.0.0.1:18789` 返回 200）。
- **但**：`POST /tools/invoke` 请求 `get_price_comparison` 或 `search_products` 时，网关返回 **「网关未找到可用比价 tool」**。即网关未向 HTTP 暴露上述比价工具，通常是因为当前加载的 Skill 未向网关注册这些 tool 名称，或 Skill 未以「可供 /tools/invoke 调用」的方式加载。

### 9.2 百度 Skill 能否模糊查询「伊利宫酪奶皮子酸奶风味酸乳138g」

- **结论**：**当前不能**。原因同上——看板后端通过网关 `POST /tools/invoke` 调用比价（精确 + 模糊），网关未暴露 `get_price_comparison`/`search_products`，因此：
  - 精确查询、模糊查询均无法通过网关执行；
  - 无法对「伊利宫酪奶皮子酸奶风味酸乳138g」做百度 Skill 模糊查询。
- 若要在看板或脚本中对该商品做模糊比价，需先让 OpenClaw 网关暴露上述 tool（在 OpenClaw 中注册/启用提供这些 tool 的 Skill），或使用万邦等其它已配置的数据源。

### 9.3 Chat 中「比较价格」无回复

- **可能原因**（结合网关日志）：
  1. **百炼 (anthropic)**：返回 HTTP 403，未通过鉴权或策略限制；
  2. **豆包 (volcengine/doubao-seed-1-8-251228)**：返回 404，账号未在火山引擎 Ark 控制台开通该模型；
  3. 回退链会继续尝试 **DeepSeek**、**OpenAI**；若二者也超时或失败，则 Chat 无回复。
- **建议**：在 `~/.openclaw/openclaw.json` 中已将回退顺序设为 百炼 → DeepSeek → 豆包 → OpenAI，确保豆包未开通时优先用 DeepSeek；若 Control UI 提示未授权，请使用带 token 的 Dashboard URL（如 `http://127.0.0.1:18789/#token=<gateway.auth.token>`）并在设置中填入该 token。

### 9.4 看板比价与 Chat 内 Skill 的关系

- **看板「货盘比价」**不依赖 Chat 里手动输入的「比较价格」或 OpenClaw 本机 Skill 脚本（如 `baidu-compare.sh`），只依赖看板后端的**百度 Skill 封装**（`htma_dashboard/baidu_skill_compare.py`）或万邦。
- 当前网关未暴露比价 tool，故看板侧即使用百度 Skill 封装请求网关，也会得到「未找到可用比价 tool」，结果表现为全部「独家款」；要打通需在 OpenClaw 侧暴露上述 tool 或使用万邦。

---

## 10. 相关文档

- 定时比价任务：[定时比价任务说明.md](./定时比价任务说明.md)
- 看板 launchd 与防睡眠：[人力成本API与部署说明.md](./人力成本API与部署说明.md) 第 4 节
- OpenClaw 官方：[openclaw.ai](https://openclaw.ai/) | ClawHub 注册中心：[clawhub.ai](https://clawhub.ai/)
