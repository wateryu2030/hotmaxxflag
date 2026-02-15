# 方案A 部署完成说明

## 一、已完成内容

### 1. 数据检索与确认

- **库存表** t_htma_stock：120,811 条
- **销售表** t_htma_sale：90,853 条
- **毛利表** t_htma_profit：13,235 条
- **日期范围**：2025-12-19 ~ 2026-02-08
- **门店**：沈阳超级仓

### 2. 表结构

沿用现有 `scripts/01_create_tables.sql` 定义，无需新建表。

### 3. JimuReport 配置

- **数据源**：htma_drag_001（好特卖数据，连接 htma_dashboard 库）
- **7 个数据集**：
  - htma_kpi_sale - 总销售额
  - htma_kpi_profit - 总毛利
  - htma_kpi_rate - 平均毛利率
  - htma_kpi_stock - 库存总额
  - htma_cat_pie - 品类销售额占比（饼图）
  - htma_daily_trend - 日销售额趋势（柱状图）
  - htma_inv_alert - 低库存预警 SKU 数

### 4. BI 大屏

- **名称**：好特卖沈阳超级仓运营看板
- **ID**：htma_dash_shenyang_001
- **内容**：
  - 4 个 KPI 数字卡片：总销售额、总毛利、平均毛利率、库存总额
  - 品类销售额占比（饼图 Top5+其他）
  - 日销售额趋势（柱状图）
  - 低库存预警 SKU 数

### 5. 数据区间

当前 SQL 使用**近 30 天**作为默认区间（`DATE_SUB(CURDATE(), INTERVAL 30 DAY)` ~ `CURDATE()`）。库存总额和预警取最新库存日期。

---

## 二、访问地址

| 页面 | 地址 |
|------|------|
| **好特卖沈阳超级仓运营看板** | http://127.0.0.1:8085/jmreport/view/htma_dash_shenyang_001 |
| 好特卖销售明细（原报表） | http://127.0.0.1:8085/jmreport/view/8946110000000000001 |
| 仪表盘设计列表 | http://127.0.0.1:8085/drag/list |

---

## 三、重新部署

如需重新执行方案 A 部署：

```bash
cd /Users/document/好特卖超级仓/数据分析
mysql -h 127.0.0.1 -u root -p62102218 jimureport < scripts/add_htma_dashboard_plan_a.sql
```

---

## 四、常见错误与处理

### 1. Network Error / 白屏

**原因**：浏览器扩展（如通义、Tampermonkey 等）会干扰对 `127.0.0.1` 的请求。

**处理**：
- 使用**无痕模式**（Ctrl+Shift+N / Cmd+Shift+N）打开报表
- 或在扩展设置里对 `http://127.0.0.1:8085` 禁用相关扩展

### 2. TypeError: Cannot convert undefined or null to object (jmsheet.js)

**原因**：图表报表的 `json_str` 缺少 `rows`、`cols` 等字段，前端 jmsheet 访问时报错。

**处理**：执行修复脚本：

```bash
mysql -h 127.0.0.1 -u root -p62102218 jimureport < scripts/fix_htma_dashboard_jmsheet.sql
```

### 3. 图表数据不显示时

1. 打开 **仪表盘设计**：http://127.0.0.1:8085/drag/list
2. 找到「好特卖沈阳超级仓运营看板」，点击编辑
3. 检查各组件是否绑定到对应数据集（htma_kpi_sale、htma_cat_pie 等）
4. 在「数据集管理」中测试各 SQL 是否返回数据

若图表需使用不同 extData 结构，可在设计器中调整后保存。

---

## 五、相关文件

| 文件 | 用途 |
|------|------|
| `scripts/add_htma_dashboard_plan_a.sql` | 方案 A 一键部署脚本 |
| `scripts/fix_htma_dashboard_jmsheet.sql` | 修复 jmsheet TypeError（补充 rows/cols 等） |
| `scripts/jimureport/*.sql` | 各数据集 SQL 参考 |
| `docs/好特卖超级仓-经营展示方案建议.md` | 展示方案说明 |
