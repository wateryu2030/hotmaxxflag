# 京东自主比价 - OpenClaw / Playwright 方案

不依赖 OneBound 等付费 API，使用 Playwright 打开京东搜索页，提取竞品价格。

## 一、快速开始

### 1. 安装依赖

```bash
cd /Users/document/好特卖超级仓/数据分析
source .venv/bin/activate
pip install playwright pymysql python-dotenv
playwright install chromium   # 需单独执行，会下载约 160MB Chromium
```

若 `playwright install` 在沙盒/CI 中失败，可在本机终端执行后再运行脚本。

### 2. 预览待比价商品（无需浏览器）

```bash
npm run htma:price_scrape:dry
```

或：

```bash
python scripts/htma_price_scrape_jd.py --dry-run --limit 20
```

### 3. 执行比价（需 Chromium）

```bash
npm run htma:price_scrape
```

或：

```bash
python scripts/htma_price_scrape_jd.py --limit 15 --headless
```

## 二、参数说明

| 参数 | 默认 | 说明 |
|------|------|------|
| `--limit` | 15 | 比价商品数（从 DB 按销售额取前 N 个） |
| `--headless` | 否 | 无头模式，不显示浏览器窗口 |
| `--delay` | 2.0 | 每次搜索间隔（秒），避免被封 |
| `--dry-run` | 否 | 仅列出商品，不爬取 |

## 三、商品来源

从 `t_htma_sale` + `t_htma_stock` 导出沈阳超级仓近 30 天有销量的商品，按销售额排序，取前 N 个。与 `price_compare.py` 的 stage1 逻辑一致。

## 四、OpenClaw Skill 配置（可选）

在 OpenClaw 的 skills 中加入：

```yaml
- name: htma-jd-price-scrape
  description: 好特卖货盘与京东自主比价（Playwright）
  trigger: |
    当用户说「京东比价」「自主比价」「爬取京东价格」时触发
  action: |
    cd /Users/document/好特卖超级仓/数据分析 && npm run htma:price_scrape
```

## 五、与 API 方案对比

| 方式 | 成本 | 稳定性 | 适用场景 |
|------|------|--------|----------|
| OneBound API | 约 0.02–0.09 元/次 | 高（需开通） | 大批量、自动化 |
| Playwright 爬取 | 免费 | 受京东反爬影响 | 小规模抽样、测试 |

建议：先用 `--limit 10` 小规模测试，确认可行后再增加数量。
