# Phase 0: 模块地图 — 路由与脚本全景

生成日期: 2026-05-10
项目: hotmaxxflag (好特卖沈阳超级仓运营看板)

---

## 1. 文件规模一览

| 文件 | 行数 | 角色 |
|------|------|------|
| htma_dashboard/app.py | 8,777 | 主应用（路由+逻辑+配置 高度混合） |
| htma_dashboard/import_logic.py | 2,841 | 数据导入核心逻辑 |
| htma_dashboard/analytics.py | 1,971 | 分析计算（含 large SQL 聚合） |
| htma_dashboard/labor_routes.py | 1,740 | 人力成本 Blueprint |
| htma_dashboard/mobile_bi.py | 1,407 | 移动端 BI API |
| htma_dashboard/routes_mobile.py | 914 | 小程序路由 Blueprint |
| htma_dashboard/routes_biz_enhanced.py | 593 | 经营分析增强路由 |
| htma_dashboard/routes_ops.py | 342 | 运维面板 Blueprint |
| htma_dashboard/routes_sales.py | 275 | 销售相关路由 |
| htma_dashboard/wechat_api.py | 281 | 微信小程序 API |
| htma_dashboard/auth.py | 180 | 飞书/企微扫码认证 |
| htma_dashboard/routes_category.py | 109 | 品类排行路由（薄） |
| htma_dashboard/routes_insights.py | 64 | 消费洞察路由（薄） |
| htma_dashboard/static/index.html | 5,530 | 前端看板（内联 JS/HTML/CSS） |
| **合计** | **25,024** | |

---

## 2. app.py 路由清单（130 条 @app.route）

### 2.1 按前缀分组

