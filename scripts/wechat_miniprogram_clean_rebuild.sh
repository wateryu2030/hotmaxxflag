#!/usr/bin/env bash
# 微信开发者工具：清理缓存 + 打开工程并触发编译 + 重建文件监听（替代已废弃的 engine build）
# 前置：① 已安装开发者工具 ② 必须先在本机打开工具，并在「设置 → 安全设置」开启「服务端口」
# 说明：新版工具不再提供 HTTP /engine/build，旧版「cli engine build」会报 Cannot GET /engine/build，已移除。
# 若 cache/open 报 ECONNRESET/TLS：多为系统代理（如 127.0.0.1:7897）拦截，请在工具内「设置→代理」选直连或关系统代理。
# 端口解析：Default/.cli 有时会滞后；脚本会优先从 WeappLocalData/localstorage_*.json 的 security.port
# 与 lsof 中 wechatweb 的 127.0.0.1 监听端口收集候选，谁在监听用谁（避免 .cli=3805 实际=11598 导致 nc 拒绝）。
# 用法: bash scripts/wechat_miniprogram_clean_rebuild.sh
# 可选: WECHAT_IDE_CLI_PORT=11598 WECHAT_IDE_READY_WAIT_SEC=120 bash scripts/wechat_miniprogram_clean_rebuild.sh
# 可选: WECHAT_CACHE_CLEAN_ALL=1 时额外执行 cache --clean all（更彻底，略慢）

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJ="$ROOT/miniprogram"
APP="/Applications/wechatwebdevtools.app"
CLI="$APP/Contents/MacOS/cli"

if [ ! -d "$PROJ" ]; then
  echo "未找到: $PROJ" >&2
  exit 1
fi
if [ ! -x "$CLI" ]; then
  echo "未找到 CLI: $CLI" >&2
  exit 1
fi

discover_cli_file_port() {
  local base="$HOME/Library/Application Support/微信开发者工具"
  if [ ! -d "$base" ]; then
    echo ""
    return
  fi
  local f
  f=$(find "$base" -path "*/Default/.cli" -type f 2>/dev/null | head -1)
  if [ -n "$f" ] && [ -r "$f" ]; then
    tr -d '\n\r ' <"$f"
  else
    echo ""
  fi
}

# 从设置同步文件读取「当前服务端口」（与 .cli 可能不一致）
security_port_from_localstorage() {
  python3 <<'PY' 2>/dev/null || true
import json, os
base = os.path.expanduser("~/Library/Application Support/微信开发者工具")
best_p, best_t = None, -1.0
if not os.path.isdir(base):
    raise SystemExit
for root, _dirs, files in os.walk(base):
    if not root.endswith("WeappLocalData"):
        continue
    for name in files:
        if not (name.startswith("localstorage_") and name.endswith(".json")):
            continue
        path = os.path.join(root, name)
        try:
            t = os.path.getmtime(path)
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            sec = d.get("security") or {}
            if sec.get("enableServicePort") and sec.get("port") is not None:
                p = int(sec["port"])
                if t >= best_t:
                    best_t, best_p = t, p
        except Exception:
            pass
if best_p is not None:
    print(best_p)
PY
}

ports_from_lsof_wechat() {
  lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | awk '/^[Ww]echatweb/ && $9 ~ /^127\.0\.0\.1:/ {
    split($9, a, ":");
    print a[2]
  }' | sort -u
}

tcp_port_open() {
  local p="$1"
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$p" 2>/dev/null
    return $?
  fi
  (echo >/dev/tcp/127.0.0.1/"$p") 2>/dev/null
  return $?
}

# 输出：去重后的候选端口（每行一个），顺序：环境变量 → 设置文件 → .cli → lsof
list_port_candidates() {
  [ -n "${WECHAT_IDE_CLI_PORT:-}" ] && echo "${WECHAT_IDE_CLI_PORT}"
  security_port_from_localstorage
  discover_cli_file_port
  ports_from_lsof_wechat
}

