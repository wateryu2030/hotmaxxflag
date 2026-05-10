#!/usr/bin/env bash
# 一键：杀 5002 → 重启看板 → 打开本机网页 → 清缓存并打开小程序（需微信开发者工具已开「服务端口」）
# 用法: bash scripts/dev_full_stack_restart.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
bash "$ROOT/scripts/restart_htma_dashboard.sh"
open "http://127.0.0.1:5002/" 2>/dev/null || true
open "https://htma.greatagain.com.cn/" 2>/dev/null || true
WECHAT_IDE_READY_WAIT_SEC="${WECHAT_IDE_READY_WAIT_SEC:-90}" bash "$ROOT/scripts/wechat_miniprogram_clean_rebuild.sh" || {
  echo "[dev_full_stack_restart] 微信 CLI 未就绪，改用 open 打开工程（请在工具内手动清缓存并编译）" >&2
  open -a "/Applications/wechatwebdevtools.app" "$ROOT/miniprogram" 2>/dev/null || true
}
