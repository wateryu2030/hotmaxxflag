#!/usr/bin/env bash
# 百度 Skill 比价环境一键验证：projectRoot、runner+MCP 比价、可选 ClawHub 安装
# 用法: bash scripts/verify_baidu_skill.sh [--install]
# --install: 在验证通过后尝试 clawhub install baidu-preferred（可能遇限流）
# 建议在系统终端（沙箱外）执行，以便正确访问本机网关与 runner。

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON=""
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON="$PROJECT_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  PYTHON="python"
fi

echo "=== 1. 检查 .env（百度 Skill 专用网关 / MCP 回退）==="
if [[ -f "$PROJECT_ROOT/.env" ]] && grep -q "OPENCLAW_BAIDU_SKILL_GATEWAY_URL=.\+" "$PROJECT_ROOT/.env" 2>/dev/null; then
  echo "  OPENCLAW_BAIDU_SKILL_GATEWAY_URL 已配置，将优先使用百度 Skill 专用网关（无需 clawhub install）。见 docs/百度Skill优先-无clawhub方案.md"
fi
if [[ -f "$PROJECT_ROOT/.env" ]] && grep -q "BAIDU_YOUXUAN_TOKEN=.\+" "$PROJECT_ROOT/.env" 2>/dev/null; then
  echo "  BAIDU_YOUXUAN_TOKEN 已配置，专用网关不可用时 runner 将用其回退获取比价。"
else
  echo "  警告: .env 中未配置 BAIDU_YOUXUAN_TOKEN，回退时将无 MCP 数据源。"
  echo "  建议在 .env 中增加: BAIDU_YOUXUAN_TOKEN=你的服务端Token"
fi
echo ""

echo "=== 2. 写入 OpenClaw 网关 projectRoot（供网关插件调用 runner）==="
bash "$SCRIPT_DIR/setup_openclaw_baidu_tools.sh"
echo ""

echo "=== 3. 测试 runner 比价（洽洽坚果）==="
OUT=$("$PYTHON" "$PROJECT_ROOT/scripts/openclaw_baidu_tools_runner.py" get_price_comparison "洽洽坚果" 2>&1) || true
if echo "$OUT" | grep -q '"data".*"price"'; then
  echo "  通过: runner 返回了比价数据（网关/看板将使用同一 runner）。"
  echo "  示例输出: $(echo "$OUT" | tail -1)"
else
  echo "  失败: runner 未返回可解析的价格。"
  echo "  输出: $OUT"
  exit 1
fi
echo ""

TRY_INSTALL=false
for a in "$@"; do
  if [[ "$a" == "--install" ]]; then TRY_INSTALL=true; break; fi
done

if $TRY_INSTALL; then
  echo "=== 4. 尝试安装百度 Skill（clawhub install）==="
  echo "  注意: clawhub 公共源已无 baidu-preferred，安装通常会失败。"
  echo "  推荐: 在 .env 配置 OPENCLAW_BAIDU_SKILL_GATEWAY_URL 指向已可用的百度 Skill 网关，见 docs/百度Skill优先-无clawhub方案.md"
  export PATH="$HOME/.npm-global/bin:/usr/local/bin:$PATH"
  if ! command -v clawhub >/dev/null 2>&1; then
    echo "  未找到 clawhub，跳过安装。可执行: npm install -g clawhub"
  else
    for slug in baidu-preferred baidu-ecommerce-skill; do
      echo "  尝试: clawhub install $slug --workdir $PROJECT_ROOT --dir skills --no-input"
      if clawhub install "$slug" --workdir "$PROJECT_ROOT" --dir skills --no-input 2>&1; then
        echo "  安装成功: skills/$slug"
        break
      fi
      echo "  当前 slug 安装未成功（clawhub 上可能已无该 skill，建议用专用网关方案）。"
    done
  fi
else
  echo "=== 4. 跳过 ClawHub 安装（加 --install 可尝试；推荐用 OPENCLAW_BAIDU_SKILL_GATEWAY_URL）==="
fi

echo ""
echo "=== 完成 ==="
echo "看板货盘比价会优先走网关 POST /tools/invoke，不可用时走 runner；runner 已能通过百度优选 MCP 出结果。"
echo "若需网关也可用，请启动 OpenClaw 网关并重启（见 setup_openclaw_baidu_tools.sh 末尾提示）。"
