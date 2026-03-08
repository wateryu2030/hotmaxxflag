#!/usr/bin/env bash
# OpenClaw 自主完成约定设计开发所需的本机环境检查
# 执行: bash scripts/check_openclaw_env.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

OK=0
MISS=0

check() { echo "  [OK] $1"; OK=$((OK+1)); }
miss() { echo "  [--] $1"; MISS=$((MISS+1)); }

echo "=============================================="
echo "OpenClaw 本机环境检查（自主编程/自动化）"
echo "=============================================="
echo ""

echo ">>> 1. 基础命令"
command -v node >/dev/null 2>&1 && check "Node $(node -v)" || miss "未安装 Node（需 18+）"
command -v npm >/dev/null 2>&1 && check "npm $(npm -v)" || miss "未安装 npm"
command -v python3 >/dev/null 2>&1 && check "Python $(python3 --version 2>&1)" || miss "未安装 python3"
command -v openclaw >/dev/null 2>&1 || command -v openclaw-cn >/dev/null 2>&1 && check "OpenClaw 已安装" || miss "未安装 OpenClaw（npm i -g openclaw）"
echo ""

echo ">>> 2. 项目依赖"
[ -d "$PROJECT_ROOT/.venv" ] && check ".venv 存在" || miss "缺少 .venv，请运行: bash scripts/ensure_venv.sh"
[ -f "$PROJECT_ROOT/node_modules/playwright/package.json" ] && check "Playwright 已安装" || miss "请运行: npm install"
if [ -d "$PROJECT_ROOT/node_modules/playwright" ]; then
  if [ -d "$HOME/Library/Caches/ms-playwright" ] || [ -d "$HOME/.cache/ms-playwright" ] 2>/dev/null; then
    check "Playwright 浏览器（Chromium）已安装"
  else
    miss "Playwright 浏览器未安装，请运行: npx playwright install chromium"
  fi
fi
echo ""

echo ">>> 3. OpenClaw 配置 (~/.openclaw/openclaw.json)"
OPENCLAW_JSON="${OPENCLAW_CONFIG:-$HOME/.openclaw/openclaw.json}"
if [ ! -f "$OPENCLAW_JSON" ]; then
  miss "不存在 $OPENCLAW_JSON，请运行: bash scripts/merge_openclaw_autonomous.sh"
else
  check "配置文件存在"
  if command -v jq >/dev/null 2>&1; then
    if jq -e '.browser.enabled == true' "$OPENCLAW_JSON" >/dev/null 2>&1; then
      check "browser.enabled = true"
    else
      miss "需设置 browser.enabled: true 以使用浏览器自动化"
    fi
    if jq -e '.tools.allow | index("browser")' "$OPENCLAW_JSON" >/dev/null 2>&1 || jq -e '.tools.allow | index("exec")' "$OPENCLAW_JSON" >/dev/null 2>&1; then
      check "tools.allow 含 browser/exec"
    else
      miss "需在 tools.allow 中加入 browser、exec、read、write、edit"
    fi
    if jq -e '.tools.exec.ask == "off"' "$OPENCLAW_JSON" >/dev/null 2>&1; then
      check "tools.exec.ask = off（自主执行不询问）"
    else
      miss "建议 tools.exec.ask = \"off\"，运行: bash scripts/merge_openclaw_autonomous.sh"
    fi
    SKILLS_DIR=$(jq -r '.skills.load.extraDirs[0] // empty' "$OPENCLAW_JSON" 2>/dev/null)
    if [ -n "$SKILLS_DIR" ] && [ -d "$SKILLS_DIR" ] && [ -f "$SKILLS_DIR/htma-openclaw-autonomous/SKILL.md" ]; then
      check "skills.load.extraDirs 指向本项目 skills（$SKILLS_DIR）"
    else
      miss "skills.load.extraDirs 未指向本项目，请运行: bash scripts/merge_openclaw_autonomous.sh"
    fi
  fi
fi
echo ""

echo ">>> 4. 项目 .env"
if [ -f "$PROJECT_ROOT/.env" ]; then
  check ".env 存在"
  grep -q "MYSQL_" "$PROJECT_ROOT/.env" 2>/dev/null && check ".env 含 MYSQL_*" || miss ".env 需配置 MYSQL_HOST/USER/PASSWORD 等"
  grep -q "OPENAI_API_KEY\|FEISHU_APP_ID" "$PROJECT_ROOT/.env" 2>/dev/null && check ".env 含 API/飞书相关" || echo "  [.] 可选: OPENAI_API_KEY、FEISHU_APP_ID/SECRET"
else
  miss "缺少 .env，可复制 .env.example 并填写"
fi
echo ""

echo ">>> 5. 可选（外网访问）"
[ -f "$PROJECT_ROOT/.tunnel-token" ] && [ -s "$PROJECT_ROOT/.tunnel-token" ] && check ".tunnel-token 存在（Cloudflare 隧道）" || echo "  [.] 无 .tunnel-token 则外网不可用，需时创建并重新安装 launchd"
command -v jq >/dev/null 2>&1 && check "jq 已安装（merge 脚本需要）" || echo "  [.] 无 jq 时 merge 需手动合并 config/openclaw-htma-autonomous.json"
echo ""

echo "=============================================="
if [ "$MISS" -eq 0 ]; then
  echo "环境就绪，OpenClaw 可自主执行约定任务。"
  echo "在 OpenClaw 中说: 「利用 openclaw 自主完成编程工作」或「使用 openclaw 自动检查并修改完善」"
else
  echo "有 $MISS 项待完善，请按上述 [--] 提示修复。"
  echo "合并自主配置: bash scripts/merge_openclaw_autonomous.sh"
  echo "安装 Playwright 浏览器: npx playwright install chromium"
fi
echo "=============================================="
