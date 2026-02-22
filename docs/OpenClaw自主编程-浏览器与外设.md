# 利用 OpenClaw 自主完成编程工作（浏览器与外设）

## 你要的效果

- **不是**：对 OpenClaw 说一句话 → 它只执行一条固定脚本 → 结束。
- **而是**：OpenClaw 像程序员一样**自主分析任务、决定步骤**，并**直接使用**：
  - **浏览器**：打开网页、填表、点击、截图 / snapshot 验证；
  - **终端**：在项目里执行命令，根据结果重试或改代码；
  - **编辑器**：读/写/改项目里的代码和配置；
  - 必要时**多轮迭代**，直到任务完成或明确卡点。

## 在 OpenClaw 里怎么说

在对话中可以说（任选其一）：

- **「利用 openclaw 自主完成编程工作」**
- **「直接调用浏览器和其他外设来自主执行相关工作」**
- **「OpenClaw 自主编程，用浏览器和终端自己跑通」**

OpenClaw 会加载本项目的 **`skills/htma-openclaw-autonomous`**，并按照 Skill 里的要求：自主决策、直接调用 browser / exec / read / write / edit，而不是只跑一个预设流程。

## 必须打开的权限（否则无法「直接调用」）

要让 OpenClaw **真的能**用浏览器和终端，需要在 **`~/.openclaw/openclaw.json`** 里放开对应工具。

### 1. 合并本项目的推荐配置

将 **`config/openclaw-htma-autonomous.json`** 的内容合并进 `~/.openclaw/openclaw.json`，或至少保证包含：

```json5
{
  "browser": {
    "enabled": true,
    "defaultProfile": "clawd",
    "headless": false
  },
  "tools": {
    "allow": ["browser", "exec", "process", "read", "write", "edit", "web_fetch", "web_search"],
    "deny": [],
    "exec": {
      "host": "sandbox",
      "security": "full",
      "ask": "off"
    }
  },
  "skills": {
    "load": {
      "extraDirs": ["/Users/document/好特卖超级仓/数据分析/skills"]
    }
  }
}
```

### 2. 含义简要说明

| 配置 | 作用 |
|------|------|
| `browser.enabled: true` | 允许使用 browser 工具（打开页面、点击、输入、snapshot 等） |
| `tools.allow` 含 `browser`, `exec`, `process`, `read`, `write`, `edit` | 允许调用浏览器、执行命令、读写文件 |
| `exec.security: "full"`, `ask: "off"` | 允许在沙箱/主机上执行命令且不需每次确认 |
| `skills.load.extraDirs` | 加载本项目 skills，使「自主编程」Skill 生效 |

### 3. 浏览器配置（可选）

若使用独立浏览器配置（如 `clawd`），可先安装/启动：

```bash
openclaw-cn browser status
openclaw-cn browser start
```

若使用系统 Chrome 并配合扩展，则 `defaultProfile` 可设为 `"chrome"`，具体见 OpenClaw 浏览器文档。

### 4. 大模型 API Key（供 OpenClaw 直接调用大模型）

- **项目 `.env`** 中已配置 `OPENAI_API_KEY`（OpenAI 兼容），供本仓库脚本与 OpenClaw 使用。
- **合并 `config/openclaw-htma-autonomous.json`** 后，其中包含 `models.providers.openai.apiKey: "${OPENAI_API_KEY}"`，OpenClaw 会据此调用大模型。
- 若从**本项目根目录**启动 OpenClaw，会优先读取当前目录 `.env` 中的 `OPENAI_API_KEY`。
- 若 OpenClaw 以 daemon 或从其他目录启动，请任选其一：
  - 在 **`~/.openclaw/.env`** 中增加一行：`OPENAI_API_KEY=sk-xxx`（与项目 `.env` 中一致）；
  - 或在启动前执行：`export OPENAI_API_KEY=sk-xxx`（或 `source .env` 后再启动）。

## 本仓库 Skill 做了什么

- **`skills/htma-openclaw-autonomous/SKILL.md`** 里写明：
  - 当用户说「利用 openclaw 自主完成编程工作」或「直接调用浏览器和外设自主执行」时，**必须**自主决策、**必须**直接使用 browser / exec / read / write / edit，迭代直到完成；
  - **禁止**只执行一条预设脚本就结束，或只给用户一份「请手动执行」的清单。
- 这样 OpenClaw 会以「自主编程 + 可调用浏览器与外设」的方式工作，而不是固定流程触发。

## 小结

1. 在 OpenClaw 里说：**「利用 openclaw 自主完成编程工作」** 或 **「直接调用浏览器和其他外设来自主执行」**。  
2. 在 **`~/.openclaw/openclaw.json`** 里按上面合并 **`config/openclaw-htma-autonomous.json`**，确保 **browser** 与 **exec/read/write/edit** 被允许。  
3. 确保 **`skills.load.extraDirs`** 包含本项目 **`skills`** 目录，以便加载「自主编程」Skill。  

完成后，OpenClaw 就可以在对话中**直接调用浏览器和终端**，自主完成编程与验证工作。
