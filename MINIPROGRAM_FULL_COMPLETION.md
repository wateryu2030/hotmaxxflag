# 好特卖经营分析小程序 — 配置与 API 说明

## 环境变量（`.env`）

| 变量 | 说明 |
|------|------|
| `WECHAT_APPID` / `WECHAT_APPSECRET` | 微信公众平台小程序 AppID / AppSecret |
| `WECHAT_JWT_SECRET` | 签发小程序 JWT |
| `WECHAT_MINI_ENABLED=1` | 生产环境要求 `/api/mobile/*` 带 Bearer |
| `HTMA_PUBLIC_URL` | 公网根，如 `https://htma.greatagain.com.cn` |
| `WECHAT_SUBSCRIBE_TEMPLATE_ID` | 订阅消息模板 ID（可逗号分隔多个） |
| `MYSQL_*` | 数据库连接，与看板一致 |

单测可设：`HTMA_SKIP_MOBILE_JWT=1`、`HTMA_UNITTEST_DISABLE_AUTH=1`。

## 数据库

- 预聚合表 `daily_category_stats`（脚本 `scripts/27_daily_category_stats.sql`）
- 可选索引：`scripts/33_mobile_bi_indexes.sql`（按需执行）
- 库存：`t_htma_stock`；销售明细：`t_htma_sale`（SKU 搜索、选品、税务）

## 微信小程序配置

- **AppID**：与 `project.config.json` 一致
- **request 合法域名**：`https://htma.greatagain.com.cn`（或你的 `HTMA_PUBLIC_URL`）
- **TabBar**：使用 `miniprogram/images/tab.png` / `tab_on.png`（占位 1×1 PNG，请替换为 **81×81** 正式图标）
- **ECharts**：已内置官方组件目录 `miniprogram/components/ec-canvas/`（含 `echarts.js`，约 1MB）。页面 `趋势洞察`、`品类分析-占比/贡献` 使用 `lazyLoad` 初始化；与列表/简易条形并存。
- **构建**：未使用 npm 分包；`project.config.json` 已 `packOptions.ignore` 忽略 `node_modules/**`（若本地自行 npm 安装依赖）。

## 新增/增强的 Mobile API（均需 JWT，单测除外）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/mobile/overview` | KPI 周期、环比、趋势、同比、周几对比、库存总额 |
| GET | `/api/mobile/heatmap` | 大类×月 毛利率矩阵 |
| GET | `/api/mobile/category_share` | 大类销售额占比 |
| GET | `/api/mobile/contribution` | 销售/毛利贡献 |
| GET | `/api/mobile/contribution_export` | 上述结果 CSV（同鉴权） |
| GET | `/api/mobile/trend_advanced` | `granularity=day\|week\|month`，`metric=sales\|profit\|margin` |
| GET | `/api/mobile/four_quadrant_simple` | 低毛利高人力摘要 |
| GET | `/api/mobile/sku_search` | `keyword` |
| GET | `/api/mobile/tax_summary` | 需 `tax_amount` 字段，否则占位说明 |
| GET | `/api/mobile/selection` | 红背篓规则选品 |
| GET | `/api/mobile/ai_advice` | 规则模板经营建议 |
| GET | `/api/mobile/inventory_summary` | 库存总额 + 低库存 SKU |
| POST | `/api/mobile/generate_report` | 返回看板链接说明（PDF 异步预留） |
| GET | `/api/mobile/labor_summary` | **增强**：人力成本/销额环比、人效环比等（见响应字段） |

缓存：上述 GET 多数带 `@mobile_cached`，TTL 300 秒（`flask_caching` 或 `SimpleTTLCache`）。

## 微信登录续期

- `POST /api/wechat/token_refresh`，Header: `Authorization: Bearer <token>`，返回新 `token`。

## 小程序页面结构

- **Tab**：总览 `home`、品类 `analysis`、趋势 `insight`、经营 `ops`、我的 `profile`
- **子页**：分类下钻 `categories/*`、预警 `alerts`、人力 Web `labor/web`、工具 `tools/*`
- **旧入口** `pages/index/index` 仍保留，主入口已改为 `pages/home/index`

## 已知限制与后续

- 趋势页超过 120 个数据点会前端抽样后再绑图；热力仍以文本列表展示（矩阵过大时更适合表格/专用热力页）。
- 若需减小包体：用 [ECharts 在线定制](https://echarts.apache.org/zh/builder.html) 替换 `components/ec-canvas/echarts.js`。
- `generate_report` 尚未接异步 PDF，仅返回 H5/说明。
- 同比依赖 `daily_category_stats` 至少覆盖前一年同区间；否则返回「数据周期不足1年」类提示。
