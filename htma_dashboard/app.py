#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
好特卖沈阳超级仓运营看板 - 独立版（不依赖 JimuReport）
直接读取 MySQL htma_dashboard，提供 API 与看板页面。
"""
import os
import tempfile
import pymysql
from flask import Flask, jsonify, send_from_directory, request
from werkzeug.utils import secure_filename

from import_logic import import_sale_daily, import_sale_summary, import_stock, import_category, import_profit, refresh_profit, refresh_category_from_sale, preview_sale_excel
from analytics import build_insights, category_rank_data

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB，避免大 Excel 413


@app.after_request
def add_cors_headers(response):
    """允许跨域，便于 Cursor 预览、OpenClaw 等不同源访问"""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/api/<path:path>", methods=["OPTIONS"])
def api_options(path):
    """CORS 预检"""
    return "", 204


@app.errorhandler(404)
@app.errorhandler(500)
@app.errorhandler(413)
def json_error(e):
    """API 请求返回 JSON；未知路径返回 404 避免 500；413 返回文件过大提示"""
    if request.path.startswith("/api/"):
        code = getattr(e, "code", 500)
        msg = str(e)
        if code == 413:
            msg = "文件过大，请上传小于 200MB 的 Excel 文件"
        return jsonify({"success": False, "message": msg}), code
    code = getattr(e, "code", 500)
    if code == 404:
        return "Not Found", 404
    raise

# MySQL 配置（与 JimuReport 一致）
DB_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", "62102218"),
    "database": "htma_dashboard",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

STORE_ID = "沈阳超级仓"
DEFAULT_DAYS = 30
FEISHU_WEBHOOK = os.environ.get(
    "FEISHU_WEBHOOK_URL",
    "https://open.feishu.cn/open-apis/bot/v2/hook/1b21bad3-22cb-4d9d-8f38-32526bd69d49",
)


def _notify_feishu(text):
    """发送飞书通知（异步，不阻塞主流程）"""
    if not FEISHU_WEBHOOK or not text:
        return
    try:
        import urllib.request
        import json
        req = urllib.request.Request(
            FEISHU_WEBHOOK,
            data=json.dumps({"msg_type": "text", "content": {"text": text}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # 静默失败，不影响导入


def get_conn():
    return pymysql.connect(**DB_CONFIG)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/undefined")
def catch_undefined():
    """拦截 href=undefined 等错误请求"""
    return "", 204


@app.route("/.well-known/<path:_>")
def catch_well_known(_):
    """拦截 Chrome 扩展等对 .well-known 的请求"""
    return "", 204


@app.route("/import")
def import_page():
    return send_from_directory("static", "import.html")


@app.route("/api/import", methods=["POST"])
def api_import():
    """上传 Excel，覆盖式导入 MySQL。preview_only=1 时仅预览销售表结构，不导入"""
    preview_only = request.form.get("preview_only", "").strip() in ("1", "true", "yes")
    if preview_only:
        for key in ("sale_daily", "sale_summary"):
            if key in request.files and request.files[key] and request.files[key].filename:
                file = request.files[key]
                if file.filename.lower().endswith((".xls", ".xlsx")):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
                        file.save(tmp.name)
                        try:
                            out = preview_sale_excel(tmp.name, is_summary=(key == "sale_summary"))
                            return jsonify({"success": True, "preview": out})
                        finally:
                            try:
                                os.unlink(tmp.name)
                            except Exception:
                                pass
                return jsonify({"success": False, "error": "仅支持 .xls / .xlsx"}), 400
        return jsonify({"success": False, "error": "请选择销售日报或销售汇总文件"}), 400

    if "sale_daily" not in request.files and "sale_summary" not in request.files and "stock" not in request.files and "category" not in request.files and "profit" not in request.files:
        return jsonify({"success": False, "message": "请至少上传一个 Excel 文件"}), 400

    conn = None
    result = {"sale_daily": 0, "sale_summary": 0, "stock": 0, "category": 0, "profit": 0, "profit_refreshed": 0, "errors": []}

    try:
        conn = get_conn()
        cur = conn.cursor()

        # 仅当有合法 Excel 文件时才清空表（避免无效文件导致误清空）
        def _has_valid_file(keys):
            for k in keys:
                f = request.files.get(k)
                if f and f.filename and (f.filename.lower().endswith(".xls") or f.filename.lower().endswith(".xlsx")):
                    return True
            return False

        # 销售类：先清空再导入
        if _has_valid_file(["sale_daily", "sale_summary"]):
            cur.execute("TRUNCATE TABLE t_htma_sale")
            cur.execute("TRUNCATE TABLE t_htma_profit")
            conn.commit()

        # 库存类：先清空再导入
        if _has_valid_file(["stock"]):
            cur.execute("TRUNCATE TABLE t_htma_stock")
            conn.commit()

        # 毛利汇总 Excel：先清空再导入（与销售汇总刷新二选一）
        if _has_valid_file(["profit"]):
            cur.execute("TRUNCATE TABLE t_htma_profit")
            conn.commit()

        # 品类附表：import_category 内部会 TRUNCATE
        # 毛利列映射：swap=对调, amount_as_total=金额已是总金额, cost_as_total=进价已是总成本
        swap = request.form.get("swap_amount_cost", "").strip().lower() in ("1", "true", "yes")
        amount_total = request.form.get("amount_as_total", "").strip().lower() in ("1", "true", "yes")
        cost_total = request.form.get("cost_as_total", "").strip().lower() in ("1", "true", "yes")
        _orig_swap = os.environ.get("HTMA_SWAP_AMOUNT_COST")
        _orig_amt = os.environ.get("HTMA_AMOUNT_AS_TOTAL")
        _orig_cost = os.environ.get("HTMA_COST_AS_TOTAL")
        if swap:
            os.environ["HTMA_SWAP_AMOUNT_COST"] = "1"
        if amount_total:
            os.environ["HTMA_AMOUNT_AS_TOTAL"] = "1"
        if cost_total:
            os.environ["HTMA_COST_AS_TOTAL"] = "1"
        try:
            for key, file in request.files.items():
                if not file or file.filename == "":
                    continue
                if not (file.filename.lower().endswith(".xls") or file.filename.lower().endswith(".xlsx")):
                    result["errors"].append(f"{key}: 仅支持 .xls / .xlsx")
                    continue
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
                    file.save(tmp.name)
                    try:
                        if key == "sale_daily":
                            cnt, diag = import_sale_daily(tmp.name, conn)
                            result["sale_daily"] = cnt
                            if diag:
                                result.setdefault("diagnostics", []).append(diag)
                        elif key == "sale_summary":
                            cnt, diag = import_sale_summary(tmp.name, conn)
                            result["sale_summary"] = cnt
                            if diag:
                                result.setdefault("diagnostics", []).append(diag)
                        elif key == "stock":
                            result["stock"] = import_stock(tmp.name, conn)
                        elif key == "category":
                            result["category"] = import_category(tmp.name, conn)
                        elif key == "profit":
                            cnt, diag = import_profit(tmp.name, conn)
                            result["profit"] = cnt
                            if diag:
                                result.setdefault("diagnostics", []).append(diag)
                    except Exception as e:
                        result["errors"].append(f"{key}: {str(e)}")
                    finally:
                        os.unlink(tmp.name)
        finally:
            if swap:
                os.environ.pop("HTMA_SWAP_AMOUNT_COST", None)
                if _orig_swap is not None:
                    os.environ["HTMA_SWAP_AMOUNT_COST"] = _orig_swap
            if amount_total:
                os.environ.pop("HTMA_AMOUNT_AS_TOTAL", None)
                if _orig_amt is not None:
                    os.environ["HTMA_AMOUNT_AS_TOTAL"] = _orig_amt
            if cost_total:
                os.environ.pop("HTMA_COST_AS_TOTAL", None)
                if _orig_cost is not None:
                    os.environ["HTMA_COST_AS_TOTAL"] = _orig_cost

        # 有销售数据且未上传毛利 Excel 时，从销售表汇总刷新毛利
        if (result["sale_daily"] > 0 or result["sale_summary"] > 0) and not _has_valid_file(["profit"]):
            result["profit_refreshed"] = refresh_profit(conn)
        # 从销售表透视生成品类主数据（大类/中类/小类）
        if result["sale_daily"] > 0 or result["sale_summary"] > 0:
            try:
                result["category_refreshed"] = refresh_category_from_sale(conn)
            except Exception as e:
                result.setdefault("errors", []).append(f"品类表刷新: {str(e)}")

        cur.execute("SELECT COUNT(*) FROM t_htma_sale")
        result["sale_total"] = cur.fetchone()["COUNT(*)"]
        cur.execute("SELECT COUNT(*) FROM t_htma_stock")
        result["stock_total"] = cur.fetchone()["COUNT(*)"]
        cur.execute("SELECT COUNT(*) FROM t_htma_profit")
        result["profit_total"] = cur.fetchone()["COUNT(*)"]
        cur.execute("SELECT MIN(data_date), MAX(data_date) FROM t_htma_sale")
        dr = cur.fetchone()
        if dr["MIN(data_date)"]:
            result["date_range"] = f"{dr['MIN(data_date)']} ~ {dr['MAX(data_date)']}"
        else:
            cur.execute("SELECT MIN(data_date), MAX(data_date) FROM t_htma_profit")
            drp = cur.fetchone()
            result["date_range"] = f"{drp['MIN(data_date)']} ~ {drp['MAX(data_date)']}" if drp and drp["MIN(data_date)"] else "-"

        conn.close()
        result["success"] = True
        # 导入成功时发送飞书通知
        if result.get("sale_total", 0) > 0 or result.get("stock_total", 0) > 0:
            msg = f"好特卖数据导入完成\n销售表: {result.get('sale_total', 0)} 条\n库存表: {result.get('stock_total', 0)} 条\n毛利表: {result.get('profit_total', 0)} 条\n日期范围: {result.get('date_range', '-')}"
            _notify_feishu(msg)
        return jsonify(result)
    except Exception as e:
        import traceback
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return jsonify({"success": False, "message": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/api/import_preview", methods=["POST"])
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


@app.route("/api/categories")
def api_categories():
    """获取品类列表。优先从 t_htma_category（品类主数据）级联；无则从 t_htma_sale、t_htma_profit 兜底。
    编码规则：中类编码前2位=大类编码，小类编码前4位=中类编码。level=large|mid|small。返回 [{code, name}]"""
    level = request.args.get("level", "large").strip() or "large"
    large_key = request.args.get("category_large_code", "").strip()
    mid_key = request.args.get("category_mid_code", "").strip()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 优先品类主数据表（附表结构，编码级联）
            cur.execute("SELECT COUNT(*) AS cnt FROM t_htma_category")
            cat_cnt = cur.fetchone().get("cnt") or 0
            if cat_cnt > 0:
                if level == "large":
                    cur.execute("""
                        SELECT DISTINCT category_large_code AS code, category_large AS name
                        FROM t_htma_category WHERE category_large_code != '' AND category_large != ''
                        ORDER BY category_large_code
                    """)
                elif level == "mid":
                    if large_key:
                        cur.execute("""
                            SELECT DISTINCT category_mid_code AS code, category_mid AS name
                            FROM t_htma_category
                            WHERE category_large_code = %s AND category_mid_code != ''
                            ORDER BY category_mid_code
                        """, (large_key,))
                    else:
                        cur.execute("""
                            SELECT DISTINCT category_mid_code AS code, category_mid AS name
                            FROM t_htma_category WHERE category_mid_code != ''
                            ORDER BY category_mid_code
                        """)
                elif level == "small":
                    if large_key and mid_key:
                        cur.execute("""
                            SELECT DISTINCT category_small_code AS code, category_small AS name
                            FROM t_htma_category
                            WHERE category_large_code = %s AND category_mid_code = %s AND category_small_code != ''
                            ORDER BY category_small_code
                        """, (large_key, mid_key))
                    elif large_key:
                        cur.execute("""
                            SELECT DISTINCT category_small_code AS code, category_small AS name
                            FROM t_htma_category
                            WHERE category_large_code = %s AND category_small_code != ''
                            ORDER BY category_small_code
                        """, (large_key,))
                    else:
                        cur.execute("""
                            SELECT DISTINCT category_small_code AS code, category_small AS name
                            FROM t_htma_category WHERE category_small_code != ''
                            ORDER BY category_small_code
                        """)
                else:
                    return jsonify([])
                rows = cur.fetchall()
                # 编码级联：中类前2位=大类，小类前4位=中类（兼容主数据表可能用编码过滤）
                if level == "mid" and large_key and not rows:
                    cur.execute("""
                        SELECT DISTINCT category_mid_code AS code, category_mid AS name
                        FROM t_htma_category
                        WHERE category_mid_code LIKE %s AND category_mid_code != ''
                        ORDER BY category_mid_code
                    """, (large_key[:2] + "%",))
                    rows = cur.fetchall()
                elif level == "small" and mid_key and not rows:
                    cur.execute("""
                        SELECT DISTINCT category_small_code AS code, category_small AS name
                        FROM t_htma_category
                        WHERE category_small_code LIKE %s AND category_small_code != ''
                        ORDER BY category_small_code
                    """, (mid_key[:4] + "%",))
                    rows = cur.fetchall()
            else:
                rows = []
            # 兜底：从 t_htma_sale、t_htma_profit 取
            if not rows:
                if level == "large":
                    cur.execute("""
                        SELECT DISTINCT
                            COALESCE(NULLIF(TRIM(category_large_code), ''), NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category), ''), '未分类') AS code,
                            COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category), ''), '未分类') AS name
                        FROM t_htma_sale WHERE store_id = %s
                          AND (COALESCE(TRIM(category_large_code), '') != '' OR COALESCE(TRIM(category_large), '') != '' OR COALESCE(TRIM(category), '') != '')
                        ORDER BY name
                    """, (STORE_ID,))
                elif level == "mid":
                    large_cond = "(COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)" if large_key else "1=1"
                    cur.execute(f"""
                        SELECT DISTINCT
                            COALESCE(NULLIF(TRIM(category_mid_code), ''), NULLIF(TRIM(category_mid), ''), COALESCE(category, '未分类')) AS code,
                            COALESCE(NULLIF(TRIM(category_mid), ''), COALESCE(category, '未分类')) AS name
                        FROM t_htma_sale WHERE store_id = %s AND {large_cond}
                          AND (COALESCE(TRIM(category_mid_code), '') != '' OR COALESCE(TRIM(category_mid), '') != '' OR COALESCE(TRIM(category), '') != '')
                        ORDER BY code
                    """, (STORE_ID, large_key, large_key) if large_key else (STORE_ID,))
                elif level == "small":
                    large_cond = "(COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)" if large_key else "1=1"
                    mid_cond = "(COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)" if mid_key else "1=1"
                    params = [STORE_ID]
                    if large_key:
                        params.extend([large_key, large_key])
                    if mid_key:
                        params.extend([mid_key, mid_key])
                    cur.execute(f"""
                        SELECT DISTINCT
                            COALESCE(NULLIF(TRIM(category_small_code), ''), NULLIF(TRIM(category_small), ''), COALESCE(category, '未分类')) AS code,
                            COALESCE(NULLIF(TRIM(category_small), ''), COALESCE(category, '未分类')) AS name
                        FROM t_htma_sale WHERE store_id = %s AND {large_cond} AND {mid_cond}
                          AND (COALESCE(TRIM(category_small_code), '') != '' OR COALESCE(TRIM(category_small), '') != '' OR COALESCE(TRIM(category), '') != '')
                        ORDER BY code
                    """, tuple(params))
                else:
                    return jsonify([])
                rows = cur.fetchall()
                if not rows and level == "large":
                    cur.execute("""
                        SELECT DISTINCT
                            COALESCE(NULLIF(TRIM(category_large_code), ''), NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category), ''), '未分类') AS code,
                            COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category), ''), '未分类') AS name
                        FROM t_htma_profit WHERE store_id = %s
                          AND (COALESCE(TRIM(category_large_code), '') != '' OR COALESCE(TRIM(category_large), '') != '' OR COALESCE(TRIM(category), '') != '')
                        ORDER BY name
                    """, (STORE_ID,))
                    rows = cur.fetchall()
        seen = {}
        for r in rows:
            code = str(r.get("code") or "").strip()
            name = str(r.get("name") or "").strip()
            if not name:
                continue
            if name not in seen or (code and not seen[name]["code"]):
                seen[name] = {"code": code or name, "name": name}
        return jsonify(list(seen.values()))
    finally:
        conn.close()


@app.route("/api/products")
def api_products():
    """获取商品列表（SKU+品类），用于下拉筛选。支持 category_*_code 编码或名称预筛"""
    category_large_code = request.args.get("category_large_code", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip()
    category_small_code = request.args.get("category_small_code", "").strip()
    conds, params = ["store_id = %s"], [STORE_ID]
    if category_large_code:
        conds.append("(COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)")
        params.extend([category_large_code, category_large_code])
    if category_mid_code:
        conds.append("(COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)")
        params.extend([category_mid_code, category_mid_code])
    if category_small_code:
        conds.append("(COALESCE(TRIM(category_small_code), '') = %s OR COALESCE(TRIM(category_small), '') = %s OR COALESCE(TRIM(category), '') = %s)")
        params.extend([category_small_code, category_small_code, category_small_code])
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT sku_code, COALESCE(category, '未分类') AS category
                FROM t_htma_sale
                WHERE """ + " AND ".join(conds) + """
                ORDER BY category, sku_code
            """, tuple(params))
            rows = cur.fetchall()
        return jsonify([{"sku_code": r["sku_code"], "category": r["category"]} for r in rows])
    finally:
        conn.close()


