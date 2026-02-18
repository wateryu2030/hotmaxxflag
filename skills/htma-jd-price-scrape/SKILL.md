---
name: htma-jd-price-scrape
description: 好特卖货盘与京东自主比价。从 DB 取具体品名+规格商品，用模糊搜索词在京东搜索页爬取竞品价。
metadata:
  openclaw:
    requires:
      bins: ["python3"]
    emoji: "🛒"
    homepage: "https://github.com"
---

# 好特卖京东自主比价

## 触发场景

当用户说以下任一短语时执行：
- 京东比价
- 自主比价
- 爬取京东价格
- 好特卖比价
- 货盘比价

## 执行步骤

1. **确认环境**：MySQL 已启动，项目路径为 `/Users/document/好特卖超级仓/数据分析`。
2. **执行命令**：
   ```bash
   cd /Users/document/好特卖超级仓/数据分析 && source .venv/bin/activate && python scripts/htma_price_scrape_jd.py --limit 10 --delay 2.5 --headless
   ```
3. **首次使用**：若报错缺少 Chromium，先执行 `playwright install chromium`。
4. **预览模式**（不启动浏览器，仅列出待比价商品与搜索词）：
   ```bash
   cd /Users/document/好特卖超级仓/数据分析 && npm run htma:price_scrape:dry
   ```

## 核心逻辑

- **数据来源**：`t_htma_sale` + `t_htma_stock`，取沈阳超级仓近 30 天有销量商品。
- **优先选择**：有具体品名、规格、品牌的商品（模糊匹配效果更好）。
- **搜索词**：`build_search_keyword()` 生成「品牌 + 品名 + 规格」空格分隔，便于京东模糊匹配。
- **输出**：好特卖售价 vs 京东最低价，价格优势率分层。

## 配置

在 `~/.openclaw/openclaw.json` 的 `skills.load.extraDirs` 中加入：
```json
["/Users/document/好特卖超级仓/数据分析/skills"]
```
