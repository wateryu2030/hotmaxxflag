---
name: htma-openclaw-autonomous
description: 利用 OpenClaw 自主完成编程工作；直接调用浏览器、终端、文件编辑等外设，由 AI 自主分析任务、决定步骤、迭代直至完成。触发词：利用 openclaw 自主完成编程工作、直接调用浏览器和外设自主执行、OpenClaw 自主编程。
metadata:
  openclaw:
    requires:
      bins: ["python3", "npm", "mysql"]
    emoji: "🔧"
    autoExec: true
---

# 利用 OpenClaw 自主完成编程工作（浏览器 + 外设）

## 重要：你不是「触发后按流程执行」

当用户说 **「利用 openclaw 自主完成编程工作」** 或 **「直接调用浏览器和其他外设来自主执行」** 时：

- **你必须自主决策**：分析任务是什么、先做什么、后做什么、哪里可能失败、如何验证。
- **你必须直接使用工具**：
  - **browser**：打开网页、点击、输入、截图、snapshot；例如打开蚂蚁星球申请 API、打开看板 http://127.0.0.1:5002 验证比价表格。
  - **exec / process**：在项目目录执行命令（如 `npm run htma:run`、`npm run htma:price_compare`、建表、同步商品），根据输出决定下一步（重试、改代码、查日志）。
  - **read / write / edit**：阅读和修改项目代码与配置（如 `.env`、`price_compare.py`、前端 HTML），修复报错或实现新逻辑。
- **迭代直到完成**：若执行失败，根据报错自行排查（改代码、改配置、重跑），不要只跑一次就停。
- **不要**：只执行一条预设的 bash 脚本就结束；或只给用户「请手动执行以下步骤」的清单。

## 工作目录

```
/Users/document/好特卖超级仓/数据分析
```

## 你可用的能力（必须被配置允许）

| 能力 | 用途 |
|------|------|
| **browser** | 打开申请页、看板页面；填写表单、点击按钮；截图/snapshot 验证界面 |
| **exec / process** | 运行 `npm run htma:run`、`npm run htma:price_compare`、`mysql` 建表、Python 脚本等 |
| **read / write / edit** | 查看和修改 `.env`、`htma_dashboard/*.py`、`static/index.html`、SQL 等 |
| **web_fetch / web_search** | 查文档、接口说明（必要时） |

## 典型自主流程示例（仅作参考，你可调整）

1. **理解任务**：例如「比价功能要能跑通并在前端以表格展示」。
2. **环境**：`exec` 检查 MySQL、Node、Python 是否可用；必要时建表（执行 `scripts/08_create_platform_products.sql` 等）。
3. **配置**：`read` 检查 `.env` 是否有 `PDD_HOJINGKE_APIKEY`；若缺失且用户允许，可用 **browser** 打开蚂蚁星球申请页，或提示用户填写。
4. **运行与调试**：`exec` 运行 `npm run htma:price_compare` 或 `htma:price_compare:auto`；若报错则 `read` 相关代码、`edit` 修复、再运行。
5. **验证**：`exec` 启动 `npm run htma:run`，用 **browser** 打开 http://127.0.0.1:5002/ → 点击「AI 分析建议」→「比价」→ 执行比价 → 用 snapshot/截图确认页面上有「比价明细表」表格。
6. **收尾**：若用户需要，可提交代码或给出简短完成报告。

## 权限配置（用户需在 ~/.openclaw/openclaw.json 中开启）

要「直接调用浏览器和其他外设」，OpenClaw 必须允许 browser 与 exec、文件工具。参考本项目 `config/openclaw-htma-autonomous.json`，合并到 `~/.openclaw/openclaw.json`：

- `tools.allow` 包含 `browser`、`exec`、`process`、`read`、`write`、`edit`（或 `group:ui`、`group:runtime`、`group:fs`）。
- `tools.deny` 不要禁止上述工具。
- `browser.enabled: true`，必要时配置 `browser.defaultProfile`、`exec.security` 等。

这样你才能自主调用浏览器和终端完成编程与验证。
