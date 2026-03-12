#!/usr/bin/env bash
# 完整版 OpenClaw + 百度 Skill：使 clawhub run 可用并返回多平台（京东/淘宝等），看板可展示 jd_min_price、taobao_min_price。
# 用法: cd 项目根 && bash scripts/setup_full_openclaw_baidu_skill.sh
# 若本机尚未安装完整版 OpenClaw，会先执行 reinstall_openclaw_full.sh；完成后需手动执行一次 openclaw onboard。

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export PATH="$HOME/.npm-global/bin:$(pnpm root -g 2>/dev/null)/../bin:/usr/local/bin:$PATH"
export PNPM_HOME="${PNPM_HOME:-$HOME/Library/pnpm}"
export PATH="$PNPM_HOME:$PATH"

echo "=============================================="
echo "  完整版 OpenClaw + 百度 Skill（京东/淘宝分平台比价）"
echo "=============================================="
echo ""

NEED_REINSTALL=false
if ! command -v openclaw &>/dev/null; then
  echo "【未检测到 openclaw】将执行完整版安装（含 clawhub run）。"
  NEED_REINSTALL=true
elif ! clawhub run --help &>/dev/null; then
  echo "【clawhub 无 run 子命令】当前多为 npm 版，将重装完整版以支持 clawhub run。"
  NEED_REINSTALL=true
fi

if $NEED_REINSTALL; then
  echo ""
  echo "======== 执行完整版重装（需数分钟） ========"
  bash "$SCRIPT_DIR/reinstall_openclaw_full.sh"
  echo ""
  echo "======== 请按顺序完成以下步骤（需本机交互） ========"
  echo "1) 初始化配置（API Key、Skills 等）："
  echo "   openclaw onboard --install-daemon"
  echo ""
  echo "2) 启用网关并安装百度 Skill："
  echo "   cd $PROJECT_ROOT"
  echo "   bash scripts/enable_baidu_skill_gateway.sh --install-skill"
  echo ""
  echo "3) 验证比价路径与数据来源："
  echo "   bash scripts/diagnose_baidu_skill.sh"
  echo "   期望【5】显示 source=baidu_skill，且能返回京东/淘宝等多平台。"
  echo ""
  echo "4) 看板货盘比价将自动解析并展示 jd_min_price、taobao_min_price。"
  echo ""
  exit 0
fi

echo "【已检测到完整版 OpenClaw（clawhub run 可用）】"
echo ""

# 若未配置过，提示先 onboard
if [[ ! -f "$HOME/.openclaw/openclaw.json" ]]; then
  echo "尚未执行过配置向导，请先运行："
  echo "  openclaw onboard --install-daemon"
  echo "完成后重新执行："
  echo "  bash scripts/setup_full_openclaw_baidu_skill.sh"
  echo ""
  exit 0
fi

echo "【1】启用网关并安装百度 Skill"
bash "$SCRIPT_DIR/enable_baidu_skill_gateway.sh" --install-skill
echo ""

echo "【2】诊断比价路径（确认 source=baidu_skill 与多平台）"
bash "$SCRIPT_DIR/diagnose_baidu_skill.sh"
echo ""

echo "=============================================="
echo "  完成说明"
echo "=============================================="
echo "若诊断【5】显示 source=baidu_skill，则 clawhub run 已返回多平台数据；"
echo "看板货盘比价会解析 京东/淘宝 等并展示 jd_min_price、taobao_min_price。"
echo "若仍为 source=baidu_youxuan_mcp，说明当前仍走 MCP 回退（仅聚合价）；"
echo "可检查：clawhub run baidu-preferred --query '洽洽坚果' 是否直接返回多平台 JSON。"
echo ""
