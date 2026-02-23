# Cloudflare 固定外网链接 - 按步操作（账号 wateryu2030@gmail.com）

你已有 Cloudflare 账号，按下面顺序做即可得到**固定地址**（如 https://htma.某域名.com），发给同事长期用。

---

## 第一步：在 Cloudflare 里有一个「域名」（必做）

隧道必须绑在一个「站点（域名）」上，所以需要先有一个域名。

### 若你还没有域名

- **免费**：可到 [Freenom](https://www.freenom.com) 申请免费 .tk/.ml（若仍开放），或 [DuckDNS](https://www.duckdns.org) 得到 xxx.duckdns.org（DuckDNS 不能直接加到 Cloudflare 做主站，需自有域名）。
- **推荐**：在 Cloudflare 或其它注册商买一个便宜域名（如 .com 约 1–10 美元/年）。  
  - 在 Cloudflare：登录 [dash.cloudflare.com](https://dash.cloudflare.com) → 左侧 **「注册域名」** 或 **「Web3」** 旁进「域名」→ 搜索并购买。  
  - 或在 Namecheap、阿里云、腾讯云等购买后，再添加到 Cloudflare。

### 若你已有域名

- 登录 [dash.cloudflare.com](https://dash.cloudflare.com) → 点击 **「添加站点」** → 输入你的域名（如 `example.com`）→ 选择 **免费** 计划 → 按提示把域名的 **NS（ nameserver）** 改成 Cloudflare 给出的两条（如 `xxx.ns.cloudflare.com`），在域名注册商处保存后回 Cloudflare 点「完成检查」。  
- 添加成功后，在「网站」列表里能看到该域名，点进去即可做后面步骤。

**后面步骤里用「你的域名」泛指你添加的这个域名（如 example.com）。**

---

## 第二步：本机用 cloudflared 登录 Cloudflare

1. 打开终端，执行：
   ```bash
   cloudflared tunnel login
   ```
2. 会自动打开浏览器；用 **wateryu2030@gmail.com** 登录（若未登录）。
3. 选择**你要用来做隧道的那个域名**（上一步添加的站点），点 **「授权」**。
4. 终端里出现 “You have successfully logged in” 即表示本机已授权，可关闭浏览器。

---

## 第三步：创建隧道并记下隧道 ID

在终端执行：

```bash
cloudflared tunnel create htma-dashboard
```

- 终端会输出类似：
  ```text
  Created tunnel htma-dashboard with id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
  ```
- **把这段 id（UUID）抄下来**，后面 DNS 和配置文件都要用。
- 同时本机会生成文件：  
  `~/.cloudflared/<上面的隧道ID>.json`  
  例如：`/Users/zhonglian/.cloudflared/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.json`

---

## 第四步：在 Cloudflare 控制台为隧道添加 DNS

1. 打开 [dash.cloudflare.com](https://dash.cloudflare.com) → 登录 **wateryu2030@gmail.com**。
2. 在「网站」里点进**你的域名**（第一步添加的那个）。
3. 左侧点 **「DNS」** → **「记录」**。
4. 点 **「添加记录」**，填：
   - **类型**：`CNAME`
   - **名称**：`htma`（或任意，如 `dashboard`；最终地址就是 `https://htma.你的域名.com`）
   - **目标**：`<第三步的隧道ID>.cfargotunnel.com`  
     例如隧道 ID 是 `abcd1234-5678-90ab-cdef-1234567890ab`，则填：  
     `abcd1234-5678-90ab-cdef-1234567890ab.cfargotunnel.com`
   - **代理状态**：**已代理**（橙色云朵 ✅）
5. 点 **「保存」**。

之后你的固定访问地址就是：**https://htma.你的域名.com**（若名称填的是 `dashboard`，则为 https://dashboard.你的域名.com）。

---

## 第五步：本机写隧道配置文件

在终端执行（把 `zhonglian` 换成你的 Mac 用户名，`<隧道ID>` 换成第三步的 UUID）：

```bash
mkdir -p ~/.cloudflared
```

然后编辑 `~/.cloudflared/config.yml`（没有就新建）：

```bash
nano ~/.cloudflared/config.yml
```

内容写成（注意替换三处：隧道 ID、主机名、凭证路径里的用户名和隧道 ID）：

```yaml
tunnel: htma-dashboard
credentials-file: /Users/zhonglian/.cloudflared/<隧道ID>.json

ingress:
  - hostname: htma.你的域名.com
    service: http://127.0.0.1:5002
  - service: http_status:404
```

- **tunnel**：和第三步创建的隧道名一致，即 `htma-dashboard`。  
- **credentials-file**：`<隧道ID>` 换成第三步的 UUID，`zhonglian` 换成你的用户名。  
- **hostname**：和第四步「名称」对应；若名称是 `htma`、域名是 `example.com`，则写 `htma.example.com`。

保存退出（nano：Ctrl+O 回车，Ctrl+X）。

---

## 第六步：启动看板 + 固定隧道

**终端 1**（先启动看板）：

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag
bash 启动好特卖看板.command
```

等看板起来（能看到 “Serving Flask app” 之类）后。

**终端 2**（再启动隧道）：

```bash
cloudflared tunnel --config ~/.cloudflared/config.yml run htma-dashboard
```

保持这两个终端不关。此时：

- **本机访问**：http://127.0.0.1:5002  
- **外网/同事访问**：**https://htma.你的域名.com**（固定链接，发一次即可长期用）

---

## 一键脚本（完成第四、五步后使用）

配置文件写好、DNS 也加好后，以后可以一条命令同时「释放 5002 + 启动看板 + 启动隧道」：

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag
bash scripts/start_htma_fixed_tunnel.sh
```

脚本会读 `~/.cloudflared/config.yml`，隧道名需为 `htma-dashboard`。

---

## 检查清单（你这边）

- [ ] 已在 Cloudflare 添加一个域名（或已购买并添加）。
- [ ] 本机执行过 `cloudflared tunnel login` 并选择了该域名。
- [ ] 执行过 `cloudflared tunnel create htma-dashboard`，并记下隧道 ID。
- [ ] 在该域名的 DNS 里添加了 CNAME：名称 `htma`（或你自定的）→ `<隧道ID>.cfargotunnel.com`，代理开启。
- [ ] `~/.cloudflared/config.yml` 里 tunnel、credentials-file、hostname 已按上面说明改好。
- [ ] 先启动看板，再执行 `cloudflared tunnel run htma-dashboard`（或用 `start_htma_fixed_tunnel.sh`）。

完成后，把 **https://htma.你的域名.com** 发给同事即可实现上述固定链接功能。
