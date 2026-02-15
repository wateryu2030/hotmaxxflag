# 如何让 AI 控制浏览器完成 JimuReport 报表设计

有两种思路：**用 Cursor 的 MCP 浏览器把控制权交给 AI**，或 **在本地运行自动化脚本一次性完成设计**。

---

## 方式一：启用 MCP 浏览器（由 AI 直接操作你的浏览器）

### 1. 确认已安装 Node.js

终端执行：

```bash
node -v   # 建议 v18+
```

若未安装：`brew install node`

### 2. 在 Cursor 里添加 MCP 浏览器服务

1. 打开 **Cursor** → 左下角齿轮 **Settings**（或 `Cmd + ,`）。
2. 在设置里找到 **Features** → **MCP**（或 **Tools** → **MCP**）。
3. 点击 **“+ Add New MCP Server”** 或 **“New MCP server”**。
4. 选择「从目录安装」时，可搜索 **browser** 或 **cursor-ide-browser** 并安装；若需手动配置，在 **全局** 或 **项目** 的 MCP 配置里添加：

**全局配置**（只在你本机生效）：编辑 `~/.cursor/mcp.json`（没有就新建），内容示例：

```json
{
  "mcpServers": {
    "cursor-ide-browser": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-server-puppeteer@latest"]
    }
  }
}
```

或使用其他你已安装的浏览器 MCP（如 `@browsermcp/mcp` 等），按该 MCP 的文档填写 `command` 和 `args`。

5. 保存后，在 MCP 页面点 **刷新**，确认该服务器为已连接/已启用。

### 3. 把“控制权”交给 AI

- **你先打开浏览器**：在 Chrome/Edge 等里打开 `http://127.0.0.1:8085`，登录 JimuReport（admin / 123456），进入 **报表设计** 或 **报表列表** 页，并保持该标签页在前台。
- **再在 Cursor 里对我说**：例如「我已经打开 JimuReport 报表设计页了，请用浏览器 MCP 帮我完成数据绑定」。
- 我会尝试通过 MCP 的浏览器工具（如 snapshot、click、type）操作你打开的页面。**注意**：部分 MCP 浏览器只能操作“已打开的标签页”，且有的环境无法访问 `localhost`，若失败可尝试下面方式二。

---

## 方式二：运行本地自动化脚本（不依赖 MCP，你本机执行一次）

由我在项目里写好脚本，你在本机执行一次，脚本自动：打开 JimuReport → 登录 → 进入报表设计 → 绑定数据集与单元格。这样不需要“把浏览器权限交给 AI”，而是“把设计步骤固化成脚本”。

### 使用步骤（推荐用 Node 脚本，不依赖 Python 版本）

1. **安装 Chromium（仅首次，需在终端执行，下载约 1–2 分钟）**

```bash
cd "/Users/document/好特卖超级仓/数据分析"
npm run jr:install
```

2. **确认 JimuReport 已启动**（例如已在本机运行 `mvn spring-boot:run`，能访问 http://127.0.0.1:8085）。

3. **运行自动化**

```bash
npm run jr:auto
```

4. 脚本会在浏览器中自动完成：登录 → 进入报表列表 → 新建/打开报表 → 绑定 `htma_sale` 数据集到第 2 行并设置表头。**结束后不要立刻关浏览器**，你可检查预览并手动点「保存」保存报表。

若你希望用方式二，我可以根据你当前 JimuReport 版本和界面，把上述脚本写好并放在 `scripts/jimureport_auto_design.py`，你只需执行上述命令即可。

---

## 小结

| 方式 | 优点 | 注意 |
|------|------|------|
| **MCP 浏览器** | 由 AI 实时操作，可随你描述调整 | 需在 Cursor 中启用 MCP；localhost 可能受限 |
| **本地脚本** | 不依赖 MCP，可重复运行、易分享 | 需本机安装 Playwright；界面大改时可能要改脚本 |

如果你告诉我更倾向哪种（MCP 或 脚本），我可以按你的选择细化下一步（例如 MCP 的准确配置名，或脚本的具体操作步骤与选择器）。
