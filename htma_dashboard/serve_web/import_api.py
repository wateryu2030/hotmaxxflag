# -*- coding: utf-8 -*-
"""serve_web/import_api：数据导入 API（从下载目录导入、预览 Excel 结构）"""

from flask import Blueprint, jsonify, request
import os, json

from core.db import get_conn

import_api_bp = Blueprint("import_api", __name__)


def _import_downloads_directory():
    """服务端「从下载目录导入」使用的目录。"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.environ.get("IMPORT_DOWNLOADS_DIR") or os.path.join(root, "downloads")


def _find_excel_files_in_dir(directory):
    """在指定目录查找销售日报、销售汇总、实时库存、分店商品档案，返回路径字典。"""
    if not directory or not os.path.isdir(directory):
        return {}
    files = {}
    for f in os.listdir(directory):
        if f.startswith(".") or f.startswith("~"):
            continue
        path = os.path.join(directory, f)
        if not os.path.isfile(path):
            continue
        low = f.lower()
        if "销售日报" in f and "品项" not in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "sale_daily" not in files or os.path.getmtime(path) > os.path.getmtime(files["sale_daily"]):
                files["sale_daily"] = path
        elif "销售汇总" in f and "品项" not in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "sale_summary" not in files or os.path.getmtime(path) > os.path.getmtime(files["sale_summary"]):
                files["sale_summary"] = path
        elif ("实时库存" in f or "库存查询" in f) and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "stock" not in files or os.path.getmtime(path) > os.path.getmtime(files["stock"]):
                files["stock"] = path
        elif "分店商品档案" in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "product_master" not in files or os.path.getmtime(path) > os.path.getmtime(files["product_master"]):
                files["product_master"] = path
    return files

def _import_downloads_directory():
    """服务端「从下载目录导入」使用的目录：环境变量 IMPORT_DOWNLOADS_DIR 或 项目/downloads"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.environ.get("IMPORT_DOWNLOADS_DIR") or os.path.join(root, "downloads")


def _find_excel_files_in_dir(directory):
    """在指定目录查找销售日报、销售汇总、实时库存/库存查询、分店商品档案（取最新），返回 {sale_daily?, sale_summary?, stock?, product_master?} 路径"""
    if not directory or not os.path.isdir(directory):
        return {}
    files = {}
    for f in os.listdir(directory):
        if f.startswith(".") or f.startswith("~"):
            continue
        path = os.path.join(directory, f)
        if not os.path.isfile(path):
            continue
        low = f.lower()
        if "销售日报" in f and "品项" not in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "sale_daily" not in files or os.path.getmtime(path) > os.path.getmtime(files["sale_daily"]):
                files["sale_daily"] = path
        elif "销售汇总" in f and "品项" not in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "sale_summary" not in files or os.path.getmtime(path) > os.path.getmtime(files["sale_summary"]):
                files["sale_summary"] = path
        elif ("实时库存" in f or "库存查询" in f) and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "stock" not in files or os.path.getmtime(path) > os.path.getmtime(files["stock"]):
                files["stock"] = path
        elif "分店商品档案" in f and (low.endswith(".xls") or low.endswith(".xlsx")):
            if "product_master" not in files or os.path.getmtime(path) > os.path.getmtime(files["product_master"]):
                files["product_master"] = path
    return files

