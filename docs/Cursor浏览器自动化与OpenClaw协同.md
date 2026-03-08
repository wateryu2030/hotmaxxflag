# Cursor 浏览器自动化与 OpenClaw 协同配置

本文说明如何让 Cursor 通过 MCP 获得浏览器自动化能力，并与 OpenClaw 协同完成开发与测试。

## 一、MCP 是什么

MCP（Model Context Protocol，模型上下文协议）是 Cursor 与外部工具之间的桥梁。安装「浏览器自动化」的 MCP 服务器后，Cursor 内的 AI 可以调用打开网页、点击、输入、截图等工具，从而自动完成前端测试、数据导入验证、看板联调等任务。

## 二、推荐方案：Playwright MCP

本项目已在 **`.cursor/mcp.json`** 中配置 Playwright MCP（项目级）。若你希望所有项目都能用，可改为全局配置。

### 1. 项目级（当前）

- 配置文件：**本仓库 `.cursor/mcp.json`**
- 内容示例：
```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"]
    }
  }
}
```
- **若本环境中没有该文件**（例如新克隆或 `.cursor/` 被 gitignore 未提交）：在项目根目录执行 **`bash scripts/ensure_cursor_mcp.sh`**，会创建 `.cursor/mcp.json`。
- 注意：`.cursor/` 在本项目 `.gitignore` 中，该文件不会提交；若需团队共用，可取消忽略并提交 `mcp.json`，或在各环境运行上述脚本。

### 2. 全局配置（可选）

- 打开 Cursor：**设置 → MCP**，点击 **Add new global MCP server**。
- 或直接编辑 **`~/.cursor/mcp.json`**（不存在则创建），写入上述 `mcpServers` 内容。
- 保存后重启 Cursor，MCP 列表中出现 `playwright` 且为绿色即表示成功。

### 3. 使用方式

配置成功后，AI 可调用以 `browser_` 开头的工具，例如：

- `browser_navigate`：打开 URL  
- `browser_click`：点击元素  
- `browser_fill` / `browser_type`：输入  
- `browser_snapshot`：获取页面结构（用于定位元素）  
- `browser_tabs`：管理标签页  

你只需用自然语言描述任务，例如：“在本地 5002 端口打开看板，登录后点人力成本 Tab，截一张图”，AI 会组合调用这些工具完成。

## 三、与 OpenClaw 的配合

- **OpenClaw** 作为后台智能体，负责任务编排、状态管理和结果汇总。
- **Cursor + Playwright MCP** 负责具体浏览器操作（打开页面、点击、输入、截图）。
- OpenClaw 可通过 `agent-memory setup cursor` 等命令配置 MCP，使其也能调用同一套工具或与 Cursor 协同。

工作流示例：

1. 你在 Cursor 中提出：“用浏览器打开 http://localhost:5002，验证人力成本 Tab 是否有数据。”
2. Cursor 的 AI 通过 Playwright MCP 执行导航、登录（若需）、点击「人力成本」、截取快照。
3. OpenClaw 可负责记录执行结果、失败时重试或通知，并在任务结束后汇总。

## 四、备选方案：CodingBaby-Browser-MCP

若你更倾向通过浏览器扩展控制，可使用：

- 在 `mcp.json` 的 `mcpServers` 中增加：
```json
"CodingBaby-Browser-MCP": {
  "command": "npx",
  "args": ["-y", "@sydneyassistent/codingbaby-browser-mcp"]
}
```
- 在 Chrome 中安装 **CodingBaby Extension**，以便 MCP 通过扩展与浏览器通信。

## 五、小结

- 本项目已提供 **`.cursor/mcp.json`** 的 Playwright MCP 示例，便于在本仓库内直接使用浏览器自动化；若缺失可运行 **`bash scripts/ensure_cursor_mcp.sh`** 生成。
- **若未生效**：① 确认 Cursor **已完全重启**（MCP 仅在启动时加载）；② 在 **设置 → MCP** 中确认 `playwright` 为绿色；③ 本机需有 Node.js 18+，以便 `npx` 拉取 `@playwright/mcp`。
- 与 OpenClaw 协同时，由 OpenClaw 做编排与记忆，Cursor + MCP 做具体浏览器操作即可。
