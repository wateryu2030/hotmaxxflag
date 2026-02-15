#!/usr/bin/env bash
# ============================================================
# 好特卖沈阳超级仓运营看板 - 一键部署（供 OpenClaw / 终端执行）
# 执行：./scripts/openclaw_deploy_htma_dashboard.sh
# 独立版：./scripts/openclaw_deploy_htma_dashboard.sh --standalone
# ============================================================

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"
MYSQL_OPTS="-h 127.0.0.1 -u root -p62102218"
JR_DIR="$PROJECT_ROOT/JimuReport/jimureport-example"
STANDALONE=0
[[ "$1" =~ ^(-s|--standalone)$ ]] && STANDALONE=1

echo "=========================================="
echo "好特卖运营看板 - 一键部署"
echo "=========================================="

# 独立版：仅启动 Flask 看板（端口 5002），不依赖 JimuReport
if [ "$STANDALONE" = "1" ]; then
  echo ""
  echo "[独立版] 启动 Flask 看板（端口 5002）..."
  source "$PROJECT_ROOT/.venv/bin/activate" 2>/dev/null || python3 -m venv "$PROJECT_ROOT/.venv" && source "$PROJECT_ROOT/.venv/bin/activate"
  pip install -q -r "$PROJECT_ROOT/htma_dashboard/requirements.txt" 2>/dev/null || true
  pkill -f "htma_dashboard/app.py" 2>/dev/null || true
  sleep 2
  cd "$PROJECT_ROOT/htma_dashboard" && nohup python app.py > /tmp/htma_dashboard.log 2>&1 &
  sleep 3
  if curl -s "http://127.0.0.1:5002/api/health" 2>/dev/null | grep -q '"status"'; then
    echo "  ✓ 看板已启动"
    echo ""
    echo "访问: http://127.0.0.1:5002"
    [[ "$2" =~ ^(-o|--open)$ ]] && open "http://127.0.0.1:5002" 2>/dev/null || true
  else
    echo "  ✗ 启动失败，请检查 MySQL 与 Python 环境"
    exit 1
  fi
  exit 0
fi

# 1. 部署 SQL（数据源 + 数据集 + 看板）
echo ""
echo "[1/4] 执行 SQL 部署..."
mysql $MYSQL_OPTS jimureport < "$PROJECT_ROOT/scripts/add_htma_dashboard_plan_a.sql" 2>/dev/null || {
  echo "  MySQL 连接失败，请确认 MySQL 已启动且密码正确"
  exit 1
}

# 2. 修复 jmsheet 所需字段
echo ""
echo "[2/4] 执行 jmsheet 修复..."
mysql $MYSQL_OPTS jimureport < "$PROJECT_ROOT/scripts/fix_htma_dashboard_jmsheet.sql" 2>/dev/null

# 3. 编译 JimuReport（含 Controller 兜底）
echo ""
echo "[3/4] 编译 JimuReport..."
(cd "$JR_DIR" && mvn compile -q -DskipTests 2>/dev/null) || {
  echo "  编译失败，请检查 Maven 环境"
  exit 1
}

# 4. 检测 JimuReport 是否运行，验证 show API
echo ""
echo "[4/4] 验证 show API..."
RESP=$(curl -s "http://127.0.0.1:8085/jmreport/show?id=htma_dash_shenyang_001" 2>/dev/null || echo "")
if echo "$RESP" | grep -q '"success":true'; then
  echo "  ✓ show API 正常"
  DASHBOARD_OK=1
elif echo "$RESP" | grep -q '"success":false'; then
  echo "  ✗ show API 返回错误，需重启 JimuReport 使 Controller 生效"
  echo "    执行: cd $JR_DIR && mvn spring-boot:run"
  DASHBOARD_OK=0
else
  echo "  ! JimuReport 未运行或无法连接"
  echo "    请先启动: cd $JR_DIR && mvn spring-boot:run"
  DASHBOARD_OK=0
fi

echo ""
echo "=========================================="
echo "部署完成"
echo "=========================================="
echo "访问地址: http://127.0.0.1:8085/jmreport/view/htma_dash_shenyang_001"
echo ""
if [ "$DASHBOARD_OK" = "0" ]; then
  echo "提示: 若 show API 报错，请重启 JimuReport 后刷新页面"
  echo "  cd $JR_DIR && mvn spring-boot:run"
fi
echo ""

# 5. 可选：打开浏览器（--open 或 -o 时自动打开，非交互模式适用 OpenClaw）
if [[ "$1" =~ ^(-o|--open)$ ]]; then
  if command -v open &>/dev/null; then
    open "http://127.0.0.1:8085/jmreport/view/htma_dash_shenyang_001"
    echo "已打开浏览器"
  fi
elif command -v open &>/dev/null && [ -t 0 ]; then
  read -p "是否打开浏览器? [y/N] " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    open "http://127.0.0.1:8085/jmreport/view/htma_dash_shenyang_001"
  fi
fi
