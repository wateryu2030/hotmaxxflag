#!/bin/bash
# 人工重装完整版 OpenClaw（Mac/Linux）- 支持 clawhub run 与百度 Skill 比价
# 用法：bash scripts/reinstall_openclaw_full.sh
# 需本机可访问 GitHub、能执行 sudo（卸载旧版时输入密码）
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="/tmp/openclaw_backup_$(date +%Y%m%d)"
OPENCLAW_SRC="${OPENCLAW_SRC:-$HOME/openclaw}"

echo "======== 一、完全卸载现有版本 =========="
openclaw gateway stop 2>/dev/null || true
openclaw gateway uninstall 2>/dev/null || true
npm uninstall -g openclaw @openclaw/cli 2>/dev/null || true

mkdir -p "$BACKUP_DIR"
[ -d ~/.openclaw/skills ] && cp -R ~/.openclaw/skills "$BACKUP_DIR/" 2>/dev/null || true
[ -f ~/.openclaw/openclaw.json ] && cp ~/.openclaw/openclaw.json "$BACKUP_DIR/" 2>/dev/null || true
echo "配置已备份到 ${BACKUP_DIR:-/tmp/openclaw_backup}（如有）"

rm -rf ~/.openclaw ~/.clawdbot 2>/dev/null || true
npm cache clean --force 2>/dev/null || true

echo "删除系统级 openclaw（需输入 sudo 密码）："
set +e
sudo rm -f /usr/local/bin/openclaw 2>/dev/null
sudo rm -rf /usr/local/lib/node_modules/openclaw 2>/dev/null
set -e
if command -v openclaw &>/dev/null || [ -f /usr/local/bin/openclaw ]; then
  echo "警告：openclaw 仍在 PATH 或 /usr/local/bin，请手动执行："
  echo "  sudo rm -f /usr/local/bin/openclaw"
  echo "  sudo rm -rf /usr/local/lib/node_modules/openclaw"
else
  echo "已卸载: openclaw not found"
fi

echo ""
echo "======== 二、准备基础环境 =========="
# 确保 npm 全局 bin 在 PATH 中（pnpm 安装后能直接找到）
NPM_BIN="$(npm root -g 2>/dev/null)/../bin"
[ -d "$NPM_BIN" ] && export PATH="$NPM_BIN:$PATH"

if ! command -v node &>/dev/null; then
  echo "请先安装 Node.js 22+："
  echo "  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash"
  echo "  source ~/.zshrc && nvm install 22 && nvm use 22"
  exit 1
fi
NODE_VER=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_VER" -lt 22 ] 2>/dev/null; then
  echo "需要 Node.js 22+，当前: $(node -v)"
  exit 1
fi
echo "Node: $(node -v) OK"

if ! command -v pnpm &>/dev/null; then
  echo "安装 pnpm（使用 npm 全局安装，避免外网超时）..."
  npm install -g pnpm 2>/dev/null || true
  # 再次把 npm 全局 bin 加入 PATH（刚装的 pnpm 在这里）
  NPM_BIN="$(npm root -g 2>/dev/null)/../bin"
  [ -d "$NPM_BIN" ] && export PATH="$NPM_BIN:$PATH"
fi
if ! command -v pnpm &>/dev/null; then
  echo "尝试 corepack 或 get.pnpm.io（若超时请手动: npm install -g pnpm 后重跑本脚本）..."
  if command -v corepack &>/dev/null; then
    corepack prepare pnpm@latest --activate 2>/dev/null || true
    NPM_BIN="$(npm root -g 2>/dev/null)/../bin"
    [ -d "$NPM_BIN" ] && export PATH="$NPM_BIN:$PATH"
  fi
  if ! command -v pnpm &>/dev/null; then
    curl -fsSL --connect-timeout 15 https://get.pnpm.io/install.sh 2>/dev/null | sh - 2>/dev/null || true
    export PNPM_HOME="${PNPM_HOME:-$HOME/Library/pnpm}"
    export PATH="$PNPM_HOME:$PATH"
    [ -f ~/.zshrc ] && grep -q PNPM_HOME ~/.zshrc || echo 'export PNPM_HOME="$HOME/Library/pnpm"' >> ~/.zshrc
    [ -f ~/.zshrc ] && grep -q 'PATH.*PNPM_HOME' ~/.zshrc || echo 'export PATH="$PNPM_HOME:$PATH"' >> ~/.zshrc
  fi
fi
PNPM_VER=$(pnpm --version 2>/dev/null || npx pnpm --version 2>/dev/null)
if [ -n "$PNPM_VER" ]; then
  echo "pnpm: $PNPM_VER OK"
