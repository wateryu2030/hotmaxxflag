#!/bin/bash
# 双击运行：仅启动看板（终端方式，不依赖 Docker）
# 关闭本窗口即停止看板

cd /Volumes/ragflow/hotmaxx/hotmaxxflag || { echo "项目目录不存在"; read -p "按 Enter 关闭..."; exit 1; }

# 若 5002 被占用则先释放（可能是上次未关或 Docker）
pid=$(lsof -ti :5002 2>/dev/null)
if [ -n "$pid" ]; then
  echo "正在释放端口 5002（进程 $pid）..."
  kill -9 $pid 2>/dev/null
  sleep 1
fi

echo "正在启动好特卖看板（本机访问 http://127.0.0.1:5002）..."
echo "关闭本窗口将停止看板。"
echo ""
bash scripts/start_htma.sh

echo ""
read -p "按 Enter 关闭窗口..."
