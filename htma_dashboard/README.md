# 好特卖沈阳超级仓运营看板（独立版）

不依赖 JimuReport，直接读取 MySQL `htma_dashboard` 库，提供轻量级看板。

## 快速启动

```bash
# 一键部署（检查 MySQL、安装依赖、启动服务）
npm run htma:standalone
# 或
bash scripts/deploy_htma_standalone.sh
```

## 手动启动

```bash
cd htma_dashboard
pip install -r requirements.txt
python app.py
```

访问 http://127.0.0.1:5002

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| MYSQL_HOST | 127.0.0.1 | MySQL 主机 |
| MYSQL_PORT | 3306 | MySQL 端口 |
| MYSQL_USER | root | MySQL 用户 |
| MYSQL_PASSWORD | 62102218 | MySQL 密码 |
| PORT | 5002 | 服务端口 |
| HTMA_DAYS | 30 | 统计天数 |

## 数据导入

访问 http://127.0.0.1:5002/import 上传 Excel 文件：

| 文件类型 | 文件名要求 | 对应表 |
|----------|------------|--------|
| 销售日报 | 包含「销售日报」 | t_htma_sale |
| 销售汇总 | 包含「销售汇总_默认」 | t_htma_sale |
| 实时库存 | 包含「实时库存」 | t_htma_stock |

导入前会**清空**对应表，再写入新数据。销售表导入后会自动刷新毛利表。

## API

- `GET /api/health` - 健康检查
- `GET /api/kpi` - 4 个 KPI 卡片
- `GET /api/category_pie` - 品类销售额占比
- `GET /api/daily_trend` - 日销售额趋势
- `GET /api/inv_alert` - 低库存预警 SKU 数
