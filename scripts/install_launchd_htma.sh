#!/bin/bash
# 将好特卖看板 + Cloudflare 隧道安装为 macOS 后台服务，本机不关机即可通过 htma.greatagain.com.cn 一直访问
# 执行: bash scripts/install_launchd_htma.sh
# 有 .tunnel-token 时同时启用隧道；无 token 时只安装看板，创建 token 后执行下方提示命令即可启用隧道

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
KEEPAWAKE_PLIST="com.htma.keepawake.plist"
DASHBOARD_PLIST="com.htma.dashboard.plist"
TUNNEL_PLIST="com.htma.tunnel.plist"
TOKEN_FILE="$PROJECT_ROOT/.tunnel-token"

mkdir -p "$AGENTS"
mkdir -p "$PROJECT_ROOT/logs"

# 确保项目使用 .venv（避免系统 Python 的 externally-managed-environment）
if [ ! -f "$PROJECT_ROOT/.venv/bin/python" ]; then
  echo "未找到 .venv，正在创建并安装依赖..."
  bash "$PROJECT_ROOT/scripts/ensure_venv.sh"
fi

HAS_TOKEN=0
[ -f "$TOKEN_FILE" ] && [ -s "$TOKEN_FILE" ] && HAS_TOKEN=1

# 先卸载旧服务（若存在）
launchctl unload "$AGENTS/$KEEPAWAKE_PLIST" 2>/dev/null || true
launchctl unload "$AGENTS/$DASHBOARD_PLIST" 2>/dev/null || true
launchctl unload "$AGENTS/$TUNNEL_PLIST" 2>/dev/null || true

# 从 .env 读取关键变量并生成 launchd EnvironmentVariables，确保看板与飞书登录在后台能拿到配置
ENV_KEYS="HTMA_PUBLIC_URL FEISHU_APP_ID FEISHU_APP_SECRET FLASK_SECRET_KEY MYSQL_HOST MYSQL_PORT MYSQL_USER MYSQL_PASSWORD MYSQL_DATABASE HTMA_SUPER_ADMIN_OPEN_ID FEISHU_WEBHOOK_URL OPENCLAW_GATEWAY_URL OPENCLAW_GATEWAY_TOKEN"
ENV_XML=""
if [ -f "$PROJECT_ROOT/.env" ]; then
  for k in $ENV_KEYS; do
    v=$(grep -m1 "^${k}=" "$PROJECT_ROOT/.env" 2>/dev/null | sed "s/^${k}=//" | tr -d '\r' | sed 's/^["'\'']//;s/["'\'']$//')
    [ -z "$v" ] && continue
    v_escaped=$(echo "$v" | sed 's/&/\&amp;/g;s/</\&lt;/g;s/>/\&gt;/g;s/"/\&quot;/g')
    ENV_XML="${ENV_XML}    <key>${k}</key>\n    <string>${v_escaped}</string>\n"
  done
fi
# 百度 Skill 比价：若 .env 未配置 OPENCLAW_GATEWAY_TOKEN，从 ~/.openclaw/openclaw.json 读取并注入
if ! echo "$ENV_XML" | grep -q "OPENCLAW_GATEWAY_TOKEN"; then
  OPENCLAW_JSON="$HOME/.openclaw/openclaw.json"
  if [ -f "$OPENCLAW_JSON" ]; then
    TOKEN=$(python3 -c "import json; print(json.load(open('$OPENCLAW_JSON')).get('gateway',{}).get('auth',{}).get('token',''))" 2>/dev/null)
    if [ -n "$TOKEN" ]; then
      TOKEN_ESC=$(echo "$TOKEN" | sed 's/&/\&amp;/g;s/</\&lt;/g;s/>/\&gt;/g;s/"/\&quot;/g')
      ENV_XML="${ENV_XML}    <key>OPENCLAW_GATEWAY_TOKEN</key>\n    <string>${TOKEN_ESC}</string>\n"
    fi
  fi
