# 好特卖运营小程序交付说明

## 一、后端新增与修改

| 文件 | 说明 |
|------|------|
| `htma_dashboard/routes_mobile.py` | `GET /api/mobile/dashboard`（`days`、统一 `code/data/msg`）、`category_large`、`category_mid`、`trend`、`alerts`、`labor_summary`；`@mobile_cached`；`daily_category_stats` 为主 |
| `htma_dashboard/labor_routes.py` | `_labor_analysis_overview` / `_labor_analysis_by_category` 增加可选 `store_id`，供移动端按店汇总 |
| `htma_dashboard/wechat_api.py` | `POST /api/wechat/subscribe`（JWT，写 `t_htma_wechat_subscription`） |
| `htma_dashboard/wechat_subscribe_repo.py` | 订阅表 upsert / 列表 |
| `htma_dashboard/wechat_scheduler.py` | 每日 9:00 任务；无模板 ID 时仅日志；预留 `sendMessage` |
| `htma_dashboard/app.py` | 启动 `start_background_scheduler()` |
| `htma_dashboard/requirements.txt` | `Flask-Caching`、`APScheduler` |
| `htma_dashboard/mobile_json.py` | `mobile_ok` / `mobile_err`（既有） |
| `htma_dashboard/extensions.py` | `mobile_cached`（既有） |
| `scripts/32_wechat_subscription_and_indexes.sql` | 订阅表 DDL；索引说明（按需执行） |

### 数据库

1. 执行 `scripts/32_wechat_subscription_and_indexes.sql` 创建 `t_htma_wechat_subscription`。
2. `daily_category_stats` 建议索引：`(store_id, data_date)`、`(category_large_code, data_date)`、`(data_date)`（若已有可跳过）。

### 环境变量（勿把真实密钥写入仓库）

- `WECHAT_JWT_SECRET` / 微信 `AppID`/`AppSecret`（见 `.env` 与现有 `wechat_*` 配置）
- `WECHAT_SUBSCRIBE_TEMPLATE_ID`：订阅消息模板（未设则定时任务只打日志）
- `HTMA_ALERT_LOW_MARGIN_PCT`（默认 20）、`HTMA_ALERT_LARGE_SHARE_PCT`（默认 5）、`HTMA_ALERT_NEG_SKU_THRESHOLD`（默认 10）
- `HTMA_DISABLE_APSCHEDULER=1`：关闭每日 9:00 任务（本地/单测可用）

### 启动后端

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag/htma_dashboard
../.venv/bin/python3 app.py
# 或 scripts/start_htma.sh；默认 PORT=5002
```

### 测试

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag
HTMA_DISABLE_APSCHEDULER=1 HTMA_UNITTEST_DISABLE_AUTH=1 HTMA_SKIP_MOBILE_JWT=1 \
  .venv/bin/python3 -m unittest tests.test_api_contract -v
```

---

## 二、小程序结构（`miniprogram/`）

- `app.js` / `app.json` / `app.wxss`：主题色（橙+绿）、全局 `baseUrl`、订阅模板 ID 数组
- `utils/request.js`：Bearer token、`code===0` 与旧版 `success` 兼容、401 清 token 并回登录
- `pages/index`：驾驶舱，KPI、TOP5、负毛利、提醒、`days=7/30`
- `pages/categories`：大类列表、中类下钻
- `pages/trend`：折线（简单 canvas）、`metric`+`days`（7/30/90）
- `pages/alerts`：预警列表、订阅消息入口
- `pages/labor`：人力摘要 + `pages/labor/web` 全屏 `web-view` 打开 `labor_analysis.html`
- `pages/profile`：我的、登出
- `pages/profile/login`：`wx.login` → `/api/wechat/login`、getPhoneNumber

**根目录**还保留 `miniprogram_example/` 供接口调试；本交付主目录为 **`miniprogram/`**。

在 `miniprogram/project.config.json` 中把 `appid` 换成真实小程序 **AppID**；本地开发可在开发者工具中勾选「不校验合法域名」；正式环境需为 `htma.greatagain.com.cn` 配 **HTTPS** 与业务域名/白名单。

---

## 三、已知限制

- 微信**订阅消息**需公众平台模板审核，且长驻发送需与 `access_token`、用户一次性订阅态一致；未配置时定时任务**仅打日志**。
- `web-view` 内 H5 人力页仍走看板**飞书/会话**登录，小程序 JWT 通过 URL 片段传递仅作联调思路，**生产需单独适配**。
- `bind_feishu` 在现有接口中可写 `feishu_open_id`；需控制权限，避免被滥用。

---

## 四、API 成功格式

除微信登录/绑定等历史接口外，`/api/mobile/*` 成功统一为：

`{ "code": 0, "data": { ... }, "msg": "" }`

`data` 中聚合类带 `data_source: "daily_category_stats"`（或人力摘要中说明性字段）与 `stats_as_of` 或时间区间说明。
