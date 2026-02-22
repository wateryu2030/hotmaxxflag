# OpenClaw 自主比价 - 终端命令

## 比价策略是否执行

- **脚本**：`scripts/openclaw_price_compare.sh` 已改为 `use_mock_fetcher=False`，会优先使用真实 API（蚂蚁星球京东/拼多多），未配置时自动回退为模拟。
- **校验**：执行后输出含「分析完成」且报告末尾有「竞品价来自 真实API」或「模拟」即表示策略已跑完；结果写入 `t_htma_price_compare` 表。

## 把控制权交给 OpenClaw，自主执行直到成功

在 OpenClaw 中执行（或本地终端执行）：

```bash
cd /Users/document/好特卖超级仓/数据分析 && npm run htma:price_compare:auto
```

或直接：

```bash
cd /Users/document/好特卖超级仓/数据分析 && bash scripts/openclaw_auto_price_compare.sh
```

**行为说明**：
1. 可选检查/创建 `t_htma_price_compare`、`t_htma_platform_products` 表。
2. 执行货盘比价（`openclaw_price_compare.sh`）。
3. 若输出包含「分析完成」则视为成功并退出。
4. 否则等待 15 秒后重试，最多 3 次；仍失败则退出码 1，便于 OpenClaw 根据程序运行情况继续调整。

## OpenClaw 全权限与 Skill

- 将 `config/openclaw-htma-full.json` 合并到 `~/.openclaw/openclaw.json`，使 `exec` 具备执行权限。
- `skills.load.extraDirs` 指向本项目 `skills`，对 OpenClaw 说「拼多多比价」「货盘比价」等可触发对应 Skill。

**让 OpenClaw 自主工作直到调试成功**：在对话中说明「执行自主比价直到成功」，或直接让 OpenClaw 执行上述 `npm run htma:price_compare:auto` 命令；OpenClaw 可根据退出码和输出决定是否重试或排查 MySQL / .env / 网络。

---

## 调用 OpenClaw 自主完成实际改造工作

当需要 **OpenClaw 自主完成实际改造**（建表 → 比价 → 校验表格结果）时，在 OpenClaw 对话中说：

- **「调用 openclaw 自主完成实际改造工作」**
- 或 **「OpenClaw 自主改造」**

OpenClaw 会加载本项目的 `skills/htma-openclaw-autonomous`，并执行：

```bash
cd /Users/document/好特卖超级仓/数据分析 && npm run htma:openclaw_work
```

或直接运行脚本：

```bash
cd /Users/document/好特卖超级仓/数据分析 && bash scripts/openclaw_do_actual_work.sh
```

该脚本会：确保平台商品表与比价表存在 → 执行自主比价（自动重试）→ 校验输出含「比价明细表」「分析完成」。成功后可在前端（npm run htma:run → http://127.0.0.1:5002/ → AI 分析建议 → 比价）查看表格结果。
