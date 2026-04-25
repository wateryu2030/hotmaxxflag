#!/bin/bash
# 好特卖看板 - 桌面一键启动（锁屏后仍可用，由系统后台服务运行）
# 用法：双击本文件，或从桌面快捷方式双击。会安装/启动 LaunchAgent 并打开浏览器，无需打开 Cursor。

# 解析项目根目录（支持从桌面快捷方式 symlink 双击）
resolve_project_root() {
  local src="$0"
  while [ -L "$src" ]; do
    local tgt="$(readlink "$src")"
    [[ "$tgt" != /* ]] && tgt="$(cd "$(dirname "$src")" && pwd)/$tgt"
    src="$tgt"
  done
  cd "$(dirname "$src")" && pwd
}

PROJECT_ROOT="$(resolve_project_root)"
cd "$PROJECT_ROOT" || { echo "无法进入项目目录"; read -n 1; exit 1; }

echo "=========================================="
echo "  好特卖运营看板 - 一键启动"
echo "=========================================="
echo ""

# 1. 安装/更新并启动后台服务（看板 + 防睡眠，锁屏下照常运行）
if [ -f "$PROJECT_ROOT/scripts/install_launchd_htma.sh" ]; then
  bash "$PROJECT_ROOT/scripts/install_launchd_htma.sh"
else
  echo "未找到 scripts/install_launchd_htma.sh，请确认在项目根目录执行。"
  read -n 1
  exit 1
fi

echo ""
echo "等待看板就绪..."
for i in 1 2 3 4 5 6 7 8 9 10; do
  curl -sS -o /dev/null -w "" http://127.0.0.1:5002/ 2>/dev/null && break
  sleep 1
done

# 若 LaunchAgent 未起来（如项目在外置卷导致退出码 78），则本次会话直接后台启动看板
if ! curl -sS -o /dev/null -w "" http://127.0.0.1:5002/ 2>/dev/null; then
  echo "后台服务未就绪（常见于项目在外置盘），改为本次直接启动看板..."
  nohup bash "$PROJECT_ROOT/scripts/start_htma.sh" >> "$PROJECT_ROOT/logs/dashboard.out.log" 2>> "$PROJECT_ROOT/logs/dashboard.err.log" &
  for j in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    curl -sS -o /dev/null -w "" http://127.0.0.1:5002/ 2>/dev/null && break
  done
fi

# 2. 打开浏览器
open "http://127.0.0.1:5002" 2>/dev/null || true

echo ""
echo "已启动。"
echo "  本机: http://127.0.0.1:5002"
if [[ "$PROJECT_ROOT" == /Volumes/* ]]; then
  echo "  说明: 项目在外置盘，锁屏后若 502 可再次双击本图标启动看板；长期稳定请将项目拷到本机盘后重新运行「创建桌面快捷方式」。"
else
  echo "  锁屏后仍可访问。关闭此窗口不影响看板运行。"
fi
echo ""
read -n 1 -p "按任意键关闭此窗口..."
