# OpenClaw 全局服务与百度比价配置

将 OpenClaw 网关配置为系统级服务（LaunchAgent，登录后自启），供好特卖超级仓项目调用百度比价。

**执行环境**：以下命令需在**系统终端（沙箱外）**执行；Cursor 内置终端或沙箱内可能无法访问本机 127.0.0.1:18789，导致网关显示不可达或 openclaw 命令异常。若遇 `openclaw onboard` 报 `SyntaxError: Unexpected reserved word`，说明当前 shell 用的 Node 过旧，请用 nvm 的 node 直接跑：`/Users/zhonglian/.nvm/versions/node/v22.22.1/bin/node /Users/zhonglian/openclaw/openclaw.mjs ...`（或先 `nvm use 22` 再执行）。

---

## 一、已修复：百度插件 ID 不匹配

插件清单 `openclaw.plugin.json` 的 `id` 已从 `index` 改为 `baidu-price-tools`，与目录名及 OpenClaw 解析一致，避免「ID 不匹配」导致无法加载。

---

## 二、终端命令（按顺序复制执行）

### 1. 合并 OpenClaw 配置并启用百度插件（含 projectRoot）

在**好特卖项目根目录**执行：

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag
bash scripts/setup_openclaw_baidu_tools.sh
```

会写入 `~/.openclaw/openclaw.json`：`plugins.load.paths` 包含百度插件路径；projectRoot 由环境变量 `OPENCLAW_BAIDU_PROJECT_ROOT` 传递（plist 中已配置）。

### 2. 确保日志目录存在

```bash
mkdir -p ~/.openclaw/logs
```

### 3. 安装 LaunchAgent（网关登录后自启）

**先停止已有网关**（若之前手动或其它 plist 启动过）：

```bash
pkill -f "openclaw.mjs gateway" 2>/dev/null
# 或: lsof -ti:18789 | xargs kill -9
```

若你**从未**用 `openclaw gateway install` 安装过 plist，直接使用项目提供的 plist（已使用 **gateway run** 常驻、且 node 为完整路径）：

```bash
cp /Volumes/ragflow/hotmaxx/hotmaxxflag/scripts/openclaw-gateway-launchagent.plist ~/Library/LaunchAgents/ai.openclaw.gateway.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist
```

若你**已经**有 `~/Library/LaunchAgents/ai.openclaw.gateway.plist`（例如曾执行过 `openclaw gateway install`），只需注入项目根目录环境变量，然后重新加载：

```bash
bash /Volumes/ragflow/hotmaxx/hotmaxxflag/scripts/setup_gateway_plist_baidu_root.sh
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist
```

### 4. 确认网关运行

```bash
launchctl list | grep ai.openclaw.gateway
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:18789/
```

应看到进程在列且 HTTP 返回 200。

### 5. 验证百度比价工具

将下面命令里的 `<TOKEN>` 替换为你的网关 token（`b5d0ea99b2800962dba51d60cb60b766a3f516bda4c49877`）：

```bash
curl -sS -X POST http://127.0.0.1:18789/tools/invoke \
  -H "Authorization: Bearer b5d0ea99b2800962dba51d60cb60b766a3f516bda4c49877" \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_price_comparison","args":{"query":"洽洽坚果"}}'
```

若返回中含 `"data"` 和价格信息，说明百度比价已可用。

---

## 三、好特卖项目侧配置（.env）

在项目根目录的 `.env` 中配置网关地址与 token（Cursor 或任意调用方共用）：

```bash
# OpenClaw 网关（全局服务）
OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
OPENCLAW_GATEWAY_TOKEN=b5d0ea99b2800962dba51d60cb60b766a3f516bda4c49877
```

看板与脚本会优先请求该网关的 `/tools/invoke` 做比价；无需在 Cursor 或项目里启动网关，网关由 LaunchAgent 在系统级常驻。

---

## 四、在好特卖项目中调用百度比价

### 方式一：curl（终端）

```bash
curl -sS -X POST http://127.0.0.1:18789/tools/invoke \
  -H "Authorization: Bearer b5d0ea99b2800962dba51d60cb60b766a3f516bda4c49877" \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_price_comparison","args":{"query":"伊利宫酪奶皮子酸奶"}}'
```

### 方式二：Python（项目内示例脚本，会读 .env）

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag
python scripts/call_openclaw_baidu_price.py 洽洽坚果
```

或在代码中调用（与看板一致，会读 `.env` 中的 `OPENCLAW_GATEWAY_URL` / `OPENCLAW_GATEWAY_TOKEN`）：

```python
import os
import json
import urllib.request

GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789").rstrip("/")
GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "你的token")

def get_price_comparison(query: str) -> dict:
    req = urllib.request.Request(
        f"{GATEWAY_URL}/tools/invoke",
        data=json.dumps({"tool": "get_price_comparison", "args": {"query": query}}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {GATEWAY_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.loads(r.read().decode())
    if not out.get("ok"):
        return {"error": out.get("error", {})}
    return out.get("result", {})

print(get_price_comparison("洽洽坚果"))
```

### 方式三：看板已有封装

看板已通过 `htma_dashboard/baidu_skill_compare.py` 调用网关；配置好 `.env` 中的 `OPENCLAW_GATEWAY_URL` 与 `OPENCLAW_GATEWAY_TOKEN` 后，货盘比价会自动走该全局网关。

---

## 五、常用 launchd 命令

| 操作       | 命令 |
|------------|------|
| 查看状态   | `launchctl list \| grep ai.openclaw.gateway` |
| 停止网关   | `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist` |
| 启动网关   | `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist` |
| 查看错误日志 | `tail -f ~/.openclaw/logs/gateway.err.log` |

