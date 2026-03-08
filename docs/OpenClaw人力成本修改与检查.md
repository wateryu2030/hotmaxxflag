# OpenClaw 自动完成人力成本修改及检查

让 OpenClaw 自动执行：部署看板使人力成本 Tab 前端修改生效，并校验接口与数据状态。

## 一键：自动检查并修改完善

在项目根目录执行（先检查 → 部署/重启看板 → 再检查，确保本地 [2][3] 通过）：

```bash
npm run htma:openclaw-check
# 或带生产 URL
bash scripts/openclaw_auto_check_and_fix.sh https://htma.greatagain.com.cn
```

## 一、在 OpenClaw 里怎么说

在 OpenClaw 对话中说（任选其一）：

- **「让 openclaw 自动完成人力成本修改及检查」**
- **「人力成本修改及检查」**
- **「执行人力成本部署并验证」**

OpenClaw 应执行（任选其一）：

```bash
cd <项目根目录> && bash scripts/openclaw_labor_modify_and_check.sh
# 或
npm run htma:labor:check
```

若需同时验证生产环境，可说「并验证生产」或传入生产 base_url：

```bash
bash scripts/openclaw_labor_modify_and_check.sh https://htma.greatagain.com.cn
```

生产 URL 也可由项目 `.env` 中的 `HTMA_PUBLIC_URL` 提供，脚本会优先使用命令行参数。

## 二、脚本做了什么

1. **说明**：人力成本 Tab 的前端修改（401 提示、切 Tab 滚动、无数据说明、credentials 等）已合入 `htma_dashboard/static/index.html`，需重启看板后生效。
2. **部署并验证**：调用 `scripts/deploy_and_verify_labor.sh`：
   - 释放 5002 端口并结束旧看板进程
   - 启动看板（加载 .env、建表、Flask）
   - 校验本地 `/api/labor_cost`（GET/POST）非 405，并校验 `/api/labor_cost_status`
   - 若传入生产 base_url（或 `HTMA_PUBLIC_URL`），再校验生产环境接口
3. **收尾**：打印看板地址与「人力成本」Tab 使用说明（报表月份留空查看最近月份）。

## 三、可选：OpenClaw Skill 配置

若希望 OpenClaw 在听到「人力成本修改及检查」时自动执行本脚本，可在 OpenClaw 的 skills 中增加触发词与命令，或在本项目 `skills/htma-openclaw-autonomous/SKILL.md` 的典型流程中增加一条：

- **触发词**：人力成本修改及检查、openclaw 自动完成人力成本修改及检查
- **动作**：在项目根目录执行 `bash scripts/openclaw_labor_modify_and_check.sh`，可选传入生产 base_url 或依赖 `HTMA_PUBLIC_URL`。

## 四、手动执行

不在 OpenClaw 中时，也可在项目根目录手动执行：

```bash
npm run htma:labor:check
# 或
bash scripts/openclaw_labor_modify_and_check.sh
# 带生产校验
bash scripts/openclaw_labor_modify_and_check.sh https://htma.greatagain.com.cn
```

## 五、人力成本 + 飞书验证 自动检查（前端看不到数据时）

若前端依然看不到人力成本数据，可重点检查飞书登录与数据状态：

```bash
python scripts/openclaw_labor_feishu_check.py
# 或带生产 URL
python scripts/openclaw_labor_feishu_check.py https://htma.greatagain.com.cn
# 或
npm run htma:labor:feishu-check
```

脚本会检查：.env 飞书配置、`/api/auth/feishu_url`、`/api/labor_cost` / `labor_cost_status` 鉴权、数据库明细/汇总、飞书 redirect_uri 与 Cookie 排查清单。若**明细表无数据、仅汇总表有**，登录后类目总体会有数但组长/组员明细表为空，需重新导入人力成本 Excel 填充明细表。

**重新导入后依然不对时**：1) 导入接口已改为「导入后自动刷新汇总表」，看板人力成本 Tab 会显示「最近月份」；2) 打开 Tab 时报表月份留空会自动拉最近月份并回填到输入框；3) 若仍无数据，请运行 `npm run htma:labor:feishu-check` 检查飞书与接口，并确认当前访问的看板与导入时是同一环境（同机或生产）。

## 六、与人力成本 Tab 的对应关系

- 修改已合入：`htma_dashboard/static/index.html`（401 提示、credentials、滚动、无数据说明、结构异常兜底等）。
- 本脚本不再次修改代码，只做**部署 + 接口与数据状态检查**，确保线上/本地看板使用最新前端并可用。
