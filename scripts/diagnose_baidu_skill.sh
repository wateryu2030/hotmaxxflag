#!/usr/bin/env bash
# 诊断「百度 Skill 被忽略」的原因：为何当前走的是百度优选 MCP 而非 clawhub run。
# 用法: bash scripts/diagnose_baidu_skill.sh
# 注意: 网关可达性等需访问本机 127.0.0.1，请在系统终端（沙箱外）执行，否则可能误报「网关不可达」。

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=============================================="
echo "  百度 Skill 比价路径诊断"
echo "=============================================="
echo ""

# 0) 百度 Skill 专用网关（clawhub 已无 baidu-preferred 时的推荐方式）
echo "【0】百度 Skill 专用网关 (OPENCLAW_BAIDU_SKILL_GATEWAY_URL)"
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  BAIDU_GW=$(grep -m1 '^OPENCLAW_BAIDU_SKILL_GATEWAY_URL=' "$PROJECT_ROOT/.env" 2>/dev/null | sed 's/^OPENCLAW_BAIDU_SKILL_GATEWAY_URL=//' | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
fi
BAIDU_GW="${BAIDU_GW:-}"
if [[ -n "$BAIDU_GW" ]]; then
  echo "  结果: 已配置，将优先请求该网关 ($BAIDU_GW)"
  echo "  说明: 看板与 runner 会先调用该 URL 的 /tools/invoke，再 fallback 本机网关/MCP。详见 docs/百度Skill优先-无clawhub方案.md"
else
  echo "  结果: 未配置"
  echo "  说明: clawhub 上已无 baidu-preferred；若需优先用百度 Skill（如手机端已可用），请在 .env 中配置 OPENCLAW_BAIDU_SKILL_GATEWAY_URL，见 docs/百度Skill优先-无clawhub方案.md"
fi
echo ""

# 1) 网关是否可达
echo "【1】本机 OpenClaw 网关 (OPENCLAW_GATEWAY_URL)"
GATEWAY_URL="${OPENCLAW_GATEWAY_URL:-http://127.0.0.1:18789}"
if curl -sS -o /dev/null -w "%{http_code}" --max-time 3 "$GATEWAY_URL/" 2>/dev/null | grep -q '200\|301\|302'; then
  echo "  结果: 网关可达 ($GATEWAY_URL)"
  echo "  说明: 看板会优先请求网关 /tools/invoke，再由网关调用 runner。"
else
  echo "  结果: 网关不可达 ($GATEWAY_URL)"
  echo "  说明: 看板会跳过网关，直接执行 runner（scripts/openclaw_baidu_tools_runner.py）。"
  echo "  处理: 若需走网关，请启动 OpenClaw 并执行 bash scripts/setup_openclaw_baidu_tools.sh 后重启网关。"
  echo "  提示: 若在 Cursor/沙箱内运行，本机网关可能显示不可达；请在系统终端（沙箱外）执行本脚本以确认。"
fi
echo ""

# 2) clawhub 是否存在、是否有 run 命令
echo "【2】clawhub 与 run 子命令"
export PATH="$HOME/.npm-global/bin:/usr/local/bin:$PATH"
if ! command -v clawhub >/dev/null 2>&1; then
  echo "  结果: 未找到 clawhub"
  echo "  说明: runner 内无法执行「clawhub run <slug>」，会直接回退到百度优选 MCP。"
  echo "  处理: 安装 npm 版仅能 search/install；若需 run，请安装完整 OpenClaw（见 docs/OpenClaw完整版重装方案.md）。"
else
  echo "  结果: 已找到 clawhub ($(which clawhub))"
  HELP=$(clawhub --help 2>&1) || true
  if echo "$HELP" | grep -q "run"; then
    echo "  结果: 存在 run 子命令，百度 Skill 路径可用（若已安装对应 Skill）。"
  else
    echo "  结果: 当前 clawhub 无 run 子命令（常见于 npm 版）。"
    echo "  说明: runner 执行「clawhub run baidu-preferred --query xxx」会失败，自动回退到百度优选 MCP。"
    echo "  处理: 若需真正走百度 Skill，请安装完整版 OpenClaw（支持 run），并 clawhub install baidu-preferred。"
  fi
fi
echo ""

# 3) 是否已安装百度 Skill（skills/ 或 --dir 指定目录）
echo "【3】本地是否已安装百度 Skill"
SLUG="baidu-preferred"
FOUND=""
for dir in "$PROJECT_ROOT/skills/$SLUG" "$PROJECT_ROOT/skills/baidu-ecommerce-skill"; do
  if [[ -d "$dir" ]] && [[ -f "$dir/SKILL.md" || -f "$dir/package.json" ]]; then
    FOUND="$dir"
    break
  fi
done
if [[ -n "$FOUND" ]]; then
  echo "  结果: 已存在 Skill 目录: $FOUND"
  echo "  说明: 仅当 clawhub 支持 run 时才会被调用；当前 npm 版无 run 则仍会回退 MCP。"
else
  echo "  结果: 未找到 skills/baidu-preferred 或 skills/baidu-ecommerce-skill"
  echo "  说明: 即使有 run 命令，也需先 clawhub install <slug>；当前无 run 时不影响（已用 MCP 回退）。"
fi
echo ""

# 4) 百度优选 MCP 是否配置
echo "【4】百度优选 MCP 回退（BAIDU_YOUXUAN_TOKEN）"
if [[ -f "$PROJECT_ROOT/.env" ]] && grep -q "BAIDU_YOUXUAN_TOKEN=.\+" "$PROJECT_ROOT/.env" 2>/dev/null; then
  echo "  结果: 已配置 BAIDU_YOUXUAN_TOKEN"
  echo "  说明: clawhub run 不可用时，runner 会由此拿到比价数据，故能出结果。"
else
  echo "  结果: 未配置或为空"
  echo "  说明: 若 clawhub run 也不可用，比价将无数据。建议在 .env 中配置百度优选开放平台服务端 Token。"
fi
echo ""

# 5) 一次实际调用看 source
echo "【5】实际调用 runner 看数据来源（query=洽洽坚果）"
PYTHON=""
[[ -x "$PROJECT_ROOT/.venv/bin/python" ]] && PYTHON="$PROJECT_ROOT/.venv/bin/python" || PYTHON="python3"
OUT=$("$PYTHON" "$PROJECT_ROOT/scripts/openclaw_baidu_tools_runner.py" get_price_comparison "洽洽坚果" 2>&1) || true
LAST=$(echo "$OUT" | tail -1)
if echo "$LAST" | grep -q '"source"'; then
  SOURCE=$(echo "$LAST" | sed -n 's/.*"source"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
  if [[ "$SOURCE" == "baidu_skill" ]]; then
    echo "  结果: source=baidu_skill（本次数据来自百度 Skill：专用网关或 clawhub run）"
  elif [[ "$SOURCE" == "baidu_youxuan_mcp" ]]; then
    echo "  结果: source=baidu_youxuan_mcp（本次数据来自百度优选 MCP，即 clawhub run 被跳过）"
    echo "  原因: 本机 clawhub 无 run 或 run 失败，runner 自动回退到 MCP。"
  else
    echo "  结果: source=$SOURCE 或 无数据"
  fi
else
  echo "  结果: 无法解析 source（可能 runner 输出格式变更）"
fi
echo ""

echo "=============================================="
echo "  总结"
echo "=============================================="
echo "优先用百度 Skill（clawhub 上已无 baidu-preferred）："
echo "  → 推荐：在 .env 配置 OPENCLAW_BAIDU_SKILL_GATEWAY_URL，指向已可用的百度 Skill 网关（如手机/其他端），见 docs/百度Skill优先-无clawhub方案.md"
echo "当前走 MCP 的常见原因："
echo "  1) 未配置百度 Skill 专用网关，且本机 clawhub 无 run 或 skills 未安装 → 回退 MCP。"
echo "  2) 本机网关未启动 → 看板直接调 runner。"
echo "若已配置 BAIDU_YOUXUAN_TOKEN，回退时仍能出比价结果；若需多平台百度 Skill，请配置专用网关。"
echo ""
