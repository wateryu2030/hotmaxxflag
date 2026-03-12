#!/usr/bin/env bash
# 在已安装完整版 OpenClaw 的前提下：配置网关 projectRoot、启动网关、可选安装百度 Skill。
# 若未安装 openclaw，会提示先执行 scripts/reinstall_openclaw_full.sh。
# 用法: bash scripts/enable_baidu_skill_gateway.sh [--install-skill]

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# 确保 PATH 含 openclaw（完整版通过 pnpm link 安装）
export PATH="$HOME/.npm-global/bin:$(pnpm root -g 2>/dev/null)/../bin:/usr/local/bin:$PATH"
export PNPM_HOME="${PNPM_HOME:-$HOME/Library/pnpm}"
export PATH="$PNPM_HOME:$PATH"

echo "=============================================="
echo "  启用百度 Skill 路径（网关 + 可选 clawhub run）"
echo "=============================================="
echo ""

if ! command -v openclaw &>/dev/null; then
  echo "【未检测到 openclaw】"
  echo "请先安装完整版 OpenClaw（含 clawhub run 与网关），执行："
  echo ""
  echo "  cd $PROJECT_ROOT"
  echo "  bash scripts/reinstall_openclaw_full.sh"
  echo ""
  echo "安装完成后按脚本末尾提示执行："
  echo "  openclaw onboard --install-daemon"
  echo "  clawhub install baidu-preferred   # 可选，限流时稍后重试"
  echo "然后重新运行本脚本："
  echo "  bash scripts/enable_baidu_skill_gateway.sh"
  echo ""
  exit 1
fi

echo "【1】写入网关 projectRoot（baidu-price-tools 插件）"
bash "$SCRIPT_DIR/setup_openclaw_baidu_tools.sh"
echo ""

echo "【2】启动 OpenClaw 网关"
if openclaw gateway status &>/dev/null; then
  echo "  网关已在运行，如需重启: openclaw gateway restart"
else
  echo "  正在启动网关..."
  openclaw gateway install 2>/dev/null || true
  openclaw gateway start 2>/dev/null || true
  sleep 3
fi
if curl -sS -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:18789/" 2>/dev/null | grep -qE '200|301|302'; then
  echo "  网关已就绪: http://127.0.0.1:18789"
else
  echo "  若网关未就绪：请执行 openclaw logs follow 查看日志，或 openclaw onboard --install-daemon 完成初始化。"
  echo "  若出现 Unknown config keys plugins.baidu-price-tools：可忽略，或为网关进程设置环境变量 OPENCLAW_BAIDU_PROJECT_ROOT=$PROJECT_ROOT"
fi
echo ""

INSTALL_SKILL=false
for a in "$@"; do
  [[ "$a" == "--install-skill" ]] && INSTALL_SKILL=true && break
done

if $INSTALL_SKILL; then
  echo "【3】尝试安装百度 Skill（clawhub install）"
  if command -v clawhub &>/dev/null; then
    for slug in baidu-preferred baidu-ecommerce-skill; do
      if clawhub install "$slug" --workdir "$PROJECT_ROOT" --dir skills --no-input 2>&1; then
        echo "  已安装: skills/$slug"
        break
      fi
      echo "  当前 slug 未成功（可能限流），可稍后重试: clawhub install $slug --workdir $PROJECT_ROOT --dir skills"
    done
  else
    echo "  未找到 clawhub，请确认完整版 OpenClaw 已安装并 link。"
  fi
else
  echo "【3】跳过安装 Skill（加 --install-skill 可尝试 clawhub install baidu-preferred）"
fi

echo ""
echo "=============================================="
echo "  验证"
echo "=============================================="
echo "1) 诊断比价路径: bash scripts/diagnose_baidu_skill.sh"
echo "   【1】应显示「网关可达」；【5】若已安装 Skill 且 clawhub 有 run，可能为 source=baidu_skill"
echo "2) 看板货盘比价会优先请求网关，再由网关调用 runner。"
echo "3) 若需 clawhub run 直接出数据，请确保已执行: clawhub install baidu-preferred（限流时稍后重试）"
echo ""