@app.route("/api/sale_detail")
def api_sale_detail():
    """商品级销售毛利明细：日期、SKU、品类、销量、销售额、成本、毛利、毛利率。支持 period、start_date、end_date、category、sku_code、page、page_size"""
    date_cond, _, params, category_cond, sku_cond = _query_filters(include_sku=True)
    page = max(1, int(request.args.get("page", "1")))
    page_size = min(500, max(10, int(request.args.get("page_size", "50"))))
    offset = (page - 1) * page_size
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COUNT(*) AS total FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
            """, params)
            total = cur.fetchone()["total"] or 0
            cur.execute(f"""
                SELECT data_date, sku_code, COALESCE(category, '未分类') AS category,
                       COALESCE(product_name, '') AS product_name,
                       COALESCE(category_large, '') AS category_large, COALESCE(category_mid, '') AS category_mid, COALESCE(category_small, '') AS category_small,
                       sale_qty, sale_amount, sale_cost, gross_profit,
                       CASE WHEN sale_amount > 0 THEN (COALESCE(gross_profit, 0) / sale_amount) * 100 ELSE 0 END AS profit_rate_pct
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                ORDER BY data_date DESC, sale_amount DESC
                LIMIT %s OFFSET %s
            """, (*params, page_size, offset))
            rows = cur.fetchall()
        return jsonify({
            "items": [{
            "data_date": r["data_date"].strftime("%Y-%m-%d") if hasattr(r["data_date"], "strftime") else str(r["data_date"]),
            "sku_code": r["sku_code"],
            "category": r["category"],
            "product_name": r.get("product_name") or "",
            "category_large": r.get("category_large") or "",
            "category_mid": r.get("category_mid") or "",
            "category_small": r.get("category_small") or "",
            "sale_qty": float(r["sale_qty"] or 0),
            "sale_amount": float(r["sale_amount"] or 0),
            "sale_cost": float(r["sale_cost"] or 0),
            "gross_profit": float(r["gross_profit"] or 0),
            "profit_rate_pct": round(float(r["profit_rate_pct"] or 0), 2),
        } for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    finally:
        conn.close()


@app.route("/api/export")
def api_export():
    """导出筛选后的数据为 CSV。支持 period、start_date、end_date、category、sku_code、export_type=category|product"""
    from flask import Response
    import csv
    import io

    export_type = request.args.get("export_type", "product").strip() or "product"
    include_sku = export_type == "product"
    date_cond, date_params, params, category_cond, sku_cond = _query_filters(include_sku=include_sku)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if export_type == "category":
                profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
                export_params = (STORE_ID,) + date_params + profit_cat_params
                cur.execute(f"""
                    SELECT data_date, COALESCE(category, '未分类') AS category,
                           total_sale, total_profit, profit_rate
                    FROM t_htma_profit
                    WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                    ORDER BY data_date DESC, total_sale DESC
                """, export_params)
                rows = cur.fetchall()
                headers = ["日期", "品类", "销售额", "毛利", "毛利率"]
                data_rows = []
                for r in rows:
                    rate = float(r["profit_rate"] or 0) * 100 if r["profit_rate"] else 0
                    data_rows.append([
                        r["data_date"].strftime("%Y-%m-%d") if hasattr(r["data_date"], "strftime") else str(r["data_date"]),
                        r["category"] or "未分类",
                        str(round(float(r["total_sale"] or 0), 2)),
                        str(round(float(r["total_profit"] or 0), 2)),
                        f"{rate:.2f}%",
                    ])
            else:
                cur.execute(f"""
                    SELECT data_date, sku_code, COALESCE(category, '未分类') AS category,
                           sale_qty, sale_amount, sale_cost, gross_profit
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                    ORDER BY data_date DESC, sale_amount DESC
                """, params)
                rows = cur.fetchall()
                headers = ["日期", "商品编码", "品类", "销售数量", "销售额", "成本", "毛利"]
                data_rows = []
                for r in rows:
                    data_rows.append([
                        r["data_date"].strftime("%Y-%m-%d") if hasattr(r["data_date"], "strftime") else str(r["data_date"]),
                        r["sku_code"] or "",
                        r["category"] or "未分类",
                        str(float(r["sale_qty"] or 0)),
                        str(round(float(r["sale_amount"] or 0), 2)),
                        str(round(float(r["sale_cost"] or 0), 2)),
                        str(round(float(r["gross_profit"] or 0), 2)),
                    ])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        for row in data_rows:
            writer.writerow(row)

        buf = io.BytesIO()
        buf.write(output.getvalue().encode("utf-8-sig"))
        buf.seek(0)
        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": "attachment; filename=htma_export.csv"},
        )
    finally:
        conn.close()


@app.route("/api/date_range")
def api_date_range():
    """获取数据日期范围，用于日期选择器默认值"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT MIN(data_date) AS min_date, MAX(data_date) AS max_date
                FROM t_htma_profit WHERE store_id = %s
            """, (STORE_ID,))
            row = cur.fetchone()
        min_d = row["min_date"]
        max_d = row["max_date"]
        return jsonify({
            "min_date": min_d.strftime("%Y-%m-%d") if min_d and hasattr(min_d, "strftime") else None,
            "max_date": max_d.strftime("%Y-%m-%d") if max_d and hasattr(max_d, "strftime") else None,
        })
    finally:
        conn.close()


@app.route("/api/kpi")
def api_kpi():
    """4 个 KPI：总销售额、总毛利、平均毛利率、库存总额。支持 period、start_date、end_date、category 及 hierarchy"""
    date_cond, date_params, _, sale_cat_cond, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    params = (STORE_ID,) + date_params + profit_cat_params
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(SUM(total_sale), 0) AS total_sale_amount,
                       COALESCE(SUM(total_profit), 0) AS total_gross_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}
            """, params)
            row = cur.fetchone()
            total_sale = float(row["total_sale_amount"] or 0)
            total_profit = float(row["total_gross_profit"] or 0)
            avg_rate = (total_profit / total_sale * 100) if total_sale > 0 else 0

            cur.execute("""
                SELECT COALESCE(SUM(stock_amount), 0) AS total_stock_amount
                FROM t_htma_stock
                WHERE store_id = %s AND data_date = (
                    SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                )
            """, (STORE_ID, STORE_ID))
            stock_row = cur.fetchone()
            total_stock = float(stock_row["total_stock_amount"] or 0)

        period = request.args.get("period", "recent30")
        start_d = request.args.get("start_date", "").strip()
        end_d = request.args.get("end_date", "").strip()
        period_label = f"{start_d} ~ {end_d}" if (start_d and end_d) else {"day": "今日", "week": "本周", "month": "本月", "recent30": "近30天"}.get(period, "近30天")
        return jsonify({
            "total_sale_amount": round(total_sale, 2),
            "total_gross_profit": round(total_profit, 2),
            "avg_profit_rate_pct": round(avg_rate, 2),
            "total_stock_amount": round(total_stock, 2),
            "period": period,
            "period_label": period_label,
        })
    finally:
        conn.close()


