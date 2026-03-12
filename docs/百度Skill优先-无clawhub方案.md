# 百度 Skill 优先方案（clawhub 已无 baidu-preferred）

## 问题与结论

- **现象**：`clawhub install baidu-preferred` 报错 **Skill not found**，clawhub 公共源里已没有百度电商比价 skill。
- **需求**：比价要**优先走百度 Skill**（多平台比价），你在手机上测试百度 skill 是可用的。
- **结论**：不再依赖「本机 clawhub 安装」，改为**配置「百度 Skill 专用网关」**，指向已能跑百度 Skill 的环境（如手机端 OpenClaw、或曾安装过该 skill 的网关）。

## 推荐做法：配置百度 Skill 专用网关

1. **确定「已可用的百度 Skill 网关」**
   - 你在**手机**上能用的百度 skill，通常对应：
     - 手机本机 OpenClaw 的网关（若手机暴露了端口/有内网 IP，可填 `http://手机IP:18789`），或
     - 与手机同一账号的**云端/远程 OpenClaw 网关**（推荐：该网关上已安装百度 skill，手机和看板都连它）。
   - 若你用的是**本机另一台电脑**上的 OpenClaw 且上面有百度 skill，填那台电脑的网关 URL 即可。

2. **在项目里配置**
   - 复制 `.env.example` 为 `.env`（若已有 `.env` 直接编辑）。
   - 增加或修改：
     ```bash
     # 百度 Skill 专用网关（优先用百度电商比价）
     OPENCLAW_BAIDU_SKILL_GATEWAY_URL=https://你的网关地址
     OPENCLAW_BAIDU_SKILL_GATEWAY_TOKEN=该网关的 Bearer token
     ```
   - `OPENCLAW_BAIDU_SKILL_GATEWAY_TOKEN` 不填时，会使用本机的 `OPENCLAW_GATEWAY_TOKEN`（若与专用网关是同一套 token）。
   - 网关 token 获取方式：该网关对应的 `~/.openclaw/openclaw.json` 里 `gateway.auth.token`，或控制台带 token 的 URL 中 `#token=xxx`。

3. **行为说明**
   - 配置后，**看板比价**与 **runner**（`scripts/openclaw_baidu_tools_runner.py`）都会：
     - **先**请求 `OPENCLAW_BAIDU_SKILL_GATEWAY_URL` 的 `POST /tools/invoke`（get_price_comparison / search_products），
     - 成功则直接使用，视为 **百度 Skill** 结果（多平台），
     - 失败再走本机网关 → clawhub run → 百度优选 MCP。
   - 因此只要该 URL 对应的是「已装百度 skill、你在手机能用的那个网关」，本机就**优先用百度 Skill**，且**不需要**在本机执行 `clawhub install baidu-preferred`。

## 如何拿到「手机/远程网关」的 URL 和 token

- **同一局域网内的手机/电脑**  
  若 OpenClaw 网关跑在手机或另一台电脑上，且你知道其 IP 和端口（例如 18789）：
  - URL：`http://<手机或该电脑的 IP>:18789`
  - Token：在该设备上查看 `~/.openclaw/openclaw.json` 的 `gateway.auth.token`（手机端若没有文件系统，从该端 OpenClaw 控制台「带 token 的链接」里取 `#token=` 后的值）。

- **云端/远程 OpenClaw**  
  若手机和电脑都连的是同一个云端网关：
  - URL：该网关的公网或内网地址（如 `https://openclaw.example.com`），
  - Token：该网关的 `gateway.auth.token` 或控制台提供的 token。

## 验证

- 配置并重启看板后，做一次比价；或在本机执行：
  ```bash
  python scripts/openclaw_baidu_tools_runner.py get_price_comparison '洽洽坚果'
  ```
  若返回的 JSON 里 `"source": "baidu_skill"`，且 `data` 中含京东/淘宝等多平台，说明已优先走百度 Skill 专用网关。

- 诊断脚本会检测是否配置了 `OPENCLAW_BAIDU_SKILL_GATEWAY_URL`，并提示「已配置百度 Skill 专用网关」：
  ```bash
  bash scripts/diagnose_baidu_skill.sh
  ```

## 小结

| 之前 | 现在 |
|------|------|
| 依赖 `clawhub install baidu-preferred`，但 clawhub 上已无该 skill，问题反复出现 | 不再依赖 clawhub 安装；配置「百度 Skill 专用网关」指向已可用的环境 |
| 本机只能走 MCP 回退 | 本机优先请求专用网关，等同于优先用百度 Skill（与手机一致） |

**以后遇到「clawhub 找不到百度 skill」时，以本文为准：配置 `OPENCLAW_BAIDU_SKILL_GATEWAY_URL` 即可优先使用百度 Skill，无需再尝试 clawhub install。**
