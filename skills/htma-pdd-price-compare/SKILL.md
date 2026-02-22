---
name: htma-pdd-price-compare
description: 好特卖货盘与拼多多比价。使用蚂蚁星球 API 获取竞品价格，OneBound 不可用时的替代方案。
metadata:
  openclaw:
    requires:
      bins: ["python3", "npm"]
    emoji: "📦"
    autoExec: true
---

# 好特卖拼多多比价

## 触发场景

当用户说以下任一短语时**自动执行**：
- 拼多多比价
- 设置拼多多比价
- 申请蚂蚁星球
- 配置 PDD 比价
- 用 wateryu2030@gmail.com 申请 apikey

## 一键自动执行（全权限）

```bash
cd /Users/document/好特卖超级仓/数据分析 && npm run htma:pdd_apply
```

## 自主执行直到成功（交给 OpenClaw）

让 OpenClaw 根据运行结果自动重试，直到比价成功：

```bash
cd /Users/document/好特卖超级仓/数据分析 && npm run htma:price_compare:auto
```

详见 `docs/OpenClaw自主比价-终端命令.md`。

该脚本会：
1. 打开注册页 https://www.haojingke.com/auth/register（使用 wateryu2030@gmail.com 完成注册）
2. 打开 API 申请页 https://www.haojingke.com/open-api/pdd
3. 若 .env 已配置 PDD_HOJINGKE_APIKEY，则自动执行比价测试

## 手动步骤（注册完成后）

1. 登录蚂蚁星球，进入「个人中心 -> 开放API -> 拼多多」申请 apikey
2. 将 apikey 填入 `.env`：`PDD_HOJINGKE_APIKEY=你的apikey`
3. 执行：`npm run htma:price_compare`

## OpenClaw 全权限配置

将 `config/openclaw-htma-full.json` 合并到 `~/.openclaw/openclaw.json`，或手动添加：

```json5
{
  "tools": {
    "allow": ["exec", "process", "read", "write", "edit"],
    "exec": { "host": "sandbox", "security": "full", "ask": "off" }
  },
  "skills": {
    "load": {
      "extraDirs": ["/Users/document/好特卖超级仓/数据分析/skills"]
    }
  }
}
```
