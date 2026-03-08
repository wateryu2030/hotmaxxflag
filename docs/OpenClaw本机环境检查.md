# OpenClaw 本机环境检查与配置

用于确认本机环境是否满足 **OpenClaw 自主完成约定设计开发**（浏览器自动化、终端执行、技能加载等）。

## 一键检查

在项目根目录执行：

```bash
bash scripts/check_openclaw_env.sh
```

脚本会检查并输出：

- **基础命令**：Node、npm、Python、OpenClaw 是否已安装
- **项目依赖**：`.venv`、Playwright、Chromium 浏览器
- **OpenClaw 配置**：`~/.openclaw/openclaw.json` 中 browser、tools.allow、exec.ask、skills 路径
- **项目 .env**：MYSQL、API/飞书等
- **可选**：`.tunnel-token`、jq

若存在未通过项，会标记为 `[--]` 并给出修复建议。

## 完善配置（首次或换机器）

1. **合并自主编程配置**（含 skills 路径、exec 不询问、browser 开启）：

   ```bash
   bash scripts/merge_openclaw_autonomous.sh
   ```

   会将 `config/openclaw-htma-autonomous.json` 合并到 `~/.openclaw/openclaw.json`，并把 `__PROJECT_ROOT__` 替换为当前项目根目录，使 `skills.load.extraDirs` 指向本项目的 `skills/`。

2. **安装 Playwright 浏览器**（用于 KPI 自定义日期等自动化）：

   ```bash
   npx playwright install chromium
   ```

3. **重启 OpenClaw**，使新配置与 skills 生效。

## 环境就绪后

在 OpenClaw 中可说：

- **「利用 openclaw 自主完成编程工作」** — 按 Skill 自主使用 browser、exec、read/write/edit 完成任务
- **「使用 openclaw 自动检查并修改完善」** — 执行 `npm run htma:openclaw-check`（人力成本+看板部署+KPI 日期检查）
- **「让 openclaw 自动完成人力成本修改及检查」** — 执行人力成本相关部署与校验

## 可选配置

| 项目 | 说明 |
|------|------|
| `.tunnel-token` | Cloudflare 隧道 Token，用于外网访问 https://htma.greatagain.com.cn |
| `jq` | 无 jq 时 merge 脚本无法自动合并，需手动编辑 `openclaw.json` |
