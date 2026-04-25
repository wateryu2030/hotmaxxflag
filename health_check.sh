#!/bin/bash
# 检查进程是否运行
if ps aux | grep -q "启动好特卖看板.command"; then
    echo "✅ hotmaxxflag运行正常"
    exit 0
else
    echo "❌ hotmaxxflag未运行"
    exit 1
fi
