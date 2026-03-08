# 外网访问错误排查（1033 / 502）

## Error 502 Bad Gateway

当访问 https://htma.greatagain.com.cn 出现 **502 Bad Gateway**：  
表示 **Cloudflare 能连上隧道，但源站（本机看板）无响应**。通常是看板进程未运行或未监听 5002。

**处理步骤（在跑看板的那台机器上）：**

1. 检查 5002 是否在监听：`lsof -i :5002`
2. 若无输出，先启动看板：
   ```bash
   cd /Volumes/ragflow/hotmaxx/hotmaxxflag
   bash scripts/start_htma.sh
   ```
   或通过 launchd：`launchctl load ~/Library/LaunchAgents/com.htma.dashboard.plist`
3. 确认本机可访问：`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5002/api/health` 应返回 200
4. 若隧道由 launchd 管理，确认隧道在跑：`launchctl list | grep com.htma.tunnel` 且 `pgrep -fl cloudflared`

---

## Error 1033（Cloudflare Tunnel 无法解析）

当出现 **Error 1033**：  
「Cloudflare is currently unable to resolve it」→ 说明 **cloudflared 未在跑或未连上 Cloudflare**。

**若遇到新 API 外网 404**（如 `/api/brand_categories`、`/api/supplier_categories`）：是看板进程未重启，新路由未加载。详见 [新增API后需重启看板.md](./新增API后需重启看板.md)，或直接执行 `bash scripts/restart_dashboard_for_new_apis.sh`。

## 1. 本机先做这两步

### ① 结束旧的 cloudflared（若有）

在**本机终端**执行（避免隧道僵死或重复）：

```bash
pkill -x cloudflared
```

若提示无权限，可在 **活动监视器** 中搜索 `cloudflared`，选中后结束进程。

### ② 准备隧道 Token 并启动

- **有 .tunnel-token 时**（项目根目录已有该文件且内容为一行 Token）：

  ```bash
  cd /Volumes/ragflow/hotmaxx/hotmaxxflag
  bash scripts/start_tunnel_htma.sh
  ```

- **没有 .tunnel-token 时**：
  1. 登录 **https://one.dash.cloudflare.com** → **网络** → **隧道** → 找到对应隧道（如 htma）。
  2. 复制「使用令牌运行」里的 Token（`eyJ...` 一整段）。
  3. 在项目根目录创建 `.tunnel-token`，内容只放这一行 Token，保存。
  4. 再执行：`bash scripts/start_tunnel_htma.sh`

## 2. 确认看板在跑

隧道会把外网流量转到本机 **5002**，看板必须在本机监听 5002：

```bash
lsof -i :5002
```

若无输出，先启动看板再启动隧道，例如：

```bash
bash scripts/deploy_and_verify_labor.sh
# 或
launchctl load ~/Library/LaunchAgents/com.htma.dashboard.plist
```

## 3. 开机/锁屏后自动跑隧道（可选）

若已用 `bash scripts/install_launchd_htma.sh` 装过服务，且项目根目录有 `.tunnel-token`：

```bash
launchctl load ~/Library/LaunchAgents/com.htma.tunnel.plist
```

查看是否在跑：

```bash
launchctl list | grep com.htma
pgrep -fl cloudflared
```

## 4. 仍报 1033 时

- 看隧道日志：`tail -30 /Volumes/ragflow/hotmaxx/hotmaxxflag/logs/tunnel.err.log`
- 确认本机网络正常、能访问外网。
- 到 **one.dash.cloudflare.com** 看该隧道状态是否为「已连接」；必要时在控制台里重启或重新复制 Token 更新 `.tunnel-token` 后再执行 `start_tunnel_htma.sh`。
