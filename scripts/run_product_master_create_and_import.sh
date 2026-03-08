#!/usr/bin/env bash
# 手工建表并（可选）从下载目录导入分店商品档案。与数据导入、人力成本同级，供 OpenClaw 或运维执行。
# 用法:
#   bash scripts/run_product_master_create_and_import.sh              # 仅建表
#   bash scripts/run_product_master_create_and_import.sh --import      # 建表 + 从 ~/Downloads 导入
set -e
cd "$(dirname "$0")/.."
SCRIPT_DIR="$(pwd)"
MYSQL_OPTS="${MYSQL_OPTS:--h 127.0.0.1 -u root -p}"
DB_NAME="${HTMA_DB:-htma_dashboard}"

echo "=== 分店商品档案：建表 ==="
mysql $MYSQL_OPTS "$DB_NAME" < scripts/19_create_product_master_table.sql
echo "表 t_htma_product_master 已创建/重建。"

if [[ "${1:-}" == "--import" ]]; then
  echo ""
  echo "=== 从下载目录导入 ==="
  python3 scripts/openclaw_product_master_import_from_downloads.py --dir "${IMPORT_DOWNLOADS_DIR:-$HOME/Downloads}"
fi
echo ""
echo "完成。可访问 /product_master 查看分析（需具备商品档案权限）。"