| 分组 | 数量 | 示例路径 |
|------|------|----------|
| ROOT `/` + 页面路由 | 14 | `/`, `/login`, `/import`, `/admin`, `/approval`, `/pending`, `/product_master`, `/profit_share`, `/tax_analysis`, `/hongbeilou`, `/attribution`, `/undefined`, `/.well-known/<path:_>` |
| `/api/auth/*` | 6 | `/api/auth/feishu_callback`, `/api/auth/feishu_url`, `/api/auth/me`, `/api/auth/logout`, `/api/auth/pending_count`, `/api/auth/approvals`, `/api/auth/approve` |
| `/api/kpi` + 概览 | 5 | `/api/kpi`, `/api/category_pie`, `/api/daily_trend`, `/api/sales_trend`, `/api/trend_analysis`, `/api/dow_sales` |
| `/api/category_rank*` | 5 | `/api/category_rank`, `/api/category_rank_by_large`, `/api/category_rank_mid`, `/api/category_rank_small`, `/api/category_rank_brands`, `/api/category_rank_products`, `/api/category_rank_detail` |
| `/api/profit*` | 5 | `/api/profit_summary`, `/api/profit_detail`, `/api/sale_summary`, `/api/sale_detail`, `/api/date_range` |
| `/api/inv_alert*` | 3 | `/api/inv_alert`, `/api/inv_alert_by_category`, `/api/inv_alert_list` |
| `/api/biz/*` (在 routes_biz_enhanced 中) | — | 见 3.4 节 |
| `/api/product_master*` | 8 | `/api/product_master_analysis`, `/api/product_master_status`, `/api/product_master_category_mid`, `/api/product_master_category_small`, `/api/product_master_drill`, `/api/product_master/brand_*`, `/api/product_master/drill_*` |
| `/api/profit_share*` | 11 | `/api/profit_share/calculate`, `/api/profit_share/category_options`, `/api/profit_share/exclude_categories`, `/api/profit_share/preview`, `/api/profit_share/result/<id>`, `/api/profit_share/results`, `/api/profit_share/rule`, `/api/profit_share/rule/<id>` |
| `/api/tax_analysis*` | 9 | `/api/tax_analysis/compare`, `/api/tax_analysis/full_invoice_months`, `/api/tax_analysis/import_full_invoice`, `/api/tax_analysis/import_invoice`, `/api/tax_analysis/invoice_detail`, `/api/tax_analysis/invoice_months`, `/api/tax_analysis/invoicing_ledger_export`, `/api/tax_analysis/tax_summary`, `/api/tax_analysis/uninvoiced_goods_analysis` |
| `/api/tax_burden*` | 2 | `/api/tax_burden_summary`, `/api/tax_burden_export` |
| `/api/import*` | 4 | `/api/import`, `/api/import_from_downloads`, `/api/import_preview`, `/api/import_product_master` |
| `/api/price_compare*` | 7 | `/api/price_compare`, `/api/price_compare_daily`, `/api/price_compare_products`, `/api/price_compare_results`, `/api/price_compare/capability`, `/api/price_compare/history`, `/api/platform_products_sync` |
| `/api/channel*` | 5 | `/api/channel/hongbeilou/batch`, `/api/channel/hongbeilou/export_pdf`, `/api/channel/hongbeilou/export`, `/api/channel/hongbeilou/logic`, `/api/channel/hongbeilou/preview` |
| `/api/consumer_insight*` | 4 | `/api/consumer_insight`, `/api/consumer_insight_trend`, `/api/consumer_insight/advanced_search`, `/api/consumer_insight/advanced_search_options` |
| `/api/analysis*` | 1 | `/api/analysis/attribution` |
| `/api/repair*` | 2 | `/api/repair_recalc_unit_price`, `/api/repair_swap_amount_cost` |
| 数据展示 (brand/supplier/price_band/sku 等) | 12 | `/api/brand_summary`, `/api/brand_categories`, `/api/supplier_summary`, `/api/supplier_categories`, `/api/supplier_products`, `/api/price_band_summary`, `/api/price_band_categories`, `/api/price_band_products`, `/api/sku_turnover`, `/api/sku_abc`, `/api/negative_margin_detail`, `/api/category_structure_trend`, `/api/inventory_turnover_summary`, `/api/inventory_turnover_by_category`, `/api/data_quality`, `/api/data_status` |
| 飞书机器人 | 2 | `/api/feishu/bot/event`, `/feishu/callback` |
| 其他 | 6 | `/api/health`, `/api/ai_chat`, `/api/insights`, `/api/enhanced_insights`, `/api/marketing_report`, `/api/structured_report`, `/api/report_history`, `/api/report_history/<id>`, `/api/sync_products_category`, `/api/export` |

**app.py 总计: ~130 条路由，~8777 行**

---

## 3. 已拆出 Blueprint / 路由模块

### 3.1 labor_routes.py (1740 行)
- Blueprint: `labor`（部分接口可能直接注册在 app）
- 功能: 人力成本增删改查、分析、导出
- 依赖: auth.py, import_logic.py（导入人力 Excel）, analytics.py（聚合指标）

### 3.2 routes_mobile.py (914 行) + mobile_bi.py (1407 行)
- Blueprint: `mobile` 或直接在 app 注册
- 功能: 微信小程序专有 API — 经营概览、预警、AI 摘要、门店切换
- 依赖: analytics.py（数据聚合）, auth.py（JWT/微信登录）

### 3.3 wechat_api.py (281 行)
- 功能: 微信小程序登录、绑定门店、订阅消息

### 3.4 routes_biz_enhanced.py (593 行)
- 功能: 经营分析增强 — `/api/biz/summary`, `/api/biz/category`, `/api/biz/slow_movers`, `/api/biz/category_matrix`
- 依赖: analytics.py

### 3.5 routes_ops.py (342 行)
- Blueprint: `ops`
- 功能: 运维面板 — `/api/ops/dashboard`, `/api/ops/panel`

### 3.6 routes_sales.py (275 行)
- 路由: 销售相关

### 3.7 routes_category.py (109 行)
- 路由: 品类排行相关（薄委托层）

### 3.8 routes_insights.py (64 行)
- 路由: 消费洞察相关（薄委托层）

---

## 4. 核心逻辑文件

