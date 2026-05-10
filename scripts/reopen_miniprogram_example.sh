#!/usr/bin/env bash
# 促使微信开发者工具重新加载 miniprogram_example（touch 配置 + 用目录唤起 IDE）
# 首页日志需在模拟器内查看；INVALID_TOKEN 时见脚本末尾说明
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJ="$ROOT/miniprogram_example"
for f in "$PROJ/project.config.json" "$PROJ/project.private.config.json" "$PROJ/app.json"; do
  [ -f "$f" ] && touch "$f"
done
open -a "/Applications/wechatwebdevtools.app" "$PROJ" 2>/dev/null || true
echo "已更新工程文件时间戳并已尝试打开: $PROJ"
echo "请在工具内: 编译 → 模拟器查看首页日志；或 项目 → 重新打开此目录。"
if command -v python3 >/dev/null 2>&1; then
  python3 <<PY
import json, os
root = r"$ROOT"
proj = json.load(open(os.path.join(root, "miniprogram_example", "project.config.json"), encoding="utf-8"))
env_id = ""
p = os.path.join(root, ".env")
if os.path.isfile(p):
    for line in open(p, encoding="utf-8", errors="ignore"):
        if line.strip().startswith("WECHAT_APPID="):
            env_id = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
pid = (proj.get("appid") or "").strip()
if pid and env_id and pid == env_id:
    print("AppID 与项目根 .env 一致。")
elif pid and env_id:
    print("警告: AppID 与 .env 不一致，请统一。")
else:
    print("提示: 未找到完整 AppID 比对信息。")
PY
fi
echo ""
echo "若仍 INVALID_TOKEN（开放平台 access_token）:"
echo "  1) 微信开发者工具右上角退出 → 重新扫码登录"
echo "  2) 公众平台 AppSecret 与服务器 .env 中 WECHAT_APPSECRET 保持一致（重置密钥后须同步）"
echo "  3) 工具 → 设置 → 安全 → 开启「服务端口」便于 CLI（可选）"
