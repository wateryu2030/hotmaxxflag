# 百度 Skill 执行清单 — 执行结果

按你整理的「百度Skill实际使用步骤」已执行可自动化部分，结果如下。

---

## 一、前期准备 ✅

| 步骤 | 命令 | 结果 |
|------|------|------|
| 1 | `openclaw --version` | **CLI 不在 PATH**；通过 `node /Users/zhonglian/openclaw/dist/index.js --version` 得到 **OpenClaw 2026.3.9** |
| 2 | `openclaw models auth list` | 本机 CLI 子命令结构不同（auth 参数报错），未继续查；网关侧模型鉴权由 `~/.openclaw/openclaw.json` 与 LaunchAgent 环境变量配置 |
| 3 | 网关状态 | **网关正常**：`http://127.0.0.1:18789` 返回 200，launchd 显示 `ai.openclaw.gateway` 在运行 |

---

## 二、安装百度优选电商 Skill ⚠️

| 步骤 | 命令 | 结果 |
|------|------|------|
| 4 | `clawhub search baidu` | 成功，列出 baidu-search、baidu-baike-data 等，**未出现** `baidu-ecommerce-skill` |
| 4 | `clawhub install baidu-ecommerce-skill` | **失败**：`Rate limit exceeded`（ClawHub 限流） |
| 5 | `openclaw skill install baidu-ecommerce` | 当前 OpenClaw 无 `skill install` 子命令，仅有 `openclaw skills`（列出/查看） |

**说明**：本机已存在 **baidu-shopping-comparison**（OpenClaw 内置/捆绑），`openclaw skills` 中状态为 **✓ ready**，描述为「百度电商比价技能，用于搜索百度电商平台商品、比较不同商家价格…」。

---

## 三、验证安装与测试 ✅

| 步骤 | 结果 |
|------|------|
| 6 | `openclaw skills` 已执行，**baidu-shopping-comparison** 为 ready |
| 7 | 网关由 launchd 管理，当前已在运行，未做 stop/start（若需重启：`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist` 再 `launchctl bootstrap ...`） |
| 8 | Chat 地址与 token 见下节「第 9 步：在 Chat 中测试」 |

---

## 四、第 9 步：在 Chat 中测试（需你本地操作）

请在浏览器中打开：

**Chat 地址（带 token）：**  
**http://127.0.0.1:18789/#token=0f93518130967e91396cf9000c57418e0cd3dac36791c5e8**

在对话框中**依次**输入下面任意一条测试：

1. **推荐先测：**  
   `请用百度电商比价Skill查询伊利宫酪奶皮子酸奶138g的价格`

2. 或：  
   `帮我对比一下 iPhone 15 在各平台的价格`

3. 或：  
   `用百度Skill对比戴森吸尘器V12在京东、淘宝、拼多多的价格`

4. 或（数码类，官方覆盖）：  
   `小米电视ES Pro 65英寸价格对比`

**请把 Chat 的返回结果（或截图/原文）发给我**，我可以帮你判断：  
- 是否已走百度电商比价能力；  
- 食品类（伊利酸奶）当前是否被覆盖。

---

## 五、故障排查命令执行结果

| 步骤 | 命令 | 结果 |
|------|------|------|
| 10 | `openclaw skill logs baidu-ecommerce` | 未执行（本机无 `skill logs`，且 Skill 名为 baidu-shopping-comparison） |
| 11 | `curl http://127.0.0.1:18789/tools/list` | 返回 **Control UI 的 HTML 页面**，非 JSON 工具列表；网关的 **POST /tools/invoke** 已确认可用（get_price_comparison、search_products 由本仓库插件暴露） |
| 12 | 百度 Skill 搜索工具是否暴露 | 网关已通过 **baidu-price-tools 插件** 暴露 `get_price_comparison` 与 `search_products`；Chat 若调用这些 tool，会经网关执行 |

---

## 六、重要说明（与你清单一致）

1. **Skill 与 API Token**：百度 Skill（如 baidu-shopping-comparison）是 OpenClaw 生态插件；`BAIDU_YOUXUAN_TOKEN` 是百度优选开放平台 API 密钥，两套体系。当前比价数据来源为：网关插件 → 项目内 OneBound/聚合/百度 API 等；若接入百度优选开放平台 API，需在代码中单独对接。
2. **品类覆盖**：官方覆盖数码、家电、家居等；食品饮料（如伊利酸奶）可能不在首批，查不到属正常，可继续用万邦/聚合等保底。
3. **多数据源**：看板侧已实现「优先百度 Skill（网关）→ 万邦/聚合」的优先级与回退逻辑。

---

## 七、下一步请你做的

1. 用上面的 **Chat 地址（带 token）** 打开页面。  
2. 在 Chat 里输入第 9 步中的任一句测试语。  
3. 把 **Chat 的完整返回结果**（或截图）发给我，我根据结果判断食品类是否已覆盖、并给出后续建议。