def _date_condition(period, start_date=None, end_date=None):
    """返回 (date_cond, params) 用于 SQL。若 start_date/end_date 均提供则用自定义区间"""
    if start_date and end_date:
        return "data_date BETWEEN %s AND %s", (start_date, end_date)
    if period == "day":
        return "data_date = CURDATE()", ()
    if period == "week":
        return "data_date >= DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY) AND data_date <= CURDATE()", ()
    if period == "month":
        return "data_date >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01') AND data_date <= CURDATE()", ()
    days = int(os.environ.get("HTMA_DAYS", DEFAULT_DAYS))
    return "data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL %s DAY) AND CURDATE()", (days,)


def _query_filters(include_sku=False):
    """从 request 解析筛选条件。返回 (date_cond, params, category_cond, sku_cond)。
    支持 category_large/category_mid/category_small/category 级联筛选。
    category_cond 适用于 t_htma_sale；profit 表需用 _profit_category_cond。"""
    period = request.args.get("period", "recent30")
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    category_large_code = request.args.get("category_large_code", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip()
    category_small_code = request.args.get("category_small_code", "").strip()
    sku_code = request.args.get("sku_code", "").strip() if include_sku else ""

    date_cond, date_params = _date_condition(period, start_date or None, end_date or None)
    base_params = list(date_params)
    sale_conds = []
    sale_params = []
    # 支持编码或名称匹配（级联选择器可能传名称）
    if category_large_code:
        sale_conds.append(" AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)")
        sale_params.extend([category_large_code, category_large_code])
    if category_mid_code:
        sale_conds.append(" AND (COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)")
        sale_params.extend([category_mid_code, category_mid_code])
    if category_small_code:
        sale_conds.append(" AND (COALESCE(TRIM(category_small_code), '') = %s OR COALESCE(TRIM(category_small), '') = %s OR COALESCE(TRIM(category), '') = %s)")
        sale_params.extend([category_small_code, category_small_code, category_small_code])
    sale_category_cond = "".join(sale_conds)
    sku_cond = ""
    if sku_code:
        sku_cond = " AND sku_code = %s"
        sale_params.append(sku_code)
    params = (STORE_ID,) + tuple(base_params) + tuple(sale_params)
    return date_cond, tuple(base_params), params, sale_category_cond, sku_cond


def _profit_category_cond_and_params(date_cond, date_params_tuple):
    """返回用于 t_htma_profit 的 category 条件与参数。支持编码或名称匹配（级联选择器可能传名称）"""
    category_large_code = request.args.get("category_large_code", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip()
    category_small_code = request.args.get("category_small_code", "").strip()
    if not (category_large_code or category_mid_code or category_small_code):
        return "", ()
    conds, params = [], []
    if category_large_code:
        conds.append("(COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)")
        params.extend([category_large_code, category_large_code])
    if category_mid_code:
        conds.append("(COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)")
        params.extend([category_mid_code, category_mid_code])
    if category_small_code:
        conds.append("(COALESCE(TRIM(category_small_code), '') = %s OR COALESCE(TRIM(category_small), '') = %s OR COALESCE(TRIM(category), '') = %s)")
        params.extend([category_small_code, category_small_code, category_small_code])
    return " AND " + " AND ".join(conds), tuple(params)


@app.route("/api/category_pie")
def api_category_pie():
    """品类销售额占比（Top10 + 其他），支持 period、start_date、end_date、category 及 hierarchy"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                WITH cs AS (
                    SELECT COALESCE(category, '未分类') AS category, SUM(sale_amount) AS sale_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}
                    GROUP BY category
                ),
                ranked AS (
                    SELECT category, sale_amount, ROW_NUMBER() OVER (ORDER BY sale_amount DESC) AS rn FROM cs
                )
                SELECT CASE WHEN rn <= 10 THEN category ELSE '其他' END AS category,
                       SUM(sale_amount) AS sale_amount
                FROM ranked
                GROUP BY CASE WHEN rn <= 10 THEN category ELSE '其他' END
                ORDER BY sale_amount DESC
            """, params)
            rows = cur.fetchall()
        return jsonify([{"category": r["category"], "sale_amount": float(r["sale_amount"])} for r in rows])
    finally:
        conn.close()


@app.route("/api/daily_trend")
def api_daily_trend():
    """日销售额趋势（兼容旧接口）"""
    return api_sales_trend("day")


@app.route("/api/sales_trend")
def api_sales_trend_route():
    """销售额/毛利趋势，支持 granularity、start_date、end_date、category"""
    g = request.args.get("granularity", "day")
    return api_sales_trend(g)


def api_sales_trend(granularity):
    """按日/周/月聚合销售额与毛利趋势"""
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    params = (STORE_ID,) + date_params + profit_cat_params
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if granularity == "day":
                cur.execute(f"""
                    SELECT data_date AS x_date, SUM(total_sale) AS sale_amount, SUM(total_profit) AS profit_amount
                    FROM t_htma_profit
                    WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                    GROUP BY data_date ORDER BY data_date
                """, params)
                rows = cur.fetchall()
                out = [_format_trend_row(r, "day") for r in rows]
            elif granularity == "week":
                cur.execute(f"""
                    SELECT MIN(data_date) AS week_start,
                           CONCAT(YEAR(MIN(data_date)), '-W', LPAD(WEEK(MIN(data_date), 3), 2, '0')) AS x_date,
                           SUM(total_sale) AS sale_amount, SUM(total_profit) AS profit_amount
                    FROM t_htma_profit
                    WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                    GROUP BY YEAR(data_date), WEEK(data_date, 3)
                    ORDER BY MIN(data_date)
                """, params)
                rows = cur.fetchall()
                out = [_format_trend_row(r, "week") for r in rows]
            else:  # month
                cur.execute(f"""
                    SELECT DATE_FORMAT(MIN(data_date), '%%Y-%%m') AS x_date,
                           SUM(total_sale) AS sale_amount, SUM(total_profit) AS profit_amount
                    FROM t_htma_profit
                    WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                    GROUP BY YEAR(data_date), MONTH(data_date)
                    ORDER BY MIN(data_date)
                """, params)
                rows = cur.fetchall()
                out = [_format_trend_row(r, "month") for r in rows]
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e), "detail": repr(e)}), 500
    finally:
        conn.close()


