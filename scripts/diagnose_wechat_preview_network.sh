#!/usr/bin/env bash
# 诊断「预览 / 上传失败：网络请求错误」常见环境原因（本机 → 微信服务器 HTTPS）
# 用法: bash scripts/diagnose_wechat_preview_network.sh
set -euo pipefail

echo "========== 1) 本机代理（若开启且拦截 HTTPS，会导致预览上传失败）=========="
if command -v networksetup >/dev/null 2>&1; then
  for s in Wi-Fi Ethernet "USB 10/100/1000 LAN"; do
    if networksetup -listallnetworkservices 2>/dev/null | grep -qx "$s" 2>/dev/null; then
      echo "--- 服务: $s ---"
      networksetup -getwebproxy "$s" 2>/dev/null || true
      networksetup -getsecurewebproxy "$s" 2>/dev/null || true
    fi
  done
else
  echo "无 networksetup（非 macOS 可忽略）"
fi

echo ""
echo "========== 2) HTTPS 连通性（超时/失败 = 网络或代理问题，与小程序代码无关）=========="
probe() {
  local url="$1"
  local code
  code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 12 -m 20 "$url" 2>&1 || echo "ERR")
  echo "$url  =>  $code"
}

probe "https://servicewechat.com/"
probe "https://developers.weixin.qq.com/"
probe "https://dldir1.qq.com/"

echo ""
echo "========== 3) 建议（按顺序试）=========="
echo "• 微信开发者工具 → 设置 → 代理设置：改为「不使用任何代理，直连网络」或关闭系统代理后再预览。"
echo "• 暂时关闭 VPN、Charles/Fiddler、公司全局代理；或换手机热点再点「预览」。"
echo "• 等编译完全结束后再点预览（避免与编译任务并发）。"
echo "• 升级微信开发者工具到最新稳定版；仍失败用工具内「反馈与投诉」附带本脚本输出。"
