# 人工重装完整版 OpenClaw 方案（Mac/Linux 环境）

当前 npm 版 OpenClaw 不支持 `clawhub run` 命令，无法直接调用百度优选 Skill。需要重新安装**完整版 OpenClaw（源码版）**，该版本包含完整的 CLI 命令和网关功能。

> ⚠️ **重要安全提醒**：OpenClaw 涉及自动化操作和环境配置，如果电脑存有重要的商业/资产或个人隐私信息，**强烈建议弄一台干净的备用设备，或者直接租用一个云端虚拟机（VPS）来运行**，这样既能保护隐私，也能避免环境冲突。

---

## 一、完全卸载现有版本

在执行新安装前，需要彻底清理当前环境：

```bash
# 1. 停止并卸载网关服务
openclaw gateway stop
openclaw gateway uninstall

# 2. 全局卸载 npm 包
npm uninstall -g openclaw @openclaw/cli

# 3. 删除系统级安装（若存在，需 sudo）
sudo rm -f /usr/local/bin/openclaw
sudo rm -rf /usr/local/lib/node_modules/openclaw

# 4. 删除配置文件目录（备份重要数据前请确认）
rm -rf ~/.openclaw
rm -rf ~/.clawdbot

# 5. 清理 npm 缓存
npm cache clean --force

# 6. 确认已卸载
which openclaw   # 应返回 "openclaw not found"
```

**一键脚本（含备份）**：`bash scripts/reinstall_openclaw_full.sh` 会执行上述步骤并备份 `~/.openclaw/skills` 与 `openclaw.json` 到 `/tmp/openclaw_backup_*`。

---

## 二、准备基础环境

OpenClaw 需要 **Node.js 22+** 和 **pnpm** 包管理器。

### 1. 安装/升级 Node.js 到 22+

```bash
# 使用 nvm 安装（推荐）
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.zshrc   # 或 ~/.bashrc
nvm install 22
nvm use 22
node -v   # 确认 ≥22.0.0
```

### 2. 安装 pnpm

若网络不稳定或 `get.pnpm.io` 超时，**优先用 npm 安装**（无需外网下载脚本）：

```bash
# 方式一（推荐，避免 SSL 超时）
npm install -g pnpm

# 方式二：Node 自带的 corepack
corepack enable
corepack prepare pnpm@latest --activate

# 方式三：官方安装脚本（需能访问 get.pnpm.io）
curl -fsSL https://get.pnpm.io/install.sh | sh -
source ~/.zshrc
pnpm --version
```

---

## 三、从源码安装完整版 OpenClaw

```bash
# 1. 克隆官方仓库（可选目录，默认 $HOME/openclaw）
export OPENCLAW_SRC="$HOME/openclaw"
git clone https://github.com/openclaw/openclaw.git "$OPENCLAW_SRC"
cd "$OPENCLAW_SRC"

# 2. 安装依赖
pnpm install

# 3. 构建 UI 界面
pnpm ui:build

# 4. 编译项目核心代码
pnpm build

# 5. 链接到全局命令
pnpm link --global

# 6. 验证安装
openclaw --version   # 应显示版本号
```

若 `pnpm link --global` 后仍 `command not found`，将 pnpm 全局 bin 加入 PATH：

```bash
export PATH="$(pnpm root -g)/../bin:$PATH"
echo 'export PATH="$(pnpm root -g)/../bin:$PATH"' >> ~/.zshrc
```

---

## 四、初始化配置向导

```bash
# 启动配置向导（会自动安装守护进程）
openclaw onboard --install-daemon
```

配置向导的关键选项：

| 提示 | 推荐选择 | 说明 |
|------|----------|------|
| Install daemon? | `yes` | 安装守护进程，后台常驻运行 |
| Onboarding mode | `QuickStart` | 快速开始模式 |
| Model/auth provider | `Custom Provider` 或 `OpenAI` | 根据你的 API Key 选择 |
| API Base URL | `https://api.openai.com/v1` | 或你的代理地址 |
| API Key | 粘贴你的密钥 | 从平台获取 |
| 接口兼容模式 | `OpenAI-compatible` | 通用选项 |
| Model ID | `gpt-4o-mini` | 选择性价比高的模型 |
| Skills | 选 `Yes` | 安装技能系统（必须） |
| Hooks | 推荐安装 | 用于自动化触发 |
| 最后一步 | `Open the Web UI` | 自动打开控制面板 |

