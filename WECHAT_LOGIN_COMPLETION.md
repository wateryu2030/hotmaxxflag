# 微信小程序独立登录（JWT）— 接入说明

## 新增与修改的文件

| 路径 | 说明 |
|------|------|
| `scripts/28_create_wechat_user_table.sql` | MySQL 表 `t_htma_wechat_user` |
| `htma_dashboard/wechat_config.py` | 环境变量读取 |
| `htma_dashboard/wechat_jwt.py` | JWT 签发与校验 |
| `htma_dashboard/wechat_user_repo.py` | 用户表 CRUD（PyMySQL） |
| `htma_dashboard/wechat_wxa.py` | `jscode2session`、access_token、新版手机号 code |
| `htma_dashboard/wechat_phone_decrypt.py` | 旧版 `encryptedData` + `iv` 解密 |
| `htma_dashboard/wechat_api.py` | Blueprint `/api/wechat/*` |
| `htma_dashboard/wechat_mobile_guard.py` | `/api/mobile/*` 上下文：`g.mobile_scope` / `g.mobile_store_id` |
| `htma_dashboard/routes_mobile.py` | `before_request` 鉴权 + SQL `store_id` 过滤 |
| `htma_dashboard/app.py` | 注册微信蓝图；`_require_auth` 放行 `/api/wechat`、`/api/mobile` |
| `htma_dashboard/requirements.txt` | 增加 `PyJWT` |
| `tests/test_api_contract.py` | 单测设置 `HTMA_SKIP_MOBILE_JWT=1` |
| `.env.example` | 微信相关占位变量 |
| `miniprogram_example/` | 示例：`app.js`、`utils/request.js`、`utils/login.js` |

## 数据库

在目标库执行：

```bash
mysql -u... -p... htma_dashboard < scripts/28_create_wechat_user_table.sql
```

## 环境变量（须手动填写）

- `WECHAT_APPID`、`WECHAT_APPSECRET`（或 `WECHAT_MINI_APPID` / `WECHAT_SECRET`）
- `WECHAT_JWT_SECRET`：签发 token 必填；未配置时 `POST /api/wechat/login` 返回 503
- `WECHAT_MINI_ENABLED=1`：强制 `/api/mobile/*` 必须携带有效 `Authorization: Bearer <jwt>`
- `HTMA_SKIP_MOBILE_JWT=1`：本地/单测跳过 JWT（勿用于生产）
- `HTMA_WECHAT_ADMIN_TOKEN`：请求头 `X-Wechat-Admin-Token` 一致时可调 `GET /api/wechat/admin/users`、`POST /api/wechat/admin/set_role`
- `HTMA_PHONE_FEISHU_OPEN_ID_MAP`（可选）：`13800000000=ou_xxx,...`，绑定手机号后自动写 `feishu_open_id`

## API 摘要

- `POST /api/wechat/login`：`{ "code" }`（`wx.login`）→ `{ token, user }`
- `POST /api/wechat/bind_phone`：Header `Authorization: Bearer ...`；body 新版 `{ "code" }` 或旧版 `{ "encryptedData", "iv" }`
- `POST /api/wechat/bind_feishu`：`{ "feishu_open_id" }`
- `GET /api/wechat/me`
- `GET /api/mobile/dashboard`：需 JWT（若开启 `WECHAT_MINI_ENABLED`）；JWT 中 `store_id` 非空则 SQL 增加 `AND store_id = ?`，为空则全部门店

## 小程序端步骤（简）

1. 将 `miniprogram_example` 中逻辑合并到项目：`baseUrl` 设为看板 HTTPS 根地址，并在微信公众平台配置 **request 合法域名**。
2. 启动或进入需登录页时调用 `wechatLogin()`，成功后 `globalData.token` 已写入。
3. 业务请求经 `utils/request.js` 自动带 `Authorization`。
4. 手机号按钮：`open-type="getPhoneNumber"`，在回调里把 `e.detail.code` POST 到 `/api/wechat/bind_phone`。

## 冒烟（需真实微信 code 与小程序密钥）

```bash
export WECHAT_APPID=... WECHAT_APPSECRET=... WECHAT_JWT_SECRET=随机串
# 可选：export WECHAT_MINI_ENABLED=1
python -m pip install -r htma_dashboard/requirements.txt
cd htma_dashboard && PORT=5002 python app.py
```

```bash
curl -s -X POST http://127.0.0.1:5002/api/wechat/login -H 'Content-Type: application/json' -d '{"code":"从真机wx.login复制"}'
curl -s http://127.0.0.1:5002/api/mobile/dashboard -H "Authorization: Bearer <上一步token>"
```

单测（不连微信，需本机已安装 `pymysql` 等依赖）：

```bash
cd /path/to/hotmaxxflag && python3 -m unittest tests.test_api_contract -v
```

（测试类会设置 `HTMA_UNITTEST_DISABLE_AUTH` 与 `HTMA_SKIP_MOBILE_JWT`。）
