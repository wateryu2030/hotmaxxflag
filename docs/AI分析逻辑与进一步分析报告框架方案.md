# AI 分析逻辑与进一步分析报告框架方案

## 一、现有 AI 分析逻辑概览

### 1.1 智能分析建议（`/api/insights`）

**入口**：看板顶部「AI 分析建议」按钮，调用 `analytics.build_insights(conn, store_id)`。

**数据来源**：`t_htma_profit`、`t_htma_sale`、`t_htma_stock`，近 90 天/30 天。

**输出结构**：`insights[]`，每项含 `type`（warning/success/info）、`title`、`desc`、`action`。

**当前逻辑要点**：

| 序号 | 分析维度       | 逻辑简述 |
|------|----------------|----------|
| 1    | 品类毛利率     | 低毛利(<15% 且销售额>5k)、高毛利(≥35% 且>3k) 品类，给出关注/推广建议 |
| 2    | 销售集中度     | 二八分析：前 N 个品类贡献约 80% 销售额 |
| 3    | 低库存预警     | 库存<50 的 SKU 数>20 时提示断货风险 |
| 4    | 负毛利异常     | 近 30 天负毛利记录条数及核查建议 |
| 5    | 整体毛利率     | 与 20%/30% 对比，健康度提示 |
| 6    | 动销/周转      | 动销 SKU 数、平均每 SKU 销量，临期折扣动销建议 |
| 7    | 数据新鲜度     | 最新销售日期距今>3 天提醒导入 |
| 8    | 退货/赠送      | 退货占比>5% 预警；赠送占比提示 |
| 9    | 品牌集中度     | 前 3 品牌销售占比>50% 提示 |
| 10   | 库存周转       | 按销速估算周转天数，>60 天预警、<30 天肯定 |
| 11   | 数据质量       | 成本缺失、售价缺失、同 SKU 多品类数量 |

---

### 1.2 AI 对话（`/api/ai_chat`）

**入口**：看板「经营分析」页内 AI 对话框，`analytics.ai_chat_response(conn, user_message, report_summary)`。

**上下文**：`_ai_fetch_context(conn, days=30, include_monthly=?)`，拉取：

- 总销售额/总毛利/毛利率、动销 SKU、负毛利条数及损失、负毛利 Top 商品
- 高毛利品类、动销 Top 品类、低库存畅销品类、性价比货品
- 退货/赠送金额及占比、品牌/供应商 Top、库存周转天数、总库存额
- 数据质量（缺失成本/售价、同 SKU 多品类）
- 可选：近几个月按月销售/毛利、上月品类毛利结构（用于「结合前几个月」「预测」）

**意图识别与回复策略**（节选）：

| 用户意图           | 触发关键词示例                     | 回复内容要点 |
|--------------------|------------------------------------|--------------|
| 销售额目标         | 销售突破 X 万、营销、营收          | 近几个月走势；缺口；引流爆品、断货补货、促销、异业、节点 |
| 毛利目标           | 毛利 X 万、提高毛利、利润          | 本月至今 vs 目标；高毛利品类；负毛利/断货/数据质量动作 |
| 负毛利/怎么验证    | 负毛利、验证、诊断                 | 负毛利条数、损失、Top 商品 + 诊断提示（录入错误/清仓） |
| 断货/补货          | 断货、补货、优先级                 | 低库存畅销品类、断货损失估算、优先补货建议 |
| 性价比/货品        | 性价比、哪些货品、高毛利            | value_skus 列表（高毛利+有动销+合理单价） |
| 移动/异业          | 移动、异业、合作                   | 结合 build_marketing_report 的异业联动区摘要 |
| 结合几个月/预测    | 几个月、结合、预测、品类           | 多月走势 + 上月品类毛利结构 + 简单趋势建议 |
| 通用/无匹配        | 其他                               | 综合建议：负毛利、退货/赠送、高毛利品类、断货、周转、数据质量、异业 |

---

### 1.3 营销报告（`build_marketing_report`）