> 💡 **API Key 获取**：  
> - OpenAI: https://platform.openai.com/api-keys  
> - Google Gemini: https://aistudio.google.com/app/apikey  

---

## 五、验证完整版功能

### 1. 检查关键命令

```bash
# 验证 clawhub run 是否存在
clawhub run --help
# 应显示 run 命令的使用说明，而非 "unknown command"
```

### 2. 安装百度电商 Skill

```bash
# 搜索可用 Skill
clawhub search "baidu"

# 安装百度优选 Skill（使用正确的 slug）
clawhub install baidu-preferred

# 若上述 slug 不对，可尝试：
clawhub install baidu-ecommerce-skill
```

### 3. 测试 Skill 调用

```bash
# 测试直接调用
clawhub run baidu-preferred --query "洽洽坚果 价格"

# 预期输出：返回多平台比价数据
```

---

## 六、配置网关暴露比价工具（可选）

若需 HTTP 接口调用比价，可修改网关配置（具体键名以当前版本为准）：

```bash
# 编辑配置（可能是 openclaw.json 或 config.yaml，视版本而定）
# 在 gateway 段中确保 skill 工具可被 HTTP 调用
openclaw gateway restart
```

---

## 七、运行自检脚本验证

```bash
cd /Volumes/ragflow/hotmaxx/hotmaxxflag   # 或你的项目根目录
bash scripts/run_selfserve_price_compare_debug.sh

# 预期：步骤1～4 通过或至少 2、3 通过（call_baidu_skill / item_fetcher）
```

---

## 八、常见问题处理

### Q0: openclaw 报错 `SyntaxError: Unexpected reserved word`（openclaw.mjs 的 import）

说明当前 **Node.js 版本过旧**（OpenClaw 需 Node 22+）。系统自带的 `node` 可能是 v10 等，无法运行 ES modules。

**处理：升级 Node 到 22+ 并让 openclaw 使用新版本**

```bash
# 安装 nvm（若尚未安装）
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.zshrc

# 安装并启用 Node 22（若 nvm 提示 npmrc 与 prefix 冲突，先执行下一行）
nvm install 22
nvm use --delete-prefix v22.22.1 --silent   # 仅当 nvm 提示 incompatible 时执行，清除 prefix
nvm use 22
node -v   # 必须显示 v22.x.x，若仍是 v4/v10 说明未切换成功，见下方

# 在 ~/openclaw 下用新 Node 重新安装并链接（务必先确认 node -v 为 22）
cd ~/openclaw
pnpm install
pnpm run build 2>/dev/null || pnpm build
pnpm link --global

# 再执行
openclaw onboard --install-daemon
```

**若 `nvm use 22` 后 `node -v` 已为 v22，但 `openclaw onboard` 仍报 `SyntaxError: Unexpected reserved word`**：说明实际执行 `openclaw.mjs` 的仍是系统旧 Node。**不要用 `openclaw` 命令**，改用当前 shell 的 node 直接运行入口：

```bash
source ~/.nvm/nvm.sh
nvm use 22
node -v   # 必须为 v22.x.x

# 直接用 node 运行（不依赖 PATH 里的 openclaw）
node "$HOME/openclaw/openclaw.mjs" onboard --install-daemon
```

若希望以后命令行打 `openclaw` 也走 Node 22：先确认没有旧版占用名称，再让 pnpm 的 bin 在 PATH 最前。

```bash
# 若有旧版，先删掉，避免优先被调用
sudo rm -f /usr/local/bin/openclaw

# 把 nvm 的 node 放在 PATH 最前（已写入 .zshrc 的可跳过）
export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH"

# pnpm link 后 openclaw 通常在 PNPM_HOME 或 pnpm 全局 bin，需在 PATH 中
export PNPM_HOME="$HOME/Library/pnpm"
export PATH="$PNPM_HOME:$PATH"
# 然后新开终端执行 nvm use 22，再试 openclaw
```

**推荐**：以后需要跑配置/网关时，直接用 `node "$HOME/openclaw/openclaw.mjs" <子命令>`，例如：

```bash
node "$HOME/openclaw/openclaw.mjs" onboard --install-daemon
node "$HOME/openclaw/openclaw.mjs" gateway start
```

**enable_baidu_skill_gateway.sh** 在**看板项目目录**下，需在项目根执行：`cd /Volumes/ragflow/hotmaxx/hotmaxxflag && bash scripts/enable_baidu_skill_gateway.sh`。

以后打开新终端若 `openclaw` 又报同样错误，先执行 `nvm use 22` 或把 `nvm use 22` 写入 `~/.zshrc`。

