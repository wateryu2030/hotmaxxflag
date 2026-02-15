# JimuReport 数据集 SQL 示例

本目录存放好特卖超级仓数据看板在 JimuReport 中可直接使用的 SQL 数据集模板。

## 文件说明

| 文件 | 对应组件 | 参数 | 说明 |
|------|----------|------|------|
| `01a_kpi_total_sale.sql` | 数字卡片 | start_date, end_date | 总销售额 |
| `01b_kpi_total_profit.sql` | 数字卡片 | start_date, end_date | 总毛利 |
| `01c_kpi_profit_rate.sql` | 数字卡片 | start_date, end_date | 平均毛利率 |
| `01d_kpi_stock_amount.sql` | 数字卡片 | 无 | 库存总额（取最新日期） |
| `02_category_analysis.sql` | 饼图、柱状图 | start_date, end_date | 品类销售额占比、品类毛利对比 |
| `03_yoy_mom_trend.sql` | 组合图、折线图 | start_date, end_date | 销售额环比、毛利率周同比 |
| `04_inventory_alert.sql` | 预警卡片、明细表 | start_date, end_date, min_stock_threshold | 库存预警、库存-销售明细 |

## 在 JimuReport 中的使用方式

1. **新增数据集**：数据源管理 → 选择 MySQL 数据源 → 新建数据集
2. **选择类型**：选择「SQL 数据集」
3. **粘贴 SQL**：将对应 `.sql` 文件内容粘贴到 SQL 编辑器
4. **配置参数**：
   - 日期参数：`start_date`、`end_date`，类型设为「字符串」或「日期」，可在控件中绑定
   - 库存阈值：`min_stock_threshold`，可设默认值 50
5. **测试**：点击「测试」验证 SQL 执行结果
6. **绑定组件**：在仪表盘组件的数据源中选择该数据集

## 参数占位符说明

JimuReport 支持 `${param}` 形式参数，示例：

- `${start_date}`：开始日期，如 `'2025-01-01'`
- `${end_date}`：结束日期，如 `'2025-02-18'`
- `${min_stock_threshold}`：最小库存阈值，如 `50`

若控件为日期选择器，需确保传参格式与 SQL 中 `DATE` 类型兼容（如 `YYYY-MM-DD`）。
