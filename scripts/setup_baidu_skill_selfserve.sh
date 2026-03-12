#!/bin/bash
# 自助执行：百度电商 Skill 环境检查 → 搜索 → 安装 → 自检
# 用法：bash scripts/setup_baidu_skill_selfserve.sh
# 若 ClawHub 注册中心限流，请稍后重试本脚本。

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# 确保 clawhub 在 PATH 中
export PATH="$HOME/.npm-global/bin:/usr/local/bin:$PATH"

echo "=== 1. 检查 clawhub ==="
if ! command -v clawhub >/dev/null 2>&1; then
  echo "未找到 clawhub。请先执行: npm install -g clawhub"
  echo "然后执行以下任一使 clawhub 可用："
  echo "  source $PROJECT_ROOT/scripts/ensure_clawhub_path.sh"
  echo "  或: export PATH=\"\$HOME/.npm-global/bin:\$PATH\""
  exit 1
fi
clawhub -V
echo ""

echo "=== 2. 搜索百度相关 Skill（若限流请稍后重试）==="
SEARCH_OUT=$(clawhub search "baidu" --limit 5 2>&1) || true
if echo "$SEARCH_OUT" | grep -q "Rate limit exceeded"; then
  echo "当前 ClawHub 限流，跳过搜索。请稍后重试: clawhub search \"baidu\""
  echo "或到 https://clawhub.ai 网页搜索「百度」获取准确 slug。"
  SLUG="baidu-ecommerce-skill"
else
  echo "$SEARCH_OUT"
  # 搜索 "baidu" 目前不返回电商 skill，优先建议用网页版安装；仍试默认 slug
  if echo "$SEARCH_OUT" | grep -q "baidu-ecommerce"; then
    SLUG="baidu-ecommerce-skill"
  else
    SLUG="baidu-ecommerce-skill"
  fi
  echo "（若安装报 Skill not found，请用 OpenClaw 网页版说「安装百度电商 Skill」或到 clawhub.ai 查准确 slug）"
fi
echo ""

echo "=== 3. 安装 Skill: $SLUG ==="
if clawhub install "$SLUG" --workdir "$PROJECT_ROOT" --dir skills --no-input 2>&1; then
  echo "安装成功: skills/$SLUG"
else
  echo "安装未成功（可能 slug 有误或限流）。请到 clawhub.ai 确认 slug 后执行:"
  echo "  clawhub install <准确slug> --workdir $PROJECT_ROOT --dir skills"
fi
echo ""

echo "=== 4. 自检说明 ==="
echo "当前 npm 版 ClawHub CLI 无 run 子命令，无法在此执行「clawhub run <slug> --query 洽洽坚果」自检。"
echo "安装好 Skill 后，若使用完整 OpenClaw 运行时，请按官方文档执行 run；或直接在前端执行货盘比价验证。"
echo ""
echo "=== 完成 ==="
echo "后续：限流解除后请重试本脚本，或手动执行 clawhub search \"baidu\" 与 clawhub install <slug>。"