### Q1: `pnpm link --global` 后仍 command not found

```bash
export PATH="$(pnpm root -g)/../bin:$PATH"
echo 'export PATH="$(pnpm root -g)/../bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Q2: 网关启动失败

```bash
openclaw logs follow
lsof -i :18789
kill -9 <PID>   # 若端口被占用
openclaw gateway restart
```

### Q3: npm install -g openclaw 报 EEXIST / EACCES permission denied（缓存冲突或权限）

先清理缓存并修复 npm 目录归属，再重试：

```bash
npm cache clean --force
sudo chown -R "$(whoami)" ~/.npm
npm install -g openclaw@latest
```

若仍报权限错误，可临时用：`sudo npm install -g openclaw@latest`（不推荐长期用 root 装全局包）。

### Q4: git clone 报错 Empty reply from server / 无法访问 GitHub

多为网络或防火墙限制，可任选其一：

- **换 SSH 克隆**（需已配置 GitHub SSH key）：  
  `git clone --depth 1 git@github.com:openclaw/openclaw.git ~/openclaw`
- **手动下载**：浏览器打开 https://github.com/openclaw/openclaw ，点 **Code → Download ZIP**，解压后把文件夹改名为 `openclaw` 并放到 `~/openclaw`（或你设的 `OPENCLAW_SRC`），再重新执行脚本从「三」之后步骤，或手动执行 `cd ~/openclaw && pnpm install && pnpm ui:build && pnpm build && pnpm link --global`。
- 使用代理或更换网络后再试 HTTPS clone。

### Q5: 安装 Skill 时提示 slug not found

```bash
clawhub search "ecommerce"
clawhub search "price"
clawhub search "shopping"
# 根据搜索结果使用正确的 slug 安装
```

---

## 九、完成后的验证清单

- [ ] `openclaw --version` 显示版本号  
- [ ] `clawhub run --help` 有输出  
- [ ] 百度电商 Skill 安装成功  
- [ ] `clawhub run baidu-preferred --query "洽洽坚果"` 返回比价数据  
- [ ] 自检脚本通过（或步骤 2、3 通过）  
- [ ] 浏览器访问 `http://127.0.0.1:18789` 能打开控制面板  

---

## 九.1、京东/淘宝分平台比价（完整版 + 百度 Skill）

安装**完整版 OpenClaw** 并安装 **百度 Skill**（如 `baidu-preferred`）后，`clawhub run` 会返回多平台比价数据（京东、淘宝、拼多多、唯品会等）。看板与 runner 已支持解析并展示：

- **runner**（`scripts/openclaw_baidu_tools_runner.py`）：解析 Skill 标准输出中的 `{"京东": {"price": 12.5}, "淘宝": {"price": 11.0}, ...}`，或兼容 `{"京东": 12.5, "淘宝": 11.0}`。
- **看板**（`htma_dashboard/baidu_skill_compare.py` 的 `baidu_skill_item_fetcher`）：将返回的 `data` 映射为 `jd_min_price`、`taobao_min_price`、`platform` 等字段，货盘比价表格中会分别显示「京东最低价」「淘宝最低价」。

**一键完成「完整版 + 百度 Skill」环境**（在项目根目录执行）：

```bash
bash scripts/setup_full_openclaw_baidu_skill.sh
```

脚本会：若未安装完整版则先执行 `reinstall_openclaw_full.sh`；若已安装则执行 `enable_baidu_skill_gateway.sh --install-skill` 并运行诊断。首次安装后需**手动执行一次**：

```bash
openclaw onboard --install-daemon
```

然后按脚本提示执行 `enable_baidu_skill_gateway.sh --install-skill` 与 `diagnose_baidu_skill.sh`。诊断中【5】显示 `source=baidu_skill` 且返回多平台时，看板即可展示京东/淘宝分平台比价。

---

## 十、相关脚本

- **一键完整版 + 百度 Skill（京东/淘宝分平台）**：`bash scripts/setup_full_openclaw_baidu_skill.sh`  
- **一键重装（含卸载与源码安装）**：`bash scripts/reinstall_openclaw_full.sh`  
- **启用网关并安装百度 Skill**：`bash scripts/enable_baidu_skill_gateway.sh [--install-skill]`  
- **比价自检**：`bash scripts/run_selfserve_price_compare_debug.sh`  
- **百度 Skill 环境说明**：[百度Skill比价环境说明.md](./百度Skill比价环境说明.md)