### 4.1 import_logic.py (2841 行)
导出函数（需 grep 确认精确列表）:
- `import_sale_daily`, `import_sale_summary`, `import_stock`, `import_category`, `import_labor_cost`, `import_invoice` 等
- 写库表: `t_htma_sale`, `t_htma_stock`, `t_htma_category`, `t_htma_labor_cost`, `t_htma_invoice` 等
- 被 app.py, labor_routes.py 等 import

### 4.2 analytics.py (1971 行)
导出函数:
- KPI/概览: `calc_kpi`, `calc_sales_trend`, `calc_category_pie`
- 经营分析: `calc_profit`, `calc_inventory`, `calc_turnover`
- 写库: `refresh_daily_category_stats`, `refresh_profit_table`（可能是）
- 被 app.py, routes_biz_enhanced.py, routes_mobile.py 等 import

### 4.3 auth.py (180 行)
导出函数:
- `feishu_exchange_code_and_user`, `get_feishu_authorize_url`, `is_feishu_configured`, `_super_admin_open_id`

---

## 5. 前端文件

### 5.1 static/*.html
| 文件 | 行数 | 说明 |
|------|------|------|
| index.html | ~5,530 | 主看板（内联 JS ~4300 行） |
| login.html | ~90 | 登录页 |
| import.html | - | 数据导入页面 |
| labor_analysis.html | - | 人力分析 |
| product_master.html | - | 商品档案 |
| profit_share.html | - | 收益分账 |
| tax_analysis.html | - | 税务分析 |
| hongbeilou.html | - | 红背篓选品 |
| attribution.html | - | 销售额归因 |
| ops_panel.html | - | 运维面板 |
| admin.html | - | 管理员页 |
| approval.html | - | 审批页 |
| pending.html | - | 待审批页 |

### 5.2 static/js/*
| 文件 | 说明 |
|------|------|
| charts.js | ECharts 图表工具 |
| kpi-cards.js | KPI 卡片渲染 |
| filter-bar.js | 筛选条件组件 |
| drill-manager.js | 下钻管理 |

### 5.3 微信小程序
路径: `miniprogram/`
- pages/: 页面
- components/: 组件
- utils/: 工具函数
- custom-tab-bar/: 自定义 tab

---

## 6. 数据库写入口清单（待验证）

需确认以下路由/函数是否涉及写库（INSERT/UPDATE/DELETE）:

| 路径/函数 | 文件 | 怀疑写库 |
|-----------|------|----------|
| `/api/import` | app.py | **是** — 上传导入 |
| `/api/import_from_downloads` | app.py | **是** — 批量导入 |
| `/api/import_preview` | app.py | 可能 预览 |
| `/api/import_product_master` | app.py | **是** |
| `/api/platform_products_sync` | app.py | **是** — 同步平台商品 |
| `/api/sync_products_category` | app.py | **是** — 同步品类 |
| `/api/repair_recalc_unit_price` | app.py | **是** — 修复单价 |
| `/api/repair_swap_amount_cost` | app.py | **是** — 修复金额/成本 |
| `/api/profit_share/rule` (POST) | app.py | **是** |
| `/api/profit_share/exclude_categories` (POST/DELETE) | app.py | **是** |
| `/api/profit_share/calculate` (POST) | app.py | **是** |
| `/api/tax_analysis/import_invoice` | app.py | **是** |
| `/api/tax_analysis/import_full_invoice` | app.py | **是** |
| `/api/auth/feishu_callback` | app.py | **是** — 写 external_access |
| `/api/auth/approve` (POST) | app.py | **是** |
| `/api/price_compare_daily` (POST) | app.py | 可能 |
| `/api/marketing_report` (POST) | app.py | **是** |
| `/api/ai_chat` | app.py | 可能 |
| `import_logic.py` 中所有 import_* | import_logic.py | **是** |
| `labor_routes.py` 中人力成本写接口 | labor_routes.py | **是** |

---

## 7. 模块归属矩阵

