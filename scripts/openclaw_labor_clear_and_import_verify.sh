#!/usr/bin/env bash
# OpenClaw 自动化：人力成本数据清空、从下载目录重新导入、并与汇总表校验。
# 用法: bash scripts/openclaw_labor_clear_and_import_verify.sh [下载目录]
#       bash scripts/openclaw_labor_clear_and_import_verify.sh [下载目录] analyze  # 先分析表格构成再导入
# 默认下载目录: IMPORT_DOWNLOADS_DIR 或 ~/Downloads
# 会按 2026-01(1月)、2025-12(12月) 在目录中查找 *1月*.xlsx、*12月*.xlsx 并导入；
# 校验通过退出 0，否则退出 1。
set -e
cd "$(dirname "$0")/.."
DIR="${1:-}"
DO_ANALYZE=""
[ "${2:-}" = "analyze" ] && DO_ANALYZE="analyze"
[ "$DIR" = "analyze" ] && DO_ANALYZE="analyze" && DIR=""
PYTHON="${PYTHON:-.venv/bin/python}"
DOWNLOAD_DIR="${DIR:-$HOME/Downloads}"
if [ "$DO_ANALYZE" = "analyze" ]; then
  echo "=============================================="
  echo "人力成本：先分析 Excel 表格构成（斗米兼职/中锐/快聘/保洁）"
  echo "=============================================="
  for f in "$DOWNLOAD_DIR/"*12月*.xlsx "$DOWNLOAD_DIR/"*1月*.xlsx; do
    [ -f "$f" ] && "$PYTHON" scripts/openclaw_labor_analyze_excel.py "$f" || true
  done
  echo ""
fi
echo "=============================================="
echo "人力成本：清空 → 重新导入 → 校验"
echo "=============================================="
if [ -n "$DIR" ]; then
  "$PYTHON" scripts/openclaw_labor_import_from_downloads.py --clear 2026-01 2025-12 --dir "$DIR"
else
  "$PYTHON" scripts/openclaw_labor_import_from_downloads.py --clear 2026-01 2025-12
fi
IMPORT_EXIT=$?
echo ""
"$PYTHON" scripts/openclaw_labor_selfcheck.py
exit $IMPORT_EXIT