**入口**：看板「生成营销报告」按钮，可先调用 `build_marketing_report(conn, mode="market_expansion")`，再作为 `report_summary` 传入 AI 对话。

**模式**：

- **market_expansion**：市场拓展+异业合作决策报告  
  - 商业结论（销冠/引流/断货/负毛利 + 移动合作价值）  
  - 1. 市场引流爆品区（动销 Top 品类、断货预警与损失估算）  
  - 2. 利润收割主力区（大类贡献 Top5）  
  - 3. 问题品清仓区（负毛利明细 + 诊断提示）  
  - 4. 中国移动异业联动专属区（满额赠话费、办套餐送券、设点建议）  
  - 5. 总部审批·商业价值总结  

- **internal**：进销存营销分析（动销 Top10、高毛利 Top10、黄金商品、需补货、滞销高库存、品类毛利 Top5 等 + 专家建议）

**数据来源**：与 `_ai_fetch_context` 同源（`t_htma_sale` + `t_htma_stock` + 排除品类），按品类/商品聚合。

---

## 二、现有数据与下钻分析结果

### 2.1 消费洞察 API（`/api/consumer_insight`）

**与 KPI 周期一致**：`_query_filters()` 得到 `date_cond`、`category_cond`（大类/中类/小类/商品筛选）。

**返回结构**（`_get_consumer_insight_data()`）：

| 模块           | 说明 |
|----------------|------|
| overview       | 总销售额、总毛利、毛利率、总销量、动销 SKU、总 SKU、动销率、客单价、平均零售价、库存周转、环比、退货率等 |
| bi_insight     | 基于 overview + 环比 + 品类矩阵生成的 BI 一句话趋势与要点 |
| category_matrix| 品类贡献矩阵：品类、动销 SKU、销量、销售额、销售占比、毛利、毛利占比、毛利率、平均售价、平均折扣率 |
| category_top_sale / category_top_profit / category_top_margin | 品类 Top 列表（销售/毛利/毛利率） |
| brand          | 品牌贡献：品牌、动销 SKU、销售额、毛利、销量、毛利率、贡献% |
| price_band     | 价格带：区间、SKU 数、销售额、销量、毛利率、占比、平均折扣率 |
| supplier       | 供应商贡献 |
| distribution   | 经销方式（代销/购销）占比 |
| discount_band  | 折扣区间分布 |
| new_product    | 新品相关指标 |
| return_rate_pct / return_by_cat | 退货率及按品类退货 |
| color_style     | 色系/风格（若有） |
| period_over_period | 本期 vs 上期销售额、环比% |
| zero_sale_skus / high_discount_low_margin | 零销售 SKU、高折扣低毛利预警 |
| **drill_brands**   | **下钻：选中品类下的品牌列表**（品牌、销售额、毛利、销量、毛利率、动销 SKU） |
| **drill_styles**   | **下钻：选中品类+品牌下的款式(品名)列表**（品名、销售额、毛利、销量、毛利率、动销 SKU） |
| **drill_sku_rank** | **下钻：选中品类+品牌+款式下的货号明细**（货号、品名、品牌、销售额、毛利、销量、毛利率、平均折扣率） |

### 2.2 下钻层级与参数

- **一级**：仅选 `category`（大类/中类/小类口径）→ 返回该品类下 `drill_brands`。  
- **二级**：`category` + `brand` → 返回该品类+品牌下 `drill_styles`。  
- **三级**：`category` + `brand` + `product_name` → 返回该品类+品牌+款式下 `drill_sku_rank`。

前端消费洞察页：品类矩阵 → 点击行展开品牌 → 点击品牌展开款式 → 点击款式展开货号明细，与上述 API 一致。

### 2.3 经营分析/其他数据

- 经营分析：退货/赠送、库存周转、数据质量、品牌下钻（`/api/brand_categories`）等。
- 品类排行（看板）：大类/中类/小类结构、下钻到品牌/商品/销售与库存。
- 商品档案下钻：`/api/product_master_drill`（品类→品牌列表；品类+品牌→SKU 销售明细）。

---