| 文件/模块 | 导入(ingest) | 清洗(clean) | 分析(analyze) | 展示(serve_web) | 小程序(serve_mini) |
|-----------|:---:|:---:|:---:|:---:|:---:|
| app.py 导入路由 | ✅ | ✅ | ✅ | ✅ | |
| app.py KPI/概览路由 | | | ✅ | ✅ | |
| app.py 品类路由 | | | ✅ | ✅ | |
| app.py 利润/销售路由 | | | ✅ | ✅ | |
| app.py 库存路由 | | | ✅ | ✅ | |
| app.py 经营分析路由 | | | ✅ | ✅ | |
| app.py 商品档案路由 | ✅ | | | ✅ | |
| app.py 收益分账路由 | | ✅ | ✅ | ✅ | |
| app.py 税务分析路由 | ✅ | | ✅ | ✅ | |
| app.py 比价路由 | | | ✅ | ✅ | |
| app.py 红背篓路由 | | | ✅ | ✅ | |
| app.py 导入路由 | ✅ | ✅ | | | |
| app.py auth 路由 | | | | ✅ | ✅ |
| import_logic.py | ✅ | ✅ | | | |
| analytics.py | | | ✅ | | |
| labor_routes.py | ✅ | ✅ | ✅ | ✅ | |
| routes_mobile.py | | | | | ✅ |
| mobile_bi.py | | | ✅ | | ✅ |
| routes_biz_enhanced.py | | | ✅ | ✅ | |
| routes_ops.py | | | ✅ | ✅ | |
| routes_sales.py | | | ✅ | ✅ | |
| routes_category.py | | | | ✅ | |
| routes_insights.py | | | ✅ | ✅ | |
| wechat_api.py | | | | | ✅ |
| auth.py | | | | ✅ | ✅ |

---

## 8. 统计总结

| 指标 | 数值 |
|------|------|
| app.py 路由数 | ~130 |
| app.py 函数(def)数 | ~191 |
| 总 Python 文件（核心） | ~14 |
| 总代码行（核心 Python） | ~25,024 |
| 已拆出 Blueprint 数 | 8 |
| 前端 HTML 页面数 | ~13 |
| 静态 JS 文件数 | 4 |
| 写库入口（估计） | ~30+ |
| 脚本文件(scripts/) | ~40 (SQL + sh + py) |

### 最危险的 5 个耦合点

1. **app.py (8777 行) — 配置+路由+鉴权+业务逻辑全部混合**
   - 风险: 一个修改影响所有 API，难以隔离测试
   - 建议: Phase 1 先抽 core/, Phase 2 按域拆 Blueprint

2. **import_logic.py (2841 行) — 导入逻辑与清洗混合**
   - 风险: 导入/清洗/验证写在同一函数链中
   - 建议: 分 ingest/pipeline.py + clean/ 两阶段

3. **analytics.py (1971 行) — 分析计算与 HTTP 概念混合**
   - 风险: 部分函数直接依赖 request.args
   - 建议: 迁到 analyze/ 后纯计算，路由只做参数提取 + jsonify

4. **index.html (5530 行) — 前端所有页面内联在单文件**
   - 风险: 4200+ 行内联 JS，与后端 API 路径强耦合
   - 建议: 拆成 static/js/pages/ 按页分离

5. **labor_routes.py (1740 行) — 人力路由+导入+分析混合**
   - 风险: 同时依赖 import_logic（导入Excel）和 analytics（计算指标）
   - 建议: 分离 labor_import / labor_analyze / labor_routes（仅 HTTP 层）

---

## 9. 建议阶段顺序

```
Phase 0 ✅ (当前) — 盘点冻结
Phase 1 — core/ 内核抽离（_effective_store_id, _query_filters, 缓存, DB连接）
Phase 2 — ingest/ + clean/ 从 import_logic 剥离
Phase 3 — analyze/ 从 analytics.py + app.py 剥离
Phase 4 — serve_web/ Blueprint 化，app.py 瘦身
Phase 5 — serve_mini/ 小程序独立
Phase 6 — app.py 收尾 < 800 行 + 文档
```
