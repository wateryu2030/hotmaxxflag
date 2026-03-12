#!/bin/bash
# 反复重试克隆 openclaw 仓库（解决网络超时）
# 用法：bash scripts/clone_openclaw_retry.sh
# 可选：OPENCLAW_SRC=/path/to/dir MAX_TRY=10 bash scripts/clone_openclaw_retry.sh
TARGET="${OPENCLAW_SRC:-$HOME/openclaw}"
MAX_TRY="${MAX_TRY:-8}"
GIT_OPTS="--depth 1 --progress"

echo "目标目录: $TARGET"
echo "最多重试: $MAX_TRY 次"
echo ""

# 若已存在且含 package.json 则跳过
if [ -f "$TARGET/package.json" ]; then
  echo "已存在有效源码: $TARGET，跳过克隆。"
  exit 0
fi
rm -rf "$TARGET" 2>/dev/null || true
mkdir -p "$(dirname "$TARGET")"

# 降低 git 对慢速/断线的敏感度（单位：字节/秒 与 秒）
export GIT_HTTP_LOW_SPEED_LIMIT=1000
export GIT_HTTP_LOW_SPEED_TIME=120
export GIT_TERMINAL_PROMPT=0

for i in $(seq 1 "$MAX_TRY"); do
  echo "======== 第 $i / $MAX_TRY 次尝试 =========="
  # 1) 若已安装 gh，先试 gh
  if command -v gh &>/dev/null; then
    if gh repo clone openclaw/openclaw "$TARGET" -- --depth 1 2>&1; then
      echo "克隆成功（gh）。"
      exit 0
    fi
    rm -rf "$TARGET" 2>/dev/null || true
  fi
  # 2) git HTTPS
  if git clone $GIT_OPTS https://github.com/openclaw/openclaw.git "$TARGET" 2>&1; then
    echo "克隆成功（git HTTPS）。"
    exit 0
  fi
  rm -rf "$TARGET" 2>/dev/null || true
  if [ "$i" -lt "$MAX_TRY" ]; then
    wait_sec=$((15 + i * 5))
    echo "未成功，${wait_sec}s 后重试..."
    sleep "$wait_sec"
  fi
done

echo "已达最大重试次数，克隆失败。可手动："
echo "  gh repo clone openclaw/openclaw $TARGET"
echo "或浏览器打开 https://github.com/openclaw/openclaw 点 Code -> Download ZIP，解压到 $TARGET"
exit 1