else
  echo "错误：未找到 pnpm。请执行: npm install -g pnpm"
  echo "再执行: export PATH=\"\$(npm root -g)/../bin:\$PATH\""
  echo "然后重新运行本脚本。"
  exit 1
fi

echo ""
echo "======== 三、从源码安装完整版 OpenClaw =========="
if [ ! -d "$OPENCLAW_SRC" ]; then
  echo "克隆仓库到 $OPENCLAW_SRC ..."
  if ! git clone --depth 1 https://github.com/openclaw/openclaw.git "$OPENCLAW_SRC" 2>/dev/null; then
    echo "HTTPS 克隆失败，尝试 SSH..."
    if ! git clone --depth 1 git@github.com:openclaw/openclaw.git "$OPENCLAW_SRC" 2>/dev/null; then
      echo "SSH 克隆失败，尝试下载 ZIP..."
      TMP_ZIP="/tmp/openclaw-main.zip"
      TMP_DIR="/tmp/openclaw-extract"
      rm -rf "$TMP_DIR" "$OPENCLAW_SRC"
      mkdir -p "$TMP_DIR"
      if curl -fsSL --connect-timeout 30 -o "$TMP_ZIP" "https://github.com/openclaw/openclaw/archive/refs/heads/main.zip" 2>/dev/null; then
        mkdir -p "$(dirname "$OPENCLAW_SRC")"
        (cd "$TMP_DIR" && unzip -q "$TMP_ZIP" && mv openclaw-main "$OPENCLAW_SRC")
        rm -f "$TMP_ZIP"
        rm -rf "$TMP_DIR"
      fi
      if [ ! -d "$OPENCLAW_SRC" ] || [ ! -f "$OPENCLAW_SRC/package.json" ]; then
        OPENCLAW_DIR="${OPENCLAW_SRC:-$HOME/openclaw}"
        echo "克隆/下载均失败。请任选其一："
        echo "  1) 浏览器打开 https://github.com/openclaw/openclaw 点 Code -> Download ZIP，解压后把文件夹改名为 openclaw 放到："
        echo "     $OPENCLAW_DIR"
        echo "  2) 或从能访问 GitHub 的电脑下载 ZIP，传到本机后解压、改名为 openclaw 并放到上述路径，再执行："
        echo "     bash scripts/reinstall_openclaw_full.sh"
        exit 1
      fi
      echo "已通过 ZIP 解压到 $OPENCLAW_SRC"
    fi
  fi
fi

# 确保 pnpm 全局 bin 目录存在（避免 link 时报 ERR_PNPM_NO_GLOBAL_BIN_DIR）
if pnpm setup &>/dev/null; then
  eval "$(pnpm env 2>/dev/null)" 2>/dev/null || true
  export PNPM_HOME="${PNPM_HOME:-$HOME/Library/pnpm}"
  export PATH="$PNPM_HOME:$PATH"
fi

cd "$OPENCLAW_SRC"
echo "安装依赖..."
pnpm install
echo "构建 UI..."
pnpm run ui:build 2>/dev/null || pnpm ui:build 2>/dev/null || true
echo "构建核心..."
pnpm run build 2>/dev/null || pnpm build
echo "链接全局命令..."
pnpm link --global 2>/dev/null || (pnpm setup && eval "$(pnpm env)" && pnpm link --global)

echo ""
echo "若 link 后仍 command not found，请把 pnpm 全局 bin 加入 PATH："
echo "  export PATH=\"\$(pnpm root -g)/../bin:\$PATH\""
echo "  或写入 ~/.zshrc"
echo ""
echo "======== 四、验证安装 =========="
openclaw --version 2>/dev/null && echo "openclaw OK" || echo "请在新终端执行: openclaw --version"
clawhub run --help 2>/dev/null | head -3 && echo "clawhub run OK" || echo "请在新终端执行: clawhub run --help"

echo ""
echo "======== 五、初始化配置（需在本机交互完成） =========="
echo "请执行："
echo "  openclaw onboard --install-daemon"
echo "按向导选择 QuickStart、配置 API Key、安装 Skills。"
echo ""
echo "======== 六、安装百度 Skill 并测试 =========="
echo "  clawhub search baidu"
echo "  clawhub install baidu-preferred   # 或 baidu-ecommerce-skill"
echo "  clawhub run baidu-preferred --query '洽洽坚果 价格'"
echo ""
echo "======== 七、运行自检 =========="
echo "  cd $PROJECT_ROOT"
echo "  bash scripts/run_selfserve_price_compare_debug.sh"
echo ""
echo "完成。备份在 $BACKUP_DIR"
