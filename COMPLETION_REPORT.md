# 好特卖运营看板 · 任务完成报告

生成时间：2026-04-25  

## 环境说明（重要）

- 本项目 **`db_config.py` 使用 MySQL + PyMySQL**，不是 SQLite。文档中若写 SQLite/MySQL 双栈，以代码为准。
- 建议在仓库根目录使用虚拟环境（已存在 `.venv` 时可执行）：
  ```bash
  cd /Volumes/ragflow/hotmaxx/hotmaxxflag
  python3 -m venv .venv
  .venv/bin/pip install -r htma_dashboard/requirements.txt
  HTMA_UNITTEST_DISABLE_AUTH=1 .venv/bin/python -m unittest tests.test_api_contract -v
  ```
- 若曾混用不同 Python 版本创建 `.venv`，请删除 `.venv` 后按上式重建，避免出现 `pip` 与 `python` 的 `site-packages` 版本不一致。

## 测试

| 项 | 状态 |
|----|------|
| `tests.test_api_contract`（4 条） | 已通过 |
| 测试环境变量 `HTMA_UNITTEST_DISABLE_AUTH=1` | 用于在无飞书登录态下断言 KPI/四象限等（**仅测试/本地调试**，生产勿设） |

## 已完成的改进项

### 环境与可运行性

- [x] `requirements.txt` 保持 Flask + PyMySQL 等依赖（未引入 `flask-caching`，改用 `extensions.SimpleTTLCache` 避免部分环境 pip/python 版本错位导致的导入失败）。
- [x] `app.py` 增加 `sys.modules.setdefault("app", …)`，修复 **`python app.py` 启动**时 `routes_*` 中 `_app()` 取不到 `get_conn` 的问题。
- [x] `_auth_enabled()` 支持 `HTMA_UNITTEST_DISABLE_AUTH` 测试旁路。

### 阶段 D / 工程

- [x] 契约测试扩展：`test_mobile_dashboard`；测试类在 `setUpClass` 中统一关闭鉴权并 `sys.modules.pop("app")` 后重新加载，保证与生产导入路径一致。

### 大数据量 / 预聚合（增量落地）

- [x] 新增表结构脚本：`scripts/27_daily_category_stats.sql`（表名 **`daily_category_stats`**：店+日+大类+中类聚合）。
- [x] 刷新脚本：`scripts/refresh_daily_category_stats.py`。
- [x] 服务模块：`htma_dashboard/daily_stats_service.py`（日期边界解析、`try_totals_from_daily_stats`、`refresh_daily_category_stats`）。
- [x] **`/api/kpi`**：在无品类/SKU 筛选时，若预聚合表有数据则 **优先 SUM(daily_category_stats)**，否则回退 `t_htma_sale`（未建表或未刷新时不影响现有行为）。

### 缓存

- [x] `htma_dashboard/extensions.py`：`SimpleTTLCache`（默认 TTL 300s）。
- [x] `routes_sales.api_contribution_structure`：命中缓存则直接返回。

### 分页

- [x] `GET /api/negative_margin_items`：支持 `limit`（默认 500，最大 500）、`offset`；**导出 CSV** 时 `limit` 最大 2000 且不分页。

### 小程序预备

- [x] `GET /api/mobile/dashboard`（`routes_mobile.py`，Blueprint `url_prefix=/api/mobile`）：近 30 天 KPI、TOP 大类、负毛利 SKU 计数；优先读 `daily_category_stats`（有数据时），否则读 `t_htma_sale`；带 120s TTL 缓存。

### 响应式

- [x] `static/index.html`、`static/labor_analysis.html` 已含 `viewport` 与布局样式（本次未大改 UI，仅确认现状）。

## 未「全量」完成或刻意保留的项（说明）

以下项在仓库中 **多数已存在前期实现**（如贡献结构、四象限、品类下钻、退货/赠送、品牌表现、负毛利、热力图等），本次 **未重复开发**；或未在单次迭代中全表替换查询：

- [ ] **所有** 聚合类 API 一律改读 `daily_category_stats`：当前仅 **KPI 全店无筛选** 与 **mobile/dashboard** 走快路径；其余接口仍按原逻辑扫描 `t_htma_sale`（避免一次性大改引入回归）。
- [ ] **Alembic / 统一 `{code,data,msg}` API 壳**：未实施（工作量大，需单独迭代）。
- [ ] **Celery / 异步长报表**：未实施。
- [ ] **四象限散点强制后端抽样**：未改（可按点数阈值再加）。
- [ ] **SQLite 模式**：不适用本仓库主路径。

若 `return_amount` / `gift_amount` 等列不存在，`routes_sales.return_gift_share` 等仍会按既有逻辑返回 skipped/空数据（与历史行为一致）。

## 新增 / 修改的文件

| 文件 | 说明 |
|------|------|
| `htma_dashboard/extensions.py` | 新建：TTL 缓存 |
| `htma_dashboard/daily_stats_service.py` | 新建：预聚合读写与 KPI 快路径 |
| `htma_dashboard/routes_mobile.py` | 新建：移动端 dashboard API |
| `scripts/27_daily_category_stats.sql` | 新建：DDL |
| `scripts/refresh_daily_category_stats.py` | 新建：刷新任务 |
| `htma_dashboard/app.py` | 修改：测试鉴权旁路、`sys.modules["app"]`、KPI 快路径、注册 mobile blueprint |
| `htma_dashboard/routes_sales.py` | 修改：贡献结构缓存、负毛利分页/导出 |
| `tests/test_api_contract.py` | 修改：鉴权旁路 + mobile 用例 |
| `COMPLETION_REPORT.md` | 本文件 |

## 启动与手动冒烟

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag/htma_dashboard
../.venv/bin/python app.py
# 另开终端（可选临时关闭飞书鉴权便于 curl）
curl -s "http://127.0.0.1:5002/api/kpi?period=recent30" | head -c 200
curl -s "http://127.0.0.1:5002/api/four_quadrant?start_date=2026-01-01&end_date=2026-01-31" | head -c 200
curl -s "http://127.0.0.1:5002/api/mobile/dashboard" | head -c 200
```

生产库执行预聚合 DDL 后，可定时跑：

```bash
.venv/bin/python scripts/refresh_daily_category_stats.py "沈阳超级仓" 2026-01-01 2026-04-25
```

## 自动化执行记录（本地 MySQL）

以下已在当前环境通过 **`.venv/bin/python` + `htma_dashboard/db_config`（读取项目根 `.env`）** 自动完成：

- [x] **DDL**：执行 `scripts/27_daily_category_stats.sql` 中的 `CREATE TABLE IF NOT EXISTS daily_category_stats`（已跳过 `USE` 行，使用连接配置中的库名）。
- [x] **刷新**：`scripts/refresh_daily_category_stats.py "沈阳超级仓" 2026-01-01 2026-04-25` → 写入约 **10741** 行（以当时库内 `t_htma_sale` 为准）。

此后 **`/api/kpi`**（无品类/SKU 筛选时）与 **`/api/mobile/dashboard`** 在满足日期范围时会优先读 **`daily_category_stats`**。

## 后台进程

本地若曾启动 `PORT=5019` 的调试服务，可在任务管理器中结束对应 `python app.py` 进程。
