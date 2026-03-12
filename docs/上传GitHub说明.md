# 好特卖看板 - 上传 GitHub 说明

## 一、上传前检查

1. **敏感信息已排除**（`.gitignore` 已配置）  
   - `.env`、`.env.local`（数据库、飞书、密钥等）  
   - `.tunnel-token`（Cloudflare 隧道 Token）  
   - `logs/`、`*.log`  
   - `downloads/`、`*.xlsx`、`*.xls`  

2. **不要提交**  
   - 数据库密码、飞书 App ID/Secret、OpenClaw Token 等  
   - 若曾误提交过，需用 `git filter-branch` 或 BFG 从历史中移除后重新 push  

3. **建议**  
   - 仓库设为 **Private**（若含业务逻辑）；或 Public 时确保无敏感路径/配置被引用  

---

## 二、首次上传到 GitHub

在项目根目录执行（将 `YOUR_USERNAME`、`YOUR_REPO` 换成你的 GitHub 用户名和仓库名）：

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag

# 1. 确认当前分支（一般为 main 或 master）
git branch

# 2. 若尚未添加远程仓库
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git

# 若已存在 origin 但地址不对，可先删除再添加
# git remote remove origin
# git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git

# 3. 推送（首次推送并设置上游分支）
git push -u origin main
# 若本地默认分支是 master，则：
# git push -u origin master
```

若 GitHub 仓库已存在且为空，页面上会提示：

```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

按提示执行即可。

---

## 三、之后日常更新

```bash
git add .
git status   # 确认没有误加入 .env、.tunnel-token 等
git commit -m "描述本次修改"
git push
```

---

## 四、克隆到新机器后

1. 克隆仓库  
   ```bash
   git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
   cd YOUR_REPO
   ```

2. 复制环境配置（需自行准备，不要从 GitHub 拉取含密码的 .env）  
   ```bash
   cp .env.example .env
   # 编辑 .env，填入 MySQL、飞书、OpenClaw 等配置
   ```

3. 安装依赖与启动  
   ```bash
   npm run htma:setup
   # 桌面启动：双击 启动好特卖看板.command 或 创建桌面快捷方式.command 后再从桌面启动
   ```

---

## 五、可选：用 SSH 推送

若已配置 GitHub SSH 密钥：

```bash
git remote add origin git@github.com:YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```
