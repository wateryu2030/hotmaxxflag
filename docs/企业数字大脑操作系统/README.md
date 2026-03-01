# 企业数字大脑操作系统雏形

本目录是 **OpenClaw / Cursor 通用** 的公司 AI 体系配置与文档，包含 5 大模块。  
本质：**公司数字大脑操作系统雏形**。

---

## 目录结构

| 模块 | 说明 | 路径 |
|------|------|------|
| **1️⃣ strategy.md** | 企业 AI 战略蓝图（核心） | [strategy.md](./strategy.md) |
| **2️⃣ 10 个 Agent** | CEO / Research / Finance / Ops / Marketing / Automation / HR / Project / Data / Strategy | [agents/](./agents/) |
| **3️⃣ 工作流模板** | 商业分析、项目启动、运营优化 | [workflows/](./workflows/) |
| **4️⃣ 技术架构** | AI 中枢 + 数据层 + 自动化层 + 应用层 | [企业AI技术架构方案.md](./企业AI技术架构方案.md) |
| **5️⃣ AI 员工制度** | AI 与人类职责、绩效、管理原则 | [AI员工管理制度.md](./AI员工管理制度.md) |

---

## 落地顺序（不可颠倒）

1. **第一步**：信息自动化  
2. **第二步**：数据整合  
3. **第三步**：业务自动化  

顺序反了会失败。

---

## 使用方式

- **OpenClaw**：工作区设为 `~/.openclaw/workspace/` 时，已同步本目录内容（strategy、agents、workflows、架构与制度）。  
- **Cursor**：直接引用本目录下 md 文件，或在对话中 @ 本目录。  
- **版本管理**：本目录在项目 `docs/` 下，随 git 提交，便于备份与协作。