def _format_trend_row(r, granularity):
    """安全格式化趋势行，避免日期/空值导致的异常"""
    x_date = r.get("x_date")
    if x_date is not None and hasattr(x_date, "strftime"):
        x_str = x_date.strftime("%Y-%m-%d" if granularity == "day" else "%Y-%m")
    else:
        x_str = str(x_date) if x_date else ""
    week_start = r.get("week_start")
    if week_start is not None and hasattr(week_start, "strftime"):
        ws_str = week_start.strftime("%Y-%m-%d")
    else:
        ws_str = str(week_start) if week_start else ""
    return {
        "x_date": x_str,
        "week_start": ws_str,
        "sale_amount": float(r.get("sale_amount") or 0),
        "profit_amount": float(r.get("profit_amount") or 0),
    }


@app.route("/api/trend_analysis")
def api_trend_analysis():
    """走势分析：环比、同比、趋势描述。支持 start_date、end_date、category_large/mid/small"""
    granularity = request.args.get("granularity", "day")
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    params_ta = (STORE_ID,) + date_params + profit_cat_params
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if granularity == "day":
                cur.execute(f"""
                    SELECT data_date, SUM(total_sale) AS sale_amount, SUM(total_profit) AS profit_amount
                    FROM t_htma_profit
                    WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                    GROUP BY data_date ORDER BY data_date
                """, params_ta)
            elif granularity == "week":
                cur.execute(f"""
                    SELECT YEAR(data_date) AS y, WEEK(data_date, 3) AS w,
                           MIN(data_date) AS week_start,
                           SUM(total_sale) AS sale_amount, SUM(total_profit) AS profit_amount
                    FROM t_htma_profit
                    WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                    GROUP BY YEAR(data_date), WEEK(data_date, 3)
                    ORDER BY week_start
                """, params_ta)
            else:
                cur.execute(f"""
                    SELECT YEAR(data_date) AS y, MONTH(data_date) AS m,
                           DATE_FORMAT(MIN(data_date), '%%Y-%%m') AS month_key,
                           SUM(total_sale) AS sale_amount, SUM(total_profit) AS profit_amount
                    FROM t_htma_profit
                    WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                    GROUP BY YEAR(data_date), MONTH(data_date)
                    ORDER BY MIN(data_date)
                """, params_ta)

            rows = cur.fetchall()
            if not rows:
                return jsonify({"message": "数据不足", "period_over_period": None, "year_over_year": None, "trend": "neutral"})

            # 转为列表便于索引
            data_list = []
            for r in rows:
                if granularity == "day":
                    data_list.append({
                        "key": r["data_date"].strftime("%Y-%m-%d") if hasattr(r["data_date"], "strftime") else str(r["data_date"]),
                        "sale_amount": float(r["sale_amount"]),
                        "profit_amount": float(r["profit_amount"]),
                    })
                elif granularity == "week":
                    data_list.append({
                        "key": f"{r['y']}-W{r['w']:02d}",
                        "sale_amount": float(r["sale_amount"]),
                        "profit_amount": float(r["profit_amount"]),
                    })
                else:
                    data_list.append({
                        "key": r["month_key"] or "",
                        "sale_amount": float(r["sale_amount"]),
                        "profit_amount": float(r["profit_amount"]),
                    })

            # 环比：最近两期
            pop = None
            if len(data_list) >= 2:
                curr = data_list[-1]
                prev = data_list[-2]
                curr_sale, prev_sale = curr["sale_amount"], prev["sale_amount"]
                curr_profit, prev_profit = curr["profit_amount"], prev["profit_amount"]
                sale_chg = ((curr_sale - prev_sale) / prev_sale * 100) if prev_sale > 0 else 0
                profit_chg = ((curr_profit - prev_profit) / prev_profit * 100) if prev_profit > 0 else 0
                pop = {
                    "current_period": curr["key"],
                    "prev_period": prev["key"],
                    "sale_change_pct": round(sale_chg, 2),
                    "profit_change_pct": round(profit_chg, 2),
                    "current_sale": round(curr_sale, 2),
                    "prev_sale": round(prev_sale, 2),
                    "current_profit": round(curr_profit, 2),
                    "prev_profit": round(prev_profit, 2),
                }

            # 同比：本期 vs 去年同期（月粒度需13期；周粒度需53期；日粒度需366期）
            yoy = None
            idx_last_year = {"month": 13, "week": 53, "day": 366}.get(granularity, 13)
            if len(data_list) >= idx_last_year:
                curr = data_list[-1]
                same_last_year = data_list[-idx_last_year]
                curr_sale, last_sale = curr["sale_amount"], same_last_year["sale_amount"]
                curr_profit, last_profit = curr["profit_amount"], same_last_year["profit_amount"]
                sale_yoy = ((curr_sale - last_sale) / last_sale * 100) if last_sale > 0 else 0
                profit_yoy = ((curr_profit - last_profit) / last_profit * 100) if last_profit > 0 else 0
                yoy = {
                    "current_period": curr["key"],
                    "same_period_last_year": same_last_year["key"],
                    "sale_change_pct": round(sale_yoy, 2),
                    "profit_change_pct": round(profit_yoy, 2),
                }

            # 趋势：最近5期简单线性趋势（斜率正负）
            trend = "neutral"
            if len(data_list) >= 5:
                recent = [x["sale_amount"] for x in data_list[-5:]]
                n = len(recent)
                x_mean = (n - 1) / 2
                y_mean = sum(recent) / n
                numer = sum((i - x_mean) * (recent[i] - y_mean) for i in range(n))
                denom = sum((i - x_mean) ** 2 for i in range(n))
                slope = (numer / denom) if denom > 0 else 0
                trend = "up" if slope > 0 else "down" if slope < 0 else "neutral"

        # 同比所需最少期数说明
        yoy_required = {"month": 13, "week": 53, "day": 366}.get(granularity, 13)
        yoy_reason = None
        if not yoy and len(data_list) > 0:
            yoy_reason = f"同比需至少{yoy_required}期数据（{'月' if granularity=='month' else '周' if granularity=='week' else '日'}粒度），当前仅{len(data_list)}期"
        return jsonify({
            "granularity": granularity,
            "period_over_period": pop,
            "year_over_year": yoy,
            "trend": trend,
            "data_points": len(data_list),
            "yoy_reason": yoy_reason,
        })
    finally:
        conn.close()