---

## 六、若比价返回 Tool not available

- 先停掉占用 18789 的旧进程：`pkill -f "openclaw.mjs gateway"` 或 `lsof -ti:18789 | xargs kill -9`。
- 确认 plist 使用 **gateway run**（不是 gateway start），且 `OPENCLAW_BAIDU_PROJECT_ROOT` 已设。
- 在终端手动验证：`cd /Users/zhonglian/openclaw && OPENCLAW_BAIDU_PROJECT_ROOT=/Volumes/ragflow/hotmaxx/hotmaxxflag node openclaw.mjs gateway run`，看日志是否出现 baidu-price-tools 或 get_price_comparison 注册；再用 curl 测 `/tools/invoke`。

## 七、说明

- **LaunchAgent vs LaunchDaemon**：当前使用 LaunchAgent（用户级，登录后自启），配置在 `~/Library/LaunchAgents/`。若需在**未登录**时也跑网关，需改用 LaunchDaemon（需 root，plist 放在 `/Library/LaunchDaemons/`），并单独配置运行用户与环境变量。
- **全局有效**：网关由 launchd 在系统级常驻，不依赖 Cursor；好特卖项目、脚本、看板只需配置同一网关 URL 和 token 即可调用。
- **百度插件路径**：插件在项目内 `openclaw_extensions/baidu-price-tools/`，通过 `~/.openclaw/openclaw.json` 的 `plugins.load.paths` 加载；`projectRoot` 在配置或环境变量 `OPENCLAW_BAIDU_PROJECT_ROOT` 中指向好特卖项目根目录，供插件调用 `scripts/openclaw_baidu_tools_runner.py`。

---

## 八、Control 配置页与「百度 Skill 一直不可用」排查（沙箱外 OpenClaw 设置）

在浏览器打开 `http://127.0.0.1:18789/config` 时，若百度 Skill 仍不可用，请按下面逐项检查（**均在系统终端 / 沙箱外**）。

### 8.1 未保存的更改必须先生效

- 若页面显示 **「1 unsaved change」/「View 1 pending change」**：说明有配置改过但未生效。
- **操作**：点击 **Save** 保存，再点 **Apply**（若有）或 **Reload**，然后**重启网关**（见下方 8.4）。未保存的改动不会被网关进程读取，可能导致插件或环境变量不生效。

### 8.2 Shell 环境导入（与 node/PATH 相关）

- **Shell Environment Import Enabled**：建议保持 **ON**，这样网关启动时会从登录 Shell 加载 `PATH` 等，便于找到正确的 `node`（尤其用 nvm 时）。
- 若本机用 nvm、且 Shell 初始化较慢：可适当调大 **Shell Environment Import Timeout (ms)**，避免超时后回退导致 `node` 或 `PATH` 未加载到网关进程。
- 若仍异常：LaunchAgent 已用 **node 绝对路径**（如 `/Users/zhonglian/.nvm/versions/node/v22.22.1/bin/node`），不依赖 Shell 的 PATH；此时 Shell 导入主要影响其他环境变量（如 `OPENCLAW_BAIDU_PROJECT_ROOT` 若只在 profile 里设）。**推荐在 plist 的 EnvironmentVariables 里显式设置 `OPENCLAW_BAIDU_PROJECT_ROOT`**（项目已提供的 plist 已包含）。

### 8.3 表单视图无法安全编辑部分字段

- 若出现提示 **「Form view can't safely edit some fields. Use Raw to avoid losing config entries.»**：说明插件相关配置（如 `plugins.load.paths`、`plugins.allow`）用表单改可能丢项。
- **推荐做法**：不要依赖 Control 表单改插件配置，而是：
  1. 在项目根目录执行：`bash scripts/setup_openclaw_baidu_tools.sh`，自动把百度插件路径写入 `~/.openclaw/openclaw.json` 的 `plugins.load.paths`。
  2. 若 OpenClaw 版本有 **plugins.allow**：用 **Raw** 视图打开 `openclaw.json`，在 `plugins.allow` 数组中加入 `"baidu-price-tools"`（若没有该数组则按官方文档添加）。
  3. 保存后**重启网关**（8.4）。

### 8.4 重启网关使配置生效

配置或 plist 修改后必须重启网关（在系统终端执行）：

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist
```

然后查看错误日志，确认是否有 baidu-price-tools 或 get_price_comparison 相关报错：

```bash
tail -30 ~/.openclaw/logs/gateway.err.log
```

### 8.5 一键检查清单（终端执行）

| 步骤 | 命令或检查 |
|------|------------|
| 1. 插件路径已写入 | `grep -A2 '"paths"' ~/.openclaw/openclaw.json` 应包含好特卖项目下的 `openclaw_extensions/baidu-price-tools` |
| 2. plist 含项目根 | `plutil -p ~/Library/LaunchAgents/ai.openclaw.gateway.plist \| grep OPENCLAW_BAIDU` 应看到 `OPENCLAW_BAIDU_PROJECT_ROOT` = 项目根路径 |
| 3. 网关在跑 | `curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:18789/` 返回 200 |
| 4. 比价工具可调 | 将 `<TOKEN>` 换为 `~/.openclaw/openclaw.json` 里 `gateway.auth.token`，执行：`curl -sS -X POST http://127.0.0.1:18789/tools/invoke -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d '{"tool":"get_price_comparison","args":{"query":"洽洽"}}'`，返回中应有 `"data"` 或价格信息；若为 `Tool not available` 说明插件未加载，回头看 8.1–8.4 |

「健康状况 正常」只表示网关进程在跑，不保证百度插件已加载；必须用第 4 步的 curl 或看板实际比价验证。