@import_api_bp.route("/api/import_from_downloads", methods=["POST", "OPTIONS"])
def api_import_from_downloads():
    """从配置的下载目录自动导入销售日报/销售汇总/库存/商品档案，并执行去重与刷新。仅处理上述表，不触碰人力成本表。"""
    if request.method == "OPTIONS":
        return "", 204
    directory = _import_downloads_directory()
    try:
        os.makedirs(directory, exist_ok=True)
    except Exception as e:
        return jsonify({"success": False, "message": f"下载目录不可用: {e}", "directory": directory}), 400
    files = _find_excel_files_in_dir(directory)
    if not files:
        return jsonify({
            "success": False,
            "message": "未在下载目录找到销售日报/销售汇总/实时库存/分店商品档案 Excel",
            "directory": directory,
            "hint": "该目录为服务器上的路径。请将 Excel 放入服务器该目录后重试，或使用本页「上传」按钮直接上传文件。",
        }), 400

    conn = None
    result = {"sale_daily": 0, "sale_summary": 0, "stock": 0, "product_master": 0, "profit_refreshed": 0, "errors": [], "from_downloads": True, "directory": directory}
    try:
        conn = get_conn()
        _ensure_product_master_distribution_mode(conn)
        cur = conn.cursor()
        has_sale_daily = "sale_daily" in files
        has_sale_summary = "sale_summary" in files
        if has_sale_daily:
            cnt, diag = import_sale_daily(files["sale_daily"], conn)
            result["sale_daily"] = cnt
            if diag:
                result.setdefault("diagnostics", []).append(diag)
        if has_sale_summary:
            cnt, diag = import_sale_summary(files["sale_summary"], conn, overwrite_on_duplicate=True)
            result["sale_summary"] = cnt
            if diag:
                result.setdefault("diagnostics", []).append(diag)
        if "stock" in files:
            cnt, diag = import_stock(files["stock"], conn)
            result["stock"] = cnt
            if diag:
                result.setdefault("diagnostics", []).append(diag)
        if "product_master" in files:
            try:
                cnt, diag = import_product_master(files["product_master"], conn)
                result["product_master"] = cnt
                if diag:
                    result.setdefault("diagnostics", []).append("商品档案: " + str(diag))
            except Exception as e:
                result["errors"].append("分店商品档案导入: " + str(e))

        if result["sale_daily"] > 0 or result["sale_summary"] > 0:
            result["profit_refreshed"] = refresh_profit(conn)
            try:
                result["category_refreshed"] = refresh_category_from_sale(conn)
            except Exception as e:
                result["errors"].append(f"品类表刷新: {str(e)}")
            try:
                result["products_synced"] = sync_products_table(conn, store_id=STORE_ID)
            except Exception as e:
                result["errors"].append(f"商品表同步: {str(e)}")
            try:
                result["category_synced"] = sync_category_table(conn, store_id=STORE_ID)
            except Exception as e:
                result["errors"].append(f"品类表同步: {str(e)}")

        conn.commit()
        conn.close()
        conn = None

        # 去重：合并同主键重复行
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        run_dedup_sh = os.path.join(project_root, "scripts", "run_dedup.sh")
        if os.path.isfile(run_dedup_sh):
            try:
                subprocess.run(["/bin/bash", run_dedup_sh], cwd=project_root, check=True, timeout=300, capture_output=True)
                result["dedup_done"] = True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                result["dedup_done"] = False
                result.setdefault("diagnostics", []).append(f"去重: {e}")

        # 统计
        conn2 = get_conn()
        cur = conn2.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM t_htma_sale")
        row = cur.fetchone()
        result["sale_total"] = row["c"] if isinstance(row, dict) else row[0]
        try:
            cur.execute("SELECT COALESCE(SUM(sale_amount), 0) AS v FROM t_htma_sale")
            row = cur.fetchone()
            result["sale_total_amount"] = round(float(row.get("v", 0) or 0 if isinstance(row, dict) else (row[0] or 0)), 2)
        except Exception:
            result["sale_total_amount"] = 0.0
        cur.execute("SELECT COUNT(*) AS c FROM t_htma_stock")
        row = cur.fetchone()
        result["stock_total"] = row["c"] if isinstance(row, dict) else row[0]
        try:
            cur.execute("""
                SELECT COALESCE(SUM(stock_amount), 0) AS v FROM t_htma_stock
                WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
            """, (STORE_ID, STORE_ID))
            row = cur.fetchone()
            result["stock_total_amount"] = round(float(row.get("v", 0) or 0 if isinstance(row, dict) else (row[0] or 0)), 2)
        except Exception:
            result["stock_total_amount"] = 0.0
        cur.execute("SELECT COUNT(*) AS c FROM t_htma_profit")
        row = cur.fetchone()
        result["profit_total"] = row["c"] if isinstance(row, dict) else row[0]
        cur.execute("SELECT MIN(data_date) AS min_d, MAX(data_date) AS max_d FROM t_htma_sale")
        dr = cur.fetchone()
        if dr and (dr.get("min_d") if isinstance(dr, dict) else dr[0]):
            result["date_range"] = f"{dr.get('min_d')} ~ {dr.get('max_d')}" if isinstance(dr, dict) else f"{dr[0]} ~ {dr[1]}"
        else:
            result["date_range"] = "-"
        try:
            cur.execute("SELECT COUNT(*) AS c FROM t_htma_product_master")
            row = cur.fetchone()
            result["product_master_total"] = row.get("c", 0) if isinstance(row, dict) else (row[0] if row else 0)
        except Exception:
            result["product_master_total"] = 0
        conn2.close()

        result["success"] = True
        result["data_import_target"] = "server"
        if result.get("sale_total", 0) > 0 or result.get("stock_total", 0) > 0 or result.get("product_master_total", 0) > 0:
            msg = f"好特卖数据导入完成（下载目录）\n销售表: {result.get('sale_total', 0)} 条\n库存表: {result.get('stock_total', 0)} 条\n毛利表: {result.get('profit_total', 0)} 条\n日期范围: {result.get('date_range', '-')}"
            if result.get("product_master_total", 0) > 0:
                msg += f"\n商品档案表: {result.get('product_master_total', 0)} 条"
            try:
                from feishu_util import send_feishu
                send_feishu(msg, at_user_id="ou_8db735f2", at_user_name="余为军", title="好特卖数据导入完成")
            except Exception:
                _notify_feishu(msg)
        return jsonify(result)
    except Exception as e:
        import traceback
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return jsonify({
            "success": False,
            "message": str(e),
            "data_import_target": "server",
            "from_downloads": True,
            "directory": directory,
            "traceback": traceback.format_exc()[-2000:],
        }), 500
@import_api_bp.route("/api/import_preview", methods=["POST"])
def api_import_preview():
    """预览销售 Excel 结构，用于调试导入问题"""
    try:
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "请上传文件"}), 400
        file = request.files["file"]
        if not file or file.filename == "":
            return jsonify({"ok": False, "error": "未选择文件"}), 400
        if not (file.filename.lower().endswith(".xls") or file.filename.lower().endswith(".xlsx")):
            return jsonify({"ok": False, "error": "仅支持 .xls / .xlsx"}), 400
        is_summary = request.form.get("type") == "sale_summary"
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            file.save(tmp.name)
            try:
                out = preview_sale_excel(tmp.name, is_summary=is_summary)
                return jsonify(out)
            finally:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()}), 500






