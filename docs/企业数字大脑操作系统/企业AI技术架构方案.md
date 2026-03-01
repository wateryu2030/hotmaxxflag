# 企业 AI 技术架构方案（推荐技术栈）

现实可落地版本。

---

## 技术栈

| 层级 | 推荐 | 说明 |
|------|------|------|
| **AI 中枢** | OpenClaw + LLM | 公司智能中枢，调度与决策 |
| **数据层** | PostgreSQL / Supabase / MSSQL（已有） | 统一数据仓库 |
| **自动化层** | n8n（强烈推荐）/ Zapier（备用） | 工作流与自动化引擎 |
| **应用层** | React / Next.js / Node.js | 前端与后端服务 |
| **AI 能力** | OpenAI API / Claude API / 本地模型（后期） | 大模型接入 |
| **数据分析** | Metabase / Superset / Power BI | 报表与看板 |

---

## 架构示意

```
AI 中枢 (OpenClaw)
        │
自动化引擎 (n8n)
        │
数据仓库 (Postgres / MSSQL)
        │
业务系统（餐饮 / 零售 / 电商 / 信息等）
```

---

## 原则

- 数据层先统一，再上自动化与 AI。
- 自动化优先用 n8n 等低代码串联，复杂逻辑再写代码。
- OpenClaw 作为入口，与 n8n、业务系统、数据层协同。