@app.route("/api/dow_sales")
def api_dow_sales():
    """周几对比：按星期几聚合销售额、毛利，便于对比周一 vs 周五等"""
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    params = (STORE_ID,) + date_params + profit_cat_params
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT DAYOFWEEK(data_date) AS dow,
                       MAX(CASE DAYOFWEEK(data_date)
                         WHEN 1 THEN '周日' WHEN 2 THEN '周一' WHEN 3 THEN '周二' WHEN 4 THEN '周三'
                         WHEN 5 THEN '周四' WHEN 6 THEN '周五' WHEN 7 THEN '周六' ELSE '周日' END) AS dow_name,
                       SUM(total_sale) AS sale_amount, SUM(total_profit) AS profit_amount,
                       COUNT(DISTINCT data_date) AS day_count
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                GROUP BY DAYOFWEEK(data_date)
                ORDER BY dow
            """, params)
            rows = cur.fetchall()
        return jsonify([{
            "dow": r["dow"],
            "dow_name": r["dow_name"],
            "sale_amount": float(r["sale_amount"] or 0),
            "profit_amount": float(r["profit_amount"] or 0),
            "day_count": int(r["day_count"] or 0),
        } for r in rows])
    finally:
        conn.close()


def _inv_category_cond_and_params():
    """低库存：通过 sku 关联 sale 表获取品类层级，支持 category_large/mid/small 筛选"""
    category_large_code = request.args.get("category_large_code", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip()
    category_small_code = request.args.get("category_small_code", "").strip()
    if not (category_large_code or category_mid_code or category_small_code):
        return "", (), False
    conds, params = [], []
    if category_large_code:
        conds.append("(COALESCE(TRIM(s.category_large_code), '') = %s OR COALESCE(TRIM(s.category_large), '') = %s)")
        params.extend([category_large_code, category_large_code])
    if category_mid_code:
        conds.append("(COALESCE(TRIM(s.category_mid_code), '') = %s OR COALESCE(TRIM(s.category_mid), '') = %s)")
        params.extend([category_mid_code, category_mid_code])
    if category_small_code:
        conds.append("(COALESCE(TRIM(s.category_small_code), '') = %s OR COALESCE(TRIM(s.category_small), '') = %s OR COALESCE(TRIM(s.category), '') = %s)")
        params.extend([category_small_code, category_small_code, category_small_code])
    return " AND " + " AND ".join(conds), tuple(params), True


@app.route("/api/inv_alert_by_category")
def api_inv_alert_by_category():
    """低库存按品类层级汇总：level=large 按大类，level=mid 按中类，level=small 按小类。支持 category_large_code/mid 筛选"""
    level = request.args.get("level", "large").strip() or "large"
    category_large_code = request.args.get("category_large_code", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip()
    inv_cond, inv_params, need_join = _inv_category_cond_and_params()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if level == "large":
                if need_join:
                    cur.execute(f"""
                        SELECT COALESCE(NULLIF(TRIM(s.category_large), ''), NULLIF(TRIM(s.category_large_code), ''), COALESCE(NULLIF(TRIM(st.category_name), ''), '未分类')) AS category_large,
                               COALESCE(NULLIF(TRIM(s.category_large_code), ''), NULLIF(TRIM(s.category_large), ''), '') AS category_large_code,
                               COUNT(DISTINCT st.sku_code) AS alert_sku_count,
                               COALESCE(SUM(st.stock_amount), 0) AS stock_amount
                        FROM t_htma_stock st
                        LEFT JOIN (
                            SELECT sku_code,
                                   MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                                   MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                                   MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                            FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                        ) s ON st.sku_code = s.sku_code
                        WHERE st.store_id = %s AND st.data_date = (
                            SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                        ) AND st.stock_qty < 50 AND st.stock_qty >= 0 {inv_cond}
                        GROUP BY category_large, category_large_code
                        ORDER BY alert_sku_count DESC
                    """, (STORE_ID, STORE_ID, STORE_ID) + inv_params)
                else:
                    cur.execute("""
                        SELECT COALESCE(NULLIF(TRIM(s.category_large), ''), NULLIF(TRIM(s.category_large_code), ''), COALESCE(NULLIF(TRIM(st.category_name), ''), COALESCE(NULLIF(TRIM(st.category), ''), '未分类'))) AS category_large,
                               COALESCE(NULLIF(TRIM(s.category_large_code), ''), NULLIF(TRIM(s.category_large), ''), '') AS category_large_code,
                               COUNT(DISTINCT st.sku_code) AS alert_sku_count,
                               COALESCE(SUM(st.stock_amount), 0) AS stock_amount
                        FROM t_htma_stock st
                        LEFT JOIN (
                            SELECT sku_code,
                                   MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                                   MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                                   MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                            FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                        ) s ON st.sku_code = s.sku_code
                        WHERE st.store_id = %s AND st.data_date = (
                            SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                        ) AND st.stock_qty < 50 AND st.stock_qty >= 0
                        GROUP BY category_large, category_large_code
                        ORDER BY alert_sku_count DESC
                    """, (STORE_ID, STORE_ID, STORE_ID))
            elif level == "mid" and category_large_code:
                large_cond = " AND (COALESCE(TRIM(s.category_large_code), '') = %s OR COALESCE(TRIM(s.category_large), '') = %s)"
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(s.category_mid), ''), NULLIF(TRIM(s.category_mid_code), ''), '未分类') AS category_mid,
                           COALESCE(NULLIF(TRIM(s.category_mid_code), ''), NULLIF(TRIM(s.category_mid), ''), '') AS category_mid_code,
                           COUNT(DISTINCT st.sku_code) AS alert_sku_count,
                           COALESCE(SUM(st.stock_amount), 0) AS stock_amount
                    FROM t_htma_stock st
                    INNER JOIN (
                        SELECT sku_code,
                               MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                               MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                               MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                        FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                    ) s ON st.sku_code = s.sku_code
                    WHERE st.store_id = %s AND st.data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND st.stock_qty < 50 AND st.stock_qty >= 0 {large_cond}
                    GROUP BY category_mid, category_mid_code
                    ORDER BY alert_sku_count DESC
                """, (STORE_ID, STORE_ID, STORE_ID, category_large_code, category_large_code))
            elif level == "small" and category_large_code and category_mid_code:
                mid_cond = " AND (COALESCE(TRIM(s.category_mid_code), '') = %s OR COALESCE(TRIM(s.category_mid), '') = %s)"
                cur.execute(f"""
                    SELECT COALESCE(NULLIF(TRIM(s.category_small), ''), NULLIF(TRIM(s.category_small_code), ''), COALESCE(NULLIF(TRIM(s.category), ''), '未分类')) AS category_small,
                           COALESCE(NULLIF(TRIM(s.category_small_code), ''), NULLIF(TRIM(s.category), ''), '') AS category_small_code,
                           COUNT(DISTINCT st.sku_code) AS alert_sku_count,
                           COALESCE(SUM(st.stock_amount), 0) AS stock_amount
                    FROM t_htma_stock st
                    INNER JOIN (
                        SELECT sku_code,
                               MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                               MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                               MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                        FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                    ) s ON st.sku_code = s.sku_code
                    WHERE st.store_id = %s AND st.data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND st.stock_qty < 50 AND st.stock_qty >= 0
                    AND (COALESCE(TRIM(s.category_large_code), '') = %s OR COALESCE(TRIM(s.category_large), '') = %s) {mid_cond}
                    GROUP BY category_small, category_small_code
                    ORDER BY alert_sku_count DESC
                """, (STORE_ID, STORE_ID, STORE_ID, category_large_code, category_large_code, category_mid_code, category_mid_code))
            else:
                return jsonify([])
            rows = cur.fetchall()
        key = "category_large" if level == "large" else ("category_mid" if level == "mid" else "category_small")
        code_key = key + "_code"
        return jsonify([{
            key: r.get(key) or "未分类",
            code_key: r.get(code_key) or "",
            "alert_sku_count": int(r["alert_sku_count"] or 0),
            "stock_amount": round(float(r["stock_amount"] or 0), 2),
        } for r in rows])
    finally:
        conn.close()


