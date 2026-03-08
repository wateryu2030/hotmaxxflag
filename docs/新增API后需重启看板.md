# 新增 API 后外网 404：需重启看板

## 原因

`/api/brand_categories`、`/api/supplier_categories`、`/api/price_band_categories` 等接口已在代码中实现，但访问 **https://htma.greatagain.com.cn** 仍返回 **404**，是因为：

- Flask 在**启动时**加载全部路由；运行中的进程不会自动加载新代码。
- 当前外网指向的那台机器上，看板进程是很早之前启动的，**没有包含这些新路由**。
- 因此只要**重启看板进程**，新路由就会生效。

## 操作步骤（在跑看板的那台电脑上执行）

### 方式一：用 launchd（推荐）

若你曾执行过 `bash scripts/install_launchd_htma.sh`，看板由 launchd 管理，重启方式：

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag

# 一键重启并等待健康检查
bash scripts/openclaw_restart_dashboard_and_verify.sh
```

或手动卸载再加载：

```bash
launchctl unload ~/Library/LaunchAgents/com.htma.dashboard.plist
sleep 2
launchctl load ~/Library/LaunchAgents/com.htma.dashboard.plist
```

### 方式二：手动启动看板

若你是用终端直接运行 `bash scripts/start_htma.sh` 启动的：

1. 在该终端按 **Ctrl+C** 停止当前看板。
2. 再次执行：`bash scripts/start_htma.sh`。

### 方式三：先杀进程再由 launchd 拉起

若不确定看板是否由 launchd 管理，可先释放 5002 端口，**务必先 unload 再 load**（否则会报 Load failed: 5）：

```bash
lsof -ti :5002 | xargs kill -9
sleep 2
launchctl unload ~/Library/LaunchAgents/com.htma.dashboard.plist
sleep 2
launchctl load ~/Library/LaunchAgents/com.htma.dashboard.plist
```

## 故障排除

### `launchctl load` 报错：Load failed: 5: Input/output error

表示该 job 已在 launchd 中加载，不能重复 load。处理：

```bash
launchctl unload ~/Library/LaunchAgents/com.htma.dashboard.plist
sleep 2
launchctl load ~/Library/LaunchAgents/com.htma.dashboard.plist
```

### 重启脚本运行后「看板未就绪」、40 秒超时

1. **看日志**（新启动的进程会往同一日志文件追加）：
   ```bash
   tail -50 /Volumes/ragflow/hotmaxx/hotmaxxflag/logs/dashboard.err.log
   tail -30 /Volumes/ragflow/hotmaxx/hotmaxxflag/logs/dashboard.out.log
   ```
2. **手动前台启动**，看终端里是否有报错（如缺依赖、数据库连不上、端口占用）：
   ```bash
   cd /Volumes/ragflow/hotmaxx/hotmaxxflag
   .venv/bin/python htma_dashboard/app.py
   ```
3. 若手动能正常起来，多半是 launchd 环境（工作目录、环境变量）与终端不一致，可改用「方式二」手动启动，或重新执行一次 `bash scripts/install_launchd_htma.sh` 再重启。

## 如何确认新 API 已生效

重启后稍等几秒，在本机或外网执行：

```bash
curl -s -o /dev/null -w "%{http_code}" "https://htma.greatagain.com.cn/api/brand_categories?period=recent30&brand=test"
# 期望：200（若未登录可能 401，而不是 404）
```

或在浏览器打开经营分析 → 品牌，点击某品牌行展开「该品牌涉及品类」，不再出现 404 即表示已生效。

## 小结

| 现象           | 原因           | 处理                 |
|----------------|----------------|----------------------|
| 新 API 外网 404 | 看板进程未重启 | 在跑看板的那台机器上重启看板 |

代码已包含新路由时，**部署/拉代码后务必重启看板**，新接口才会在外网生效。