fi
if ! echo "$ENV_XML" | grep -q "OPENCLAW_GATEWAY_URL"; then
  ENV_XML="${ENV_XML}    <key>OPENCLAW_GATEWAY_URL</key>\n    <string>http://127.0.0.1:18789</string>\n"
fi
# 注入 PATH 便于看板进程调起 clawhub/openclaw（百度 Skill 比价）
PNPM_BIN="$HOME/Library/pnpm"
NPM_BIN="$HOME/.npm-global/bin"
PATH_VAL="/usr/local/bin:/usr/bin:/bin"
[ -d "$PNPM_BIN" ] && PATH_VAL="$PNPM_BIN:$PATH_VAL"
[ -d "$NPM_BIN" ] && PATH_VAL="$NPM_BIN:$PATH_VAL"
PATH_ESC=$(echo "$PATH_VAL" | sed 's/&/\&amp;/g;s/</\&lt;/g;s/>/\&gt;/g;s/"/\&quot;/g')
ENV_XML="${ENV_XML}    <key>PATH</key>\n    <string>${PATH_ESC}</string>\n"
if [ -n "$ENV_XML" ]; then
  ENV_BLOCK="  <key>EnvironmentVariables</key>\n  <dict>\n${ENV_XML}  </dict>"
else
  ENV_BLOCK=""
fi

# 防睡眠服务（锁屏/息屏后本机不睡眠，OpenClaw 网关与看板/隧道可继续运行）
# 日志写到 /tmp，避免项目在外置卷时 launchd 无法写入导致退出码 78
cat > "$AGENTS/$KEEPAWAKE_PLIST" << KEEPAWAKEEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.keepawake</string>
  <key>ProcessType</key>
  <string>Background</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-s</string>
    <string>-i</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/com.htma.keepawake.out.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/com.htma.keepawake.err.log</string>
</dict>
</plist>
KEEPAWAKEEOF

# 看板服务（用 caffeinate 防睡眠；注入 .env 关键变量保证飞书与公网域名可用）
cat > "$AGENTS/$DASHBOARD_PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.dashboard</string>
  <key>ProcessType</key>
  <string>Background</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-s</string>
    <string>-i</string>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>sleep 5 &amp;&amp; exec /bin/bash $PROJECT_ROOT/scripts/start_htma.sh</string>
  </array>
$(echo -e "$ENV_BLOCK")
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/dashboard.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/dashboard.err.log</string>
</dict>
</plist>
PLISTEOF