## 三、现有逻辑与数据的缺口（为何要「进一步」）

1. **insights / AI 对话 / 营销报告** 主要用「汇总 + 品类/商品级聚合」，**未显式接入消费洞察下钻结果**（drill_brands / drill_styles / drill_sku_rank）。
2. **下钻结果** 当前仅用于前端展示，**未反哺到**：  
   - 一键「AI 分析建议」卡片；  
   - AI 对话的上下文（例如「当前选中品类/品牌下的问题」）；  
   - 营销报告中的「某品类/某品牌专项建议」。
3. **报告输出形态** 以文本为主，缺少**结构化报告框架**（固定章节 + 可选模块 + 与下钻维度绑定），不便于扩展「按品类/按品牌」的专项页或导出。

因此，下一步应：**在保留现有 AI 逻辑与数据口径的前提下，把下钻分析结果纳入统一的分析与报告框架，并输出可复用的「分析报告框架」**。

---

## 四、进一步分析报告框架方案

### 4.1 目标

- **统一数据源**：继续使用现有 `_query_filters()`、`_get_consumer_insight_data()`、`_ai_fetch_context()`、`build_insights()` 等，保证与看板 KPI、消费洞察、经营分析一致。
- **显式纳入下钻**：将 `drill_brands` / `drill_styles` / `drill_sku_rank` 作为「当前视角」输入，参与生成建议与报告段落。
- **可扩展结构**：报告采用固定章节 + 可选模块，便于后续增加「按品类/按品牌」的专项段、或对接导出/飞书。

### 4.2 报告框架结构（建议）

```
1. 总览与商业结论（现有 insights + 环比 + 一句话结论）
   - 1.1 周期与核心 KPI（销售额、毛利、毛利率、动销、周转、退货率）
   - 1.2 智能建议卡片（现有 build_insights 的 11 类）
   - 1.3 商业结论句（可复用 build_marketing_report 的首段或由 AI 摘要）

2. 品类与结构（现有 category_matrix + 下钻摘要）
   - 2.1 品类贡献 Top N（销售/毛利/毛利率）
   - 2.2 当前下钻视角摘要（若存在 category/brand/product_name）
     - 若仅选品类：该品类下品牌 Top5、占比
     - 若选品类+品牌：该品牌下款式 Top5、占比
     - 若选品类+品牌+款式：该款式下货号 Top10、销售/毛利/折扣
   - 2.3 品类维度建议（低毛利/高毛利/断货品类，可引用 insights）

3. 品牌与供应商（现有 brand + supplier + 下钻）
   - 3.1 品牌贡献 Top N
   - 3.2 若当前下钻到「某品类」：该品类下品牌排名与建议
   - 3.3 供应商贡献与集中度

4. 价格、经销与促销（现有 price_band / distribution / discount_band）
   - 4.1 价格带与销售占比
   - 4.2 经销方式占比
   - 4.3 折扣区间与高折扣低毛利预警（high_discount_low_margin）

5. 问题与行动（负毛利、断货、滞销、数据质量）
   - 5.1 负毛利明细与诊断（现有 neg_top + _neg_diagnosis_hint）
   - 5.2 断货/补货优先级（low_stock_cats / need_replenish）
   - 5.3 滞销/高库存（若有）
   - 5.4 数据质量（缺失成本/售价、同 SKU 多品类）
   - 5.5 退货/赠送（占比及按品类若有）

6. 市场拓展与异业（可选，复用 build_marketing_report 的 1–5 段）
   - 6.1 引流爆品区
   - 6.2 利润收割主力区
   - 6.3 问题品清仓区
   - 6.4 异业联动建议
   - 6.5 总部审批·商业价值总结

7. 附录：当前下钻明细（可选）
   - 当存在 category/brand/product_name 时，输出 drill_brands / drill_styles / drill_sku_rank 的简要表（前 N 行），便于附在报告末尾或导出
```

### 4.3 与现有实现的对接方式

