# 人力成本 API 与部署说明

## 1. 接口说明

- **GET** `/api/labor_cost_analysis`  
  - 可选参数：`month=YYYY-MM`（不传则取库中最新月份）  
  - 返回：`success`、`report_month`、`leaders[]`、`fulltime[]`、`summary`（含 `by_category` 类目总体工资）

- 服务端已支持 **GET / HEAD / OPTIONS**，便于 CORS 预检与正常请求。

## 2. 若出现 405 Method Not Allowed

405 通常表示**反向代理（如 Nginx）未放行 GET 方法**。请在前端服务器配置中对该路径允许 GET，例如 Nginx：

```nginx
location /api/labor_cost_analysis {
    # 允许 GET（及 OPTIONS 预检）
    if ($request_method = 'OPTIONS') {
        add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS';
        add_header 'Access-Control-Allow-Origin' '*';
        return 204;
    }
    proxy_pass http://后端地址;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

或确保 `location /api/` 的 `proxy_pass` 不会限制方法，使 GET 能转发到 Flask。

## 3. 检查数据与接口

在项目根目录执行（需已安装依赖、MySQL 可连）：

```bash
./scripts/check_labor_cost_api.sh
# 或指定线上地址
./scripts/check_labor_cost_api.sh https://htma.greatagain.com.cn
```

脚本会：  
- 查询 `t_htma_labor_cost` 各月份、类型的条数；  
- 对给定 base_url 请求 `GET /api/labor_cost_analysis` 并打印 HTTP 状态与摘要。  
若返回 405，脚本会提示检查反向代理是否允许 GET。

## 4. 锁屏/后台常驻（保证锁屏时服务也可用）

看板需**常驻后台**且**锁屏、息屏时不睡眠**，才能保证随时可访问（含人力成本等接口）。推荐使用项目自带的 launchd 安装脚本：

```bash
# 在项目根目录执行（会安装防睡眠 + 看板服务，锁屏后仍可访问 http://127.0.0.1:5002）
bash scripts/install_launchd_htma.sh
```

- **防睡眠**：`com.htma.keepawake` 运行 `caffeinate -s -i`，锁屏后系统不进入睡眠，看板与定时任务照常运行。  
- **看板服务**：`com.htma.dashboard` 由 launchd 托管，不依赖终端或 Cursor，退出/锁屏后仍可访问。  
- 若看板在 launchd 下启动失败（如 `launchctl list` 显示退出码 78），可查看 `logs/dashboard.err.log` 排查；临时恢复访问可执行：`cd 项目根 && .venv/bin/python htma_dashboard/app.py`（后台运行）。

常用命令：

- 查看状态：`launchctl list | grep com.htma`  
- 停止看板：`launchctl unload ~/Library/LaunchAgents/com.htma.dashboard.plist`  
- 再次启动：`launchctl load ~/Library/LaunchAgents/com.htma.dashboard.plist`

## 5. 导入去重

- **Excel 导入**：组长表已按**岗位名去重汇总**（同一岗位多行合并为一条，金额求和后再写入）；组员表按行写入，依赖表唯一键 `(report_month, position_type, position_name, store_id)` 做 ON DUPLICATE KEY UPDATE，同一岗位多行会更新为最后一行。  
- 若组员表也需按岗位汇总后写入，可与组长表一致改为“先按岗位聚合再插入”。
