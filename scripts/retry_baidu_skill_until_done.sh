#!/bin/bash
# 定时重试：尝试安装百度电商 Skill，成功则标记完成并退出；失败则退出非 0，由 launchd 隔一段时间再次拉起，直至完成。
# 用法：由 launchd 按间隔执行；或手动 bash scripts/retry_baidu_skill_until_done.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DONE_FILE="$PROJECT_ROOT/.baidu_skill_installed"
LOG_FILE="$PROJECT_ROOT/logs/retry_baidu_skill.log"

mkdir -p "$PROJECT_ROOT/logs"
export PATH="$HOME/.npm-global/bin:/usr/local/bin:$PATH"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# 已完成则直接退出 0
if [ -f "$DONE_FILE" ]; then
  log "已存在完成标记 $DONE_FILE，跳过"
  exit 0
fi

if ! command -v clawhub >/dev/null 2>&1; then
  log "未找到 clawhub，跳过本次（请先 npm install -g clawhub 并配置 PATH）"
  exit 1
fi

cd "$PROJECT_ROOT"
SLUG="baidu-ecommerce-skill"

# 尝试安装（先试默认 slug，限流或 not found 则失败，下次再试）
log "尝试安装: clawhub install $SLUG ..."
if clawhub install "$SLUG" --workdir "$PROJECT_ROOT" --dir skills --no-input >> "$LOG_FILE" 2>&1; then
  log "安装成功: skills/$SLUG"
  touch "$DONE_FILE"
  exit 0
fi

# 可选：尝试从搜索结果取第一个 slug（当前常限流，仅作扩展）
log "本次安装未成功（可能限流或 slug 有误），下次定时再试"
exit 1