@app.route("/api/inv_alert")
def api_inv_alert():
    """低库存预警 SKU 数，支持 category_large_code/mid/small 筛选"""
    inv_cond, inv_params, need_join = _inv_category_cond_and_params()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if need_join:
                cur.execute(f"""
                    SELECT COUNT(DISTINCT st.sku_code) AS alert_sku_count
                    FROM t_htma_stock st
                    INNER JOIN (
                        SELECT sku_code,
                               MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                               MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                               MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                        FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                    ) s ON st.sku_code = s.sku_code
                    WHERE st.store_id = %s AND st.data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND st.stock_qty < 50 AND st.stock_qty >= 0 {inv_cond}
                """, (STORE_ID, STORE_ID, STORE_ID) + inv_params)
            else:
                cur.execute("""
                    SELECT COUNT(DISTINCT sku_code) AS alert_sku_count
                    FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND stock_qty < 50 AND stock_qty >= 0
                """, (STORE_ID, STORE_ID))
            row = cur.fetchone()
        return jsonify({"alert_sku_count": int(row["alert_sku_count"] or 0)})
    finally:
        conn.close()


@app.route("/api/profit_summary")
def api_profit_summary():
    """品类汇总：按时间段合并，大类/中类/小类、销售额、毛利、毛利率。支持 period、start_date、end_date、category 及 hierarchy"""
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    params = (STORE_ID,) + date_params + profit_cat_params
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(category, '未分类') AS category,
                       MAX(COALESCE(category_large, '')) AS category_large,
                       MAX(COALESCE(category_mid, '')) AS category_mid,
                       MAX(COALESCE(category_small, '')) AS category_small,
                       SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                GROUP BY category
                ORDER BY total_sale DESC
            """, params)
            rows = cur.fetchall()
        return jsonify([{
            "category": r["category"] or "未分类",
            "category_large": r.get("category_large") or "",
            "category_mid": r.get("category_mid") or "",
            "category_small": r.get("category_small") or "",
            "total_sale": round(float(r["total_sale"] or 0), 2),
            "total_profit": round(float(r["total_profit"] or 0), 2),
            "profit_rate": round((float(r["total_profit"] or 0) / float(r["total_sale"] or 1) * 100), 2) if r["total_sale"] else 0,
        } for r in rows])
    finally:
        conn.close()


@app.route("/api/sale_summary")
def api_sale_summary():
    """商品汇总：按时间段合并，SKU、品名、品类、销量、销售额、成本、毛利、毛利率。支持 period、start_date、end_date、category、page、page_size"""
    date_cond, _, params, category_cond, sku_cond = _query_filters(include_sku=True)
    page = max(1, int(request.args.get("page", "1")))
    page_size = min(200, max(10, int(request.args.get("page_size", "50"))))
    offset = (page - 1) * page_size
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COUNT(DISTINCT sku_code) AS total FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
            """, params)
            total = cur.fetchone()["total"] or 0
            cur.execute(f"""
                SELECT sku_code,
                       MAX(COALESCE(product_name, '')) AS product_name,
                       MAX(COALESCE(category, '未分类')) AS category,
                       MAX(COALESCE(category_large, '')) AS category_large,
                       MAX(COALESCE(category_mid, '')) AS category_mid,
                       MAX(COALESCE(category_small, '')) AS category_small,
                       SUM(sale_qty) AS sale_qty, SUM(sale_amount) AS sale_amount,
                       SUM(sale_cost) AS sale_cost, SUM(gross_profit) AS gross_profit
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                GROUP BY sku_code
                ORDER BY sale_amount DESC
                LIMIT %s OFFSET %s
            """, (*params, page_size, offset))
            rows = cur.fetchall()
        return jsonify({
            "items": [{
                "sku_code": r["sku_code"],
                "product_name": r.get("product_name") or "",
                "category": r["category"] or "未分类",
                "category_large": r.get("category_large") or "",
                "category_mid": r.get("category_mid") or "",
                "category_small": r.get("category_small") or "",
                "sale_qty": float(r["sale_qty"] or 0),
                "sale_amount": round(float(r["sale_amount"] or 0), 2),
                "sale_cost": round(float(r["sale_cost"] or 0), 2),
                "gross_profit": round(float(r["gross_profit"] or 0), 2),
                "profit_rate_pct": round((float(r["gross_profit"] or 0) / float(r["sale_amount"] or 1) * 100), 2) if r["sale_amount"] else 0,
            } for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    finally:
        conn.close()


@app.route("/api/profit_detail")
def api_profit_detail():
    """毛利明细表：日期、品类、销售额、毛利、毛利率。支持 period、start_date、end_date、category 及 hierarchy、expand_category（展开某品类时传）、page、page_size"""
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    expand_category = request.args.get("expand_category", "").strip()
    expand_cond = " AND COALESCE(category, '未分类') = %s" if expand_category else ""
    expand_params = (expand_category,) if expand_category else ()
    params = (STORE_ID,) + date_params + profit_cat_params + expand_params
    page = max(1, int(request.args.get("page", "1")))
    page_size = min(200, max(10, int(request.args.get("page_size", "50"))))
    offset = (page - 1) * page_size
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COUNT(*) AS total FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}{expand_cond}
            """, params)
            total = cur.fetchone()["total"] or 0
            cur.execute(f"""
                SELECT data_date, category, total_sale, total_profit, profit_rate, store_id,
                       COALESCE(category_large, '') AS category_large, COALESCE(category_mid, '') AS category_mid, COALESCE(category_small, '') AS category_small
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}{expand_cond}
                ORDER BY data_date DESC, total_sale DESC
                LIMIT %s OFFSET %s
            """, (*params, page_size, offset))
            rows = cur.fetchall()
        return jsonify({
            "items": [{
            "data_date": r["data_date"].strftime("%Y-%m-%d") if hasattr(r["data_date"], "strftime") else str(r["data_date"]),
            "category": r["category"] or "未分类",
            "category_large": r.get("category_large") or "",
            "category_mid": r.get("category_mid") or "",
            "category_small": r.get("category_small") or "",
            "total_sale": float(r["total_sale"] or 0),
            "total_profit": float(r["total_profit"] or 0),
            "profit_rate": float(r["profit_rate"] or 0) * 100 if r["profit_rate"] else 0,
            "store_id": r["store_id"],
        } for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    finally:
        conn.close()


@app.route("/api/inv_alert_list")
def api_inv_alert_list():
    """低库存明细：SKU、品类、库存数量、库存金额。支持 page、page_size、category_large/mid/small"""
    inv_cond, inv_params, need_join = _inv_category_cond_and_params()
    page = max(1, int(request.args.get("page", "1")))
    page_size = min(100, max(10, int(request.args.get("page_size", "50"))))
    offset = (page - 1) * page_size
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if need_join:
                cur.execute(f"""
                    SELECT COUNT(*) AS total
                    FROM t_htma_stock st
                    INNER JOIN (
                        SELECT sku_code,
                               MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                               MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                               MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                        FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                    ) s ON st.sku_code = s.sku_code
                    WHERE st.store_id = %s AND st.data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND st.stock_qty < 50 AND st.stock_qty >= 0 {inv_cond}
                """, (STORE_ID, STORE_ID, STORE_ID) + inv_params)
                total = cur.fetchone()["total"] or 0
                cur.execute(f"""
                    SELECT st.sku_code, COALESCE(st.category, s.category, '') AS category,
                           COALESCE(st.product_name, '') AS product_name, st.stock_qty, st.stock_amount, st.data_date
                    FROM t_htma_stock st
                    INNER JOIN (
                        SELECT sku_code,
                               MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large,
                               MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid,
                               MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                        FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
                    ) s ON st.sku_code = s.sku_code
                    WHERE st.store_id = %s AND st.data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND st.stock_qty < 50 AND st.stock_qty >= 0 {inv_cond}
                    ORDER BY st.stock_qty ASC
                    LIMIT %s OFFSET %s
                """, (STORE_ID, STORE_ID, STORE_ID) + inv_params + (page_size, offset))
            else:
                cur.execute("""
                    SELECT COUNT(*) AS total FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND stock_qty < 50 AND stock_qty >= 0
                """, (STORE_ID, STORE_ID))
                total = cur.fetchone()["total"] or 0
                cur.execute("""
                    SELECT sku_code, category, COALESCE(product_name, '') AS product_name, stock_qty, stock_amount, data_date
                    FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (
                        SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s
                    ) AND stock_qty < 50 AND stock_qty >= 0
                    ORDER BY stock_qty ASC
                    LIMIT %s OFFSET %s
                """, (STORE_ID, STORE_ID, page_size, offset))
            rows = cur.fetchall()
        return jsonify({
            "items": [{
            "sku_code": r["sku_code"],
            "category": r["category"] or "未分类",
            "product_name": r.get("product_name") or "",
            "stock_qty": float(r["stock_qty"] or 0),
            "stock_amount": float(r["stock_amount"] or 0),
            "data_date": r["data_date"].strftime("%Y-%m-%d") if hasattr(r["data_date"], "strftime") else str(r["data_date"]),
        } for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    finally:
        conn.close()


@app.route("/api/data_status")
def api_data_status():
    """数据状态：用于实时展示导入数据概况"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM t_htma_sale WHERE store_id = %s", (STORE_ID,))
            sale_cnt = cur.fetchone()["cnt"] or 0
            cur.execute("SELECT COUNT(*) AS cnt FROM t_htma_stock WHERE store_id = %s", (STORE_ID,))
            stock_cnt = cur.fetchone()["cnt"] or 0
            cur.execute("SELECT COUNT(*) AS cnt FROM t_htma_profit WHERE store_id = %s", (STORE_ID,))
            profit_cnt = cur.fetchone()["cnt"] or 0
            cur.execute("SELECT MIN(data_date) AS min_d, MAX(data_date) AS max_d FROM t_htma_sale WHERE store_id = %s", (STORE_ID,))
            dr = cur.fetchone()
            min_d = dr["min_d"]
            max_d = dr["max_d"]
        return jsonify({
            "sale_count": sale_cnt,
            "stock_count": stock_cnt,
            "profit_count": profit_cnt,
            "min_date": min_d.strftime("%Y-%m-%d") if min_d and hasattr(min_d, "strftime") else None,
            "max_date": max_d.strftime("%Y-%m-%d") if max_d and hasattr(max_d, "strftime") else None,
        })
    finally:
        conn.close()


