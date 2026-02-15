# 在 JimuReport 中连接好特卖数据（htma_dashboard）

Excel 已通过脚本导入到 MySQL 库 `htma_dashboard`，在 JimuReport 里用「数据源」连接即可，无需再上传 Excel。

## 一、数据已导入情况

| 表名 | 说明 | 当前数据量级 |
|------|------|--------------|
| t_htma_sale | 销售明细（日期、商品、品类、销量、销售额、成本、毛利） | 约 34 万+ 条 |
| t_htma_stock | 库存（日期、商品、品类、库存数量、库存金额） | 约 12 万+ 条 |
| t_htma_profit | 毛利汇总（按日期+品类） | 已按销售表汇总 |

数据来源：下载目录下的「销售日报_默认」「销售汇总_默认」「实时库存」Excel，由 `scripts/import_excel_to_mysql.py` 导入。

## 二、在 JimuReport 中配置数据源

1. 打开 **报表设计** 或 **仪表盘设计**（如 http://127.0.0.1:8085/drag/list）。
2. 进入 **数据源管理**（或 数据集 → 数据源）。
3. **新增数据源**：
   - 类型：MySQL
   - 主机：`127.0.0.1`
   - 端口：`3306`
   - 数据库：`htma_dashboard`
   - 用户名：`root`
   - 密码：`62102218`
4. 测试连接通过后保存。

## 三、在仪表盘/报表中使用

- **数据集**：选择该数据源后，新建「SQL 数据集」，编写查询（可参考 `scripts/jimureport/` 下示例 SQL），或直接选表。
- **图表/表格**：绑定到上述数据集即可做销售额、毛利、品类、库存等分析。

## 四、以后更新 Excel 数据

在终端执行（需先安装 Python 依赖，见脚本内说明）：

```bash
cd /Users/document/好特卖超级仓/数据分析
.venv/bin/python scripts/import_excel_to_mysql.py /Users/apple/Downloads
```

会把下载目录下最新的「销售日报_默认」「销售汇总_默认」「实时库存」再次导入并刷新毛利表。