wait_any_port_listen() {
  local max_wait="${WECHAT_IDE_READY_WAIT_SEC:-90}"
  local elapsed=0
  local step=2
  local tmp
  tmp=$(mktemp)
  list_port_candidates | awk 'NF && !a[$0]++' >"$tmp"
  if [ ! -s "$tmp" ]; then
    rm -f "$tmp"
    echo ""
    return 1
  fi
  echo ">>> 服务端口候选（去重）: $(tr '\n' ' ' <"$tmp" | sed 's/ $//')" >&2
  while [ "$elapsed" -lt "$max_wait" ]; do
    while IFS= read -r p; do
      [ -z "$p" ] && continue
      if tcp_port_open "$p"; then
        echo "$p"
        rm -f "$tmp"
        return 0
      fi
    done <"$tmp"
    sleep "$step"
    elapsed=$((elapsed + step))
    echo ">>> 等待任一候选端口就绪 ... ${elapsed}s / ${max_wait}s（请保持微信开发者工具已打开并已开启「服务端口」）" >&2
  done
  rm -f "$tmp"
  echo ""
  return 1
}

warn_proxy() {
  if command -v networksetup >/dev/null 2>&1; then
    local on=0
    for s in Wi-Fi Ethernet; do
      networksetup -listallnetworkservices 2>/dev/null | grep -qx "$s" 2>/dev/null || continue
      if networksetup -getwebproxy "$s" 2>/dev/null | grep -q "Enabled: Yes"; then
        on=1
        echo ">>> 提示: 系统代理已开启 ($s)。若 CLI 报 TLS/ECONNRESET，请开发者工具「设置→代理」选「不使用任何代理」或暂时关闭系统 HTTP 代理。" >&2
      fi
    done
    [ "$on" = "1" ] || true
  fi
}
warn_proxy

echo ">>> 拉起微信开发者工具并打开项目: $PROJ"
open -a "$APP" "$PROJ" 2>/dev/null || true
sleep 2

if ! list_port_candidates | awk 'NF' | head -1 | grep -q .; then
  echo "未检测到任何端口候选（无 .cli / 无 localstorage 中的 security.port）。请：① 打开微信开发者工具 ② 设置 → 安全设置 → 开启「服务端口」③ 再执行本脚本，或设置 WECHAT_IDE_CLI_PORT=工具界面显示的端口" >&2
  echo "已尝试仅 open 工程；请在工具内手动：项目 → 清缓存 → 全部清除 → 编译。" >&2
  exit 0
fi

PORT="$(wait_any_port_listen || true)"
if [ -z "$PORT" ]; then
  echo "" >&2
  echo "未在 ${WECHAT_IDE_READY_WAIT_SEC:-90}s 内检测到 127.0.0.1 上可连接的 CLI 服务端口。" >&2
  echo "请：① 打开微信开发者工具并登录 ② 设置 → 安全设置 → 开启「服务端口」并记下端口号 ③ 执行：" >&2
  echo "  WECHAT_IDE_CLI_PORT=<该端口> bash scripts/wechat_miniprogram_clean_rebuild.sh" >&2
  echo "（可选）仅打开工程：open -a \"/Applications/wechatwebdevtools.app\" \"$PROJ\"" >&2
  exit 1
fi

CLI_FILE_PORT="$(discover_cli_file_port)"
if [ -n "$CLI_FILE_PORT" ] && [ "$CLI_FILE_PORT" != "$PORT" ]; then
  echo ">>> 提示: Default/.cli 记录为 ${CLI_FILE_PORT}，实际监听为 ${PORT}；已使用 ${PORT} 调用 CLI（可在工具内重新开关一次「服务端口」以同步 .cli）。" >&2
fi

echo ">>> 使用 CLI 端口: ${PORT}"

run_cli() {
  "$CLI" --port "$PORT" --lang zh "$@"
}

echo ">>> cache --clean compile"
run_cli cache --clean compile --project "$PROJ" || true
echo ">>> cache --clean file"
run_cli cache --clean file --project "$PROJ" || true
echo ">>> cache --clean storage"
run_cli cache --clean storage --project "$PROJ" || true

if [ "${WECHAT_CACHE_CLEAN_ALL:-}" = "1" ]; then
  echo ">>> cache --clean all（WECHAT_CACHE_CLEAN_ALL=1）"
  run_cli cache --clean all --project "$PROJ" || true
fi

echo ">>> cache --clean network（清理工具内网络缓存，减轻异常 TLS 重试）"
run_cli cache --clean network --project "$PROJ" || true

echo ">>> open（自动编译刷新；官方已废弃 engine build /v1 HTTP）"
run_cli open --project "$PROJ" || true

echo ">>> reset-fileutils（重建文件监听，等同旧版「彻底刷新工程」）"
run_cli reset-fileutils --project "$PROJ" || true

echo "完成。请在工具右上角确认「调试基础库」>= 2.9.0 (project.private.config.json 已设 libVersion)。"