@app.route("/api/category_rank_by_large")
def api_category_rank_by_large():
    """品类排行按大类汇总：大类名称、销售额、毛利、毛利率、贡献度。支持 start_date、end_date、category 及 hierarchy"""
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    params = (STORE_ID,) + date_params + profit_cat_params
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category_large_code), ''), '未分类') AS category_large,
                       COALESCE(NULLIF(TRIM(category_large_code), ''), NULLIF(TRIM(category_large), ''), '') AS category_large_code,
                       SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                  AND (COALESCE(TRIM(category_large), '') != '' OR COALESCE(TRIM(category_large_code), '') != '')
                GROUP BY category_large, category_large_code
                ORDER BY total_sale DESC
                LIMIT 50
            """, params)
            rows = cur.fetchall()
            cur.execute(f"""
                SELECT COALESCE(SUM(total_sale), 0) AS total_sale, COALESCE(SUM(total_profit), 0) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}
            """, params)
            tot = cur.fetchone()
        total_sale = float(tot["total_sale"] or 0)
        total_profit = float(tot["total_profit"] or 0)
        out = []
        for i, r in enumerate(rows, 1):
            sale = float(r["total_sale"] or 0)
            profit = float(r["total_profit"] or 0)
            contrib_sale = (sale / total_sale * 100) if total_sale > 0 else 0
            contrib_profit = (profit / total_profit * 100) if total_profit > 0 else 0
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "rank": i,
                "category_large": r["category_large"] or "未分类",
                "category_large_code": r.get("category_large_code") or "",
                "sale_amount": round(sale, 2),
                "profit_amount": round(profit, 2),
                "margin_pct": round(margin, 2),
                "sale_contrib_pct": round(contrib_sale, 2),
                "profit_contrib_pct": round(contrib_profit, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


@app.route("/api/category_rank_detail")
def api_category_rank_detail():
    """品类排行明细：按大类下的中类/小类。需传 category_large_code 或 category_large"""
    category_large_code = request.args.get("category_large_code", "").strip() or request.args.get("category_large", "").strip()
    if not category_large_code:
        return jsonify([])
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    large_cond = " AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)"
    params = (STORE_ID,) + date_params + profit_cat_params + (category_large_code, category_large_code)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(category, '未分类') AS category,
                       MAX(COALESCE(category_mid, '')) AS category_mid,
                       MAX(COALESCE(category_small, '')) AS category_small,
                       SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}{large_cond}
                GROUP BY category
                ORDER BY total_sale DESC
                LIMIT 100
            """, params)
            rows = cur.fetchall()
        total_sale = sum(float(r["total_sale"] or 0) for r in rows)
        total_profit = sum(float(r["total_profit"] or 0) for r in rows)
        out = []
        for i, r in enumerate(rows, 1):
            sale = float(r["total_sale"] or 0)
            profit = float(r["total_profit"] or 0)
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "rank": i,
                "category_mid": r.get("category_mid") or "",
                "category": r["category"] or "未分类",
                "sale_amount": round(sale, 2),
                "profit_amount": round(profit, 2),
                "margin_pct": round(margin, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


@app.route("/api/category_rank")
def api_category_rank():
    """品类排行：销售、毛利、毛利率、贡献度。支持 start_date、end_date、category 及 hierarchy"""
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    params = (STORE_ID,) + date_params + profit_cat_params
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(category, '未分类') AS category,
                       SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}
                GROUP BY category
                ORDER BY total_sale DESC
                LIMIT 50
            """, params)
            rows = cur.fetchall()
            cur.execute(f"""
                SELECT COALESCE(SUM(total_sale), 0) AS total_sale, COALESCE(SUM(total_profit), 0) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}
            """, params)
            tot = cur.fetchone()
        total_sale = float(tot["total_sale"] or 0)
        total_profit = float(tot["total_profit"] or 0)
        out = category_rank_data(rows, total_sale, total_profit)
        return jsonify(out)
    finally:
        conn.close()


@app.route("/api/insights")
def api_insights():
    """智能分析建议：基于零售业数据模型生成"""
    conn = get_conn()
    try:
        insights = build_insights(conn, STORE_ID)
        return jsonify({"insights": insights})
    finally:
        conn.close()


@app.route("/api/repair_recalc_unit_price", methods=["POST"])
def api_repair_recalc_unit_price():
    """将金额/成本按单价×数量重算：当导入时误将单价当总金额时使用"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE t_htma_sale
                SET sale_amount = sale_amount * CASE WHEN sale_qty > 0 THEN sale_qty ELSE 1 END,
                    sale_cost = sale_cost * CASE WHEN sale_qty > 0 THEN sale_qty ELSE 1 END
            """)
            cur.execute("UPDATE t_htma_sale SET gross_profit = sale_amount - sale_cost")
            conn.commit()
            cur.execute("TRUNCATE TABLE t_htma_profit")
            cur.execute("""
                INSERT INTO t_htma_profit (data_date, category, total_sale, total_profit, profit_rate, store_id,
                    category_code, category_large_code, category_large, category_mid_code, category_mid, category_small_code, category_small)
                SELECT data_date, COALESCE(category, '未分类'),
                       SUM(sale_amount), SUM(COALESCE(gross_profit, 0)),
                       LEAST(1, GREATEST(-1, CASE WHEN SUM(sale_amount) > 0 THEN SUM(COALESCE(gross_profit, 0)) / SUM(sale_amount) ELSE 0 END)),
                       store_id,
                       MAX(category_code), MAX(category_large_code), MAX(category_large),
                       MAX(category_mid_code), MAX(category_mid), MAX(category_small_code), MAX(category_small)
                FROM t_htma_sale
                GROUP BY data_date, category, store_id
            """)
            conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "已按单价×数量重算销售额与成本"})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/repair_swap_amount_cost", methods=["POST"])
def api_repair_swap_amount_cost():
    """对调 t_htma_sale 中 sale_amount 与 sale_cost，并重算毛利表。用于修复金额/进价列错位导入的数据"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE t_htma_sale SET sale_amount = sale_cost, sale_cost = sale_amount")
            cur.execute("UPDATE t_htma_sale SET gross_profit = sale_amount - sale_cost")
            conn.commit()
            cur.execute("TRUNCATE TABLE t_htma_profit")
            cur.execute("""
                INSERT INTO t_htma_profit (data_date, category, total_sale, total_profit, profit_rate, store_id,
                    category_code, category_large_code, category_large, category_mid_code, category_mid, category_small_code, category_small)
                SELECT data_date, COALESCE(category, '未分类'),
                       SUM(sale_amount), SUM(COALESCE(gross_profit, 0)),
                       LEAST(1, GREATEST(-1, CASE WHEN SUM(sale_amount) > 0 THEN SUM(COALESCE(gross_profit, 0)) / SUM(sale_amount) ELSE 0 END)),
                       store_id,
                       MAX(category_code), MAX(category_large_code), MAX(category_large),
                       MAX(category_mid_code), MAX(category_mid), MAX(category_small_code), MAX(category_small)
                FROM t_htma_sale
                GROUP BY data_date, category, store_id
            """)
            conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "已对调金额与成本并重算毛利表"})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "message": str(e)}), 500


