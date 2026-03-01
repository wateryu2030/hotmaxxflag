# 好特卖运营看板 - 运行说明

好特卖沈阳超级仓临期折扣零售运营看板，支持销售/毛利/库存分析、品类排行、周几对比、AI 智能分析建议。

## 快速启动

```bash
# 1. 初始化（首次或表结构变更时）
npm run htma:setup

# 2. 启动服务
npm run htma:run
```

访问 http://127.0.0.1:5002

**AI 分析建议**：点击右上角「✨ AI 分析建议」按钮，基于当前数据自动生成品类毛利、动销、库存等智能建议。

## 一键部署

```bash
npm run htma:standalone
# 或
bash scripts/deploy_htma_standalone.sh
```

## 数据导入

1. 打开 http://127.0.0.1:5002/import
2. 上传 Excel：
   - **销售日报**：含货号、销售日期、销售金额、参考金额等（39 列）
   - **销售汇总**：54 列格式
   - **实时库存**：24 列
   - **品类附表**：大类编、大类名称、中类编、中类名称、小类编、小类名称

或命令行自动导入（从 ~/Downloads 查找）：

```bash
npm run htma:import
```

### 从下载目录自动导入（推荐：含去重与数据完整性）

将 **销售日报**、**销售汇总**、**实时库存** Excel 放入指定目录后，可一键完成导入、去重、刷新毛利/品类/商品，确保数据完整可靠。

- **本机命令行**（默认目录 `~/Downloads`）：
  ```bash
  bash scripts/run_auto_import.sh
  # 或指定目录
  bash scripts/run_auto_import.sh /path/to/excel
  ```
- **导入页按钮**：打开 http://127.0.0.1:5002/import ，点击「从下载目录自动导入」。此时使用**服务器**上的目录：项目下的 `downloads/` 或环境变量 `IMPORT_DOWNLOADS_DIR`。将 Excel 放到该目录后点击即可。
- **定时自动执行**（macOS）：每日 6:00 从 ~/Downloads 自动导入（有文件则执行）：
  ```bash
  bash scripts/install_launchd_auto_import.sh
  ```

## 前置条件

- MySQL 运行中，已创建数据库 `htma_dashboard`
- 执行过 `scripts/01_create_tables.sql` 建表
- 执行过 `scripts/04_create_category_table.sql` 创建品类表
- 执行过 `python scripts/run_add_columns.py` 补齐扩展列

## 修复说明

- **导入误清空**：已修复。仅当上传合法 .xls/.xlsx 文件时才清空表，无效文件不会触发清空。
- **品类级联**：优先从 `t_htma_category`（品类附表）读取；无则从销售表兜底。
