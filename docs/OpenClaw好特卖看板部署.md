# 使用 OpenClaw 自动部署好特卖运营看板

## 一、准备工作

1. **安装 OpenClaw**（若尚未安装）：
   ```bash
   npm install -g openclaw@latest
   openclaw onboard --install-daemon
   ```

2. **确保 MySQL 已启动**，数据源 `htma_dashboard` 有数据。

## 二、告诉 OpenClaw 执行部署

### 方式一：独立版（推荐，端口 5002）

不依赖 JimuReport，直接启动 Flask 看板，含 AI 分析建议、品类/商品明细、周几对比等：

```
cd /Users/document/好特卖超级仓/数据分析 && bash scripts/openclaw_deploy_htma_dashboard.sh --standalone --open
```

### 方式二：JimuReport 版（端口 8085）

```
cd /Users/document/好特卖超级仓/数据分析 && bash scripts/openclaw_deploy_htma_dashboard.sh --open
```

`--open` 会在部署完成后自动打开浏览器到看板页面。

## 三、若 OpenClaw 未安装，可手动执行

```bash
cd /Users/document/好特卖超级仓/数据分析
bash scripts/openclaw_deploy_htma_dashboard.sh --open
```

或使用 npm script（已在 package.json 中配置）：

```bash
npm run jr:deploy
```

## 四、脚本执行内容

| 步骤 | 操作 |
|------|------|
| 1 | 执行 `add_htma_dashboard_plan_a.sql`（数据源、数据集、看板） |
| 2 | 执行 `fix_htma_dashboard_jmsheet.sql`（修复 jmsheet TypeError） |
| 3 | 编译 JimuReport（含 show 接口兜底） |
| 4 | 验证 show API 是否正常 |
| 5 | 可选：打开浏览器到看板 |

## 五、若 show API 仍报错

需**重启 JimuReport** 使 Controller 生效：

```bash
# 在运行 JimuReport 的终端中 Ctrl+C 停止，再执行：
cd /Users/document/好特卖超级仓/数据分析/JimuReport/jimureport-example
mvn spring-boot:run
```

重启后访问：http://127.0.0.1:8085/jmreport/view/htma_dash_shenyang_001

## 六、OpenClaw Skill（可选）

若希望 OpenClaw 通过「技能」一键执行，可将以下内容加入 OpenClaw 的 skills 配置：

```yaml
# 好特卖看板部署
- name: htma-dashboard-deploy
  description: 部署好特卖沈阳超级仓运营看板
  trigger: |
    当用户说「部署好特卖看板」「好特卖看板部署」「deploy htma dashboard」时触发
  action: |
    cd /Users/document/好特卖超级仓/数据分析 && bash scripts/openclaw_deploy_htma_dashboard.sh --open
```

具体配置方式取决于 OpenClaw 的 skills 格式，请参考 [OpenClaw Skills 文档](https://openclaw.im/tools/skills)。