def _ensure_report_log_table(conn):
    """确保 t_htma_report_log 表存在"""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS t_htma_report_log (
              id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
              report_date DATE NOT NULL,
              report_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              store_id VARCHAR(32) DEFAULT '沈阳超级仓',
              report_content TEXT NOT NULL,
              feishu_at_user_id VARCHAR(64) DEFAULT NULL,
              feishu_at_user_name VARCHAR(32) DEFAULT NULL,
              send_status TINYINT DEFAULT 1,
              send_error VARCHAR(512) DEFAULT NULL,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              KEY idx_report_date (report_date),
              KEY idx_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.commit()
        cur.close()
    except Exception:
        pass


def _save_report_log(conn, report, send_ok, send_err=None):
    """将报告保存到 t_htma_report_log"""
    try:
        _ensure_report_log_table(conn)
        from feishu_util import FEISHU_AT_USER_ID, FEISHU_AT_USER_NAME
        uid = (FEISHU_AT_USER_ID or "").strip()
        if uid and not uid.startswith("ou_"):
            uid = f"ou_{uid}"
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO t_htma_report_log
               (report_date, report_time, store_id, report_content, feishu_at_user_id, feishu_at_user_name, send_status, send_error)
               VALUES (CURDATE(), NOW(), %s, %s, %s, %s, %s, %s)""",
            (STORE_ID, report, uid or None, FEISHU_AT_USER_NAME, 1 if send_ok else 0, (send_err or "")[:512]),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        pass  # 表可能未创建，静默失败


@app.route("/api/marketing_report")
def api_marketing_report():
    """进销存营销分析报告。mode=market_expansion 为市场拓展版，internal 为传统版。send=1 时推送飞书"""
    send_feishu_flag = request.args.get("send", "").strip() in ("1", "true", "yes")
    mode = request.args.get("mode", "market_expansion").strip() or "market_expansion"
    try:
        from analytics import build_marketing_report
        from feishu_util import send_feishu
        conn = get_conn()
        try:
            report = build_marketing_report(conn, STORE_ID, mode=mode)
            send_ok = False
            send_err = None
            if send_feishu_flag:
                send_ok, send_err = send_feishu(report, at_user_id="ou_8db735f2", at_user_name="余为军")
            _save_report_log(conn, report, send_ok, send_err)
            return jsonify({"success": True, "report": report, "feishu_sent": send_feishu_flag, "feishu_ok": send_ok})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/report_history")
def api_report_history():
    """营销报告历史列表，供 AI 分析界面展示"""
    try:
        limit = min(int(request.args.get("limit", "20")), 100)
        conn = get_conn()
        try:
            _ensure_report_log_table(conn)
            cur = conn.cursor()
            cur.execute(
                """SELECT id, report_date, report_time, store_id, feishu_at_user_name, send_status,
                          LEFT(report_content, 200) AS summary, LENGTH(report_content) AS content_len
                   FROM t_htma_report_log
                   ORDER BY report_time DESC
                   LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
            cur.close()
            return jsonify([{
                "id": r["id"],
                "report_date": r["report_date"].isoformat() if r.get("report_date") else None,
                "report_time": r["report_time"].isoformat() if r.get("report_time") else None,
                "store_id": r["store_id"],
                "feishu_at_user_name": r["feishu_at_user_name"],
                "send_status": r["send_status"],
                "summary": r["summary"],
                "content_len": r["content_len"],
            } for r in rows])
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"error": str(e), "items": []}), 500


@app.route("/api/report_history/<int:rid>")
def api_report_detail(rid):
    """获取单条报告全文"""
    try:
        conn = get_conn()
        try:
            _ensure_report_log_table(conn)
            cur = conn.cursor()
            cur.execute(
                """SELECT id, report_date, report_time, store_id, report_content, feishu_at_user_name, send_status
                   FROM t_htma_report_log WHERE id = %s""",
                (rid,),
            )
            r = cur.fetchone()
            cur.close()
            if not r:
                return jsonify({"error": "未找到"}), 404
            return jsonify({
                "id": r["id"],
                "report_date": r["report_date"].isoformat() if r.get("report_date") else None,
                "report_time": r["report_time"].isoformat() if r.get("report_time") else None,
                "store_id": r["store_id"],
                "report_content": r["report_content"],
                "feishu_at_user_name": r["feishu_at_user_name"],
                "send_status": r["send_status"],
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai_chat", methods=["GET", "POST", "OPTIONS"])
def api_ai_chat():
    """AI 对话：基于报告数据返回可操作建议，可扩展接入 LLM。支持 GET（避免 CORS 预检）和 POST"""
    if request.method == "OPTIONS":
        return "", 204
    try:
        if request.method == "GET":
            msg = (request.args.get("message") or "").strip()
        else:
            data = request.get_json(silent=True) or {}
            msg = (data.get("message") or "").strip()
        if not msg:
            return jsonify({"success": False, "reply": "请输入您的问题"}), 400
        from analytics import ai_chat_response, build_marketing_report
        conn = get_conn()
        try:
            try:
                report = build_marketing_report(conn, STORE_ID, mode="market_expansion")
                summary = report[:500] if report else ""
            except Exception:
                summary = ""
            reply = ai_chat_response(conn, msg, report_summary=summary)
            return jsonify({"success": True, "reply": reply})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "reply": "处理失败: " + str(e)}), 500


@app.route("/api/health")
def api_health():
    """健康检查"""
    try:
        conn = get_conn()
        conn.close()
        return jsonify({"status": "ok", "db": "connected"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5002"))
    app.run(host="0.0.0.0", port=port, debug=False)
