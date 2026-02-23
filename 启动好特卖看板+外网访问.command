#!/bin/bash
# 双击运行：启动看板 + 外网隧道（Cloudflare）
# 关闭本窗口会同时停止看板与隧道；外网用终端里显示的 https://xxx.trycloudflare.com 访问

cd /Volumes/ragflow/hotmaxx/hotmaxxflag || { echo "项目目录不存在"; read -p "按 Enter 关闭..."; exit 1; }

bash scripts/start_htma_with_tunnel.sh

echo ""
read -p "按 Enter 关闭窗口..."