| 模块           | 现有实现                     | 对接方式 |
|----------------|------------------------------|----------|
| 1.1 周期与 KPI | overview（consumer_insight） | 直接使用 overview + period_over_period |
| 1.2 建议卡片   | build_insights               | 直接调用，输出 type/title/desc/action |
| 1.3 商业结论   | build_marketing_report 首段  | 取 market_expansion 前几行或单独写一句 |
| 2.1 品类 Top   | category_matrix / category_top_* | 已有，直接填入 2.1 |
| 2.2 下钻摘要   | drill_brands / drill_styles / drill_sku_rank | **新增**：根据 category/brand/product_name 是否存在，写一段「当前视角」摘要（Top5/Top10） |
| 3              | brand / supplier             | 已有；2.2 可引用「该品类下品牌」 |
| 4              | price_band / distribution / discount_band / high_discount_low_margin | 已有 |
| 5              | _ai_fetch_context 的 neg_* / low_stock / 数据质量 / 退货 | 已有；统一归到「问题与行动」 |
| 6              | build_marketing_report(mode="market_expansion") | 按章节拆成 6.1–6.5 填入 |
| 7              | drill_* 原始列表              | **新增**：仅当有下钻参数时，附简要表 |

### 4.4 下钻结果如何「反哺」AI 与报告

- **报告生成**：  
  - 调用 `_get_consumer_insight_data()` 时传入当前请求的 `category` / `brand` / `product_name`（与消费洞察页一致），拿到 `drill_brands` / `drill_styles` / `drill_sku_rank`。  
  - 在框架的 2.2、7 中写入「当前品类/品牌/款式」的摘要与明细。

- **AI 对话**：  
  - 若前端能传「当前选中的品类/品牌/款式」（与消费洞察 Tab 一致），可在 `ai_chat_response` 中增加可选参数 `current_drill`（如 `{category, brand, product_name}`）。  
  - `_ai_fetch_context` 或单独函数按该维度过滤/聚合，得到「该品类下品牌 Top」「该品牌下款式 Top」等，再在回复中引用（例如：「当前选中品类 X 下，品牌 A、B、C 贡献最高，建议……」）。

- **AI 分析建议（insights）**：  
  - 保持全局建议不变；**可选**增加「当存在下钻维度时」的 1–2 条：如「当前品类下，品牌集中度较高，前 3 品牌占比 XX%」，数据来自 `drill_brands` 的占比汇总。

### 4.5 实施优先级建议

1. **Phase 1**：在现有「生成营销报告」或新接口上，按 4.2 的 1–6 输出**结构化文本报告**（不改变现有 build_insights / ai_chat_response 行为），其中 2.2、7 在请求带 `category`/`brand`/`product_name` 时写入下钻摘要与附录。  
2. **Phase 2**：AI 对话支持 `current_drill`，并在回复中引用「当前品类/品牌/款式」的汇总或 Top 列表。  
3. **Phase 3**：insights 可选增加「下钻视角」的 1–2 条建议；报告支持导出（如 PDF/Word）或飞书卡片。

---

## 五、小结

- **现有 AI 分析逻辑**：`build_insights`（11 类建议）、`ai_chat_response`（意图识别 + 上下文 `_ai_fetch_context`）、`build_marketing_report`（市场拓展/进销存两种模式），均已基于现有表结构且与 KPI/经营分析一致。  
- **现有数据与下钻**：消费洞察 API 已提供完整的 **品类 → 品牌 → 款式 → 货号** 四级下钻（`drill_brands` / `drill_styles` / `drill_sku_rank`），目前仅用于前端展示。  
- **进一步方案**：在上述逻辑与数据不变的前提下，增加**统一的分析报告框架**（固定章节 + 可选模块），把**下钻分析结果**纳入报告 2.2 与附录、并可选反哺 AI 对话与 insights，从而形成「总览 + 品类结构 + 下钻视角 + 问题与行动 + 异业」的一体化分析报告与可扩展结构。

按 4.5 的 Phase 1→2→3 实施，即可在保留现有行为的前提下，逐步交付「结合下钻分析的进一步分析报告」能力。