# 隧道服务（锁屏后继续运行，保证 htma.greatagain.com.cn 可访问）
# 项目在外置卷时 launchd 无法读项目路径，改为从 HOME 运行并读 ~/.htma-tunnel-token
if [[ "$PROJECT_ROOT" == /Volumes/* ]] && [ "$HAS_TOKEN" = "1" ]; then
  cp "$TOKEN_FILE" "$HOME/.htma-tunnel-token" 2>/dev/null || true
  if [ -f "$HOME/.htma-tunnel-token" ] && [ -s "$HOME/.htma-tunnel-token" ]; then
    cat > "$HOME/.htma-tunnel-run.sh" << 'TUNNELRUN'
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
TOKEN=$(cat "$HOME/.htma-tunnel-token" 2>/dev/null | tr -d '\n\r ')
[ -z "$TOKEN" ] && echo "~/.htma-tunnel-token 为空" >&2 && exit 1
for i in 1 2 3 4 5 6 7 8 9 10; do lsof -i :5002 >/dev/null 2>&1 && break; sleep 1; done
exec /usr/bin/caffeinate -s -i -- cloudflared tunnel run --token "$TOKEN"
TUNNELRUN
    chmod +x "$HOME/.htma-tunnel-run.sh"
    cat > "$AGENTS/$TUNNEL_PLIST" << TUNNELPREF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.tunnel</string>
  <key>ProcessType</key>
  <string>Background</string>
  <key>WorkingDirectory</key>
  <string>$HOME</string>
  <key>ProgramArguments</key>
  <array>
    <string>$HOME/.htma-tunnel-run.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/com.htma.tunnel.out.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/com.htma.tunnel.err.log</string>
</dict>
</plist>
TUNNELPREF
  else
    HAS_TOKEN=0
    cat > "$AGENTS/$TUNNEL_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.tunnel</string>
  <key>ProcessType</key>
  <string>Background</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-s</string>
    <string>-i</string>
    <string>/bin/bash</string>
    <string>$PROJECT_ROOT/scripts/run_tunnel_forever.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/tunnel.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/tunnel.err.log</string>
</dict>
</plist>
EOF
  fi
else
  cat > "$AGENTS/$TUNNEL_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.htma.tunnel</string>
  <key>ProcessType</key>
  <string>Background</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-s</string>
    <string>-i</string>
    <string>/bin/bash</string>
    <string>$PROJECT_ROOT/scripts/run_tunnel_forever.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/tunnel.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/tunnel.err.log</string>
</dict>
</plist>
EOF
fi

mkdir -p "$PROJECT_ROOT/logs"

# 项目在外置卷（/Volumes/...）时，launchd 子进程可能无法访问该卷，导致看板退出码 78 或 "Operation not permitted"
if [[ "$PROJECT_ROOT" == /Volumes/* ]]; then
  echo "提示：当前项目在外置卷 ($PROJECT_ROOT)，launchd 可能无法访问，看板服务可能显示退出码 78。"
  echo "  若看板无法自启，请：① 将项目复制到本机卷（如 ~/hotmaxxflag）再执行本脚本；或 ② 改用手动启动：cd 项目根 && .venv/bin/python htma_dashboard/app.py"
  echo ""
fi

# 先加载防睡眠（锁屏后本机定时任务与看板/隧道照常运行），再加载看板与隧道
launchctl load "$AGENTS/$KEEPAWAKE_PLIST"
launchctl load "$AGENTS/$DASHBOARD_PLIST"
if [ "$HAS_TOKEN" = "1" ]; then
  launchctl load "$AGENTS/$TUNNEL_PLIST"
  echo "已安装并启动：防睡眠 + 看板 + 隧道（锁屏/息屏后本机功能正常执行、外网可访问）。"
  echo "  防睡眠: com.htma.keepawake（阻止系统睡眠）"
  echo "  看板:   com.htma.dashboard  → http://127.0.0.1:5002"
  echo "  隧道:   com.htma.tunnel     → https://htma.greatagain.com.cn"
else
  echo "已安装并启动：防睡眠 + 看板（隧道未启用：未找到 .tunnel-token）。"
  echo "  防睡眠: com.htma.keepawake（锁屏后定时任务与看板照常运行）"
  echo "  看板:   com.htma.dashboard  → http://127.0.0.1:5002"
  echo ""
  echo "要启用外网访问 https://htma.greatagain.com.cn，请："
  echo "  1. 创建文件 .tunnel-token（在项目根目录），内容为一行 Cloudflare 隧道 Token（从 one.dash.cloudflare.com 复制）"
  echo "  2. 执行: launchctl load $AGENTS/$TUNNEL_PLIST"
  echo "  或重新执行: bash scripts/install_launchd_htma.sh"
fi
echo "日志: $PROJECT_ROOT/logs/"
echo ""
echo "常用命令："
echo "  查看状态: launchctl list | grep com.htma"
echo "  停止隧道: launchctl unload $AGENTS/$TUNNEL_PLIST"
echo "  停止看板: launchctl unload $AGENTS/$DASHBOARD_PLIST"
echo "  停止防睡眠: launchctl unload $AGENTS/$KEEPAWAKE_PLIST"
echo "             （停止防睡眠后，锁屏时系统可能进入睡眠）"
echo "  再次启动: launchctl load $AGENTS/$KEEPAWAKE_PLIST && launchctl load $AGENTS/$DASHBOARD_PLIST && launchctl load $AGENTS/$TUNNEL_PLIST"
