#!/usr/bin/env bash
# 将百度比价工具插件注册到 OpenClaw 网关，使 /tools/invoke 可调用 get_price_comparison 与 search_products。
# 用法: bash scripts/setup_openclaw_baidu_tools.sh
# 会合并配置到 ~/.openclaw/openclaw.json 并提示重启网关。

set -e
OPENCLAW_JSON="${OPENCLAW_JSON:-$HOME/.openclaw/openclaw.json}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_DIR="$PROJECT_ROOT/openclaw_extensions/baidu-price-tools"

if [[ ! -d "$PLUGIN_DIR" ]] || [[ ! -f "$PLUGIN_DIR/openclaw.plugin.json" ]]; then
  echo "错误: 未找到插件目录或 openclaw.plugin.json: $PLUGIN_DIR"
  exit 1
fi

# 备份并合并配置
mkdir -p "$(dirname "$OPENCLAW_JSON")"
if [[ -f "$OPENCLAW_JSON" ]]; then
  cp -a "$OPENCLAW_JSON" "${OPENCLAW_JSON}.bak.$(date +%Y%m%d%H%M%S)"
fi

# 使用 Node 合并 JSON，避免 jq 依赖（通过环境变量传入）；用 var 兼容旧版 Node
# 注意：OpenClaw 官方不识别 plugins["baidu-price-tools"]，只写 plugins.load.paths；projectRoot 通过环境变量 OPENCLAW_BAIDU_PROJECT_ROOT 传递
export OPENCLAW_JSON PROJECT_ROOT PLUGIN_DIR
node -e "
'use strict';
var fs = require('fs');
var path = require('path');
var cfgPath = process.env.OPENCLAW_JSON || path.join(process.env.HOME || '', '.openclaw', 'openclaw.json');
var projectRoot = process.env.PROJECT_ROOT || '';
var pluginDir = process.env.PLUGIN_DIR || '';

var cfg = {};
try {
  var stat = fs.statSync(cfgPath);
  if (stat.isDirectory()) throw new Error('Config path is a directory: ' + cfgPath);
  cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
} catch (e) {
  if (e.code === 'ENOENT') cfg = {};
  else throw e;
}

cfg.plugins = cfg.plugins || {};
cfg.plugins.load = cfg.plugins.load || {};
var paths = Array.isArray(cfg.plugins.load.paths) ? cfg.plugins.load.paths.filter(function(p) { return typeof p === 'string' && p.trim(); }) : [];
if (pluginDir && paths.indexOf(pluginDir) === -1) {
  paths.push(pluginDir);
  cfg.plugins.load.paths = paths;
}
// 不写入 plugins.entries['baidu-price-tools']，避免 id mismatch；仅通过 paths 加载，projectRoot 由环境变量 OPENCLAW_BAIDU_PROJECT_ROOT 传递
if (cfg.plugins.entries && cfg.plugins.entries['baidu-price-tools']) delete cfg.plugins.entries['baidu-price-tools'];

fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2) + '\n');
console.log('已合并配置到', cfgPath);
console.log('  plugins.load.paths 含:', pluginDir);
console.log('  projectRoot 请通过环境变量传递（见下方）');
"

echo ""
echo "启动网关时请设置环境变量 OPENCLAW_BAIDU_PROJECT_ROOT（项目根目录），插件才能调 runner："
echo "  export OPENCLAW_BAIDU_PROJECT_ROOT=\"$PROJECT_ROOT\""
echo "  node \"\$HOME/openclaw/openclaw.mjs\" gateway start"
echo "或先 export 再 install/start。launchd 需在 plist 里配置 EnvironmentVariables。"
echo ""
echo "请重启 OpenClaw 网关使插件生效，例如："
echo "  openclaw gateway restart"
echo "或（launchd）："
echo "  launchctl bootout gui/\$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist"
echo "  launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist"
echo ""
echo "验证："
echo "  curl -sS -X POST http://127.0.0.1:18789/tools/invoke \\"
echo "    -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' \\"
echo "    -d '{\"tool\":\"get_price_comparison\",\"args\":{\"query\":\"伊利宫酪奶皮子酸奶\"}}'"
