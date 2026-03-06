#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
好特卖沈阳超级仓运营看板 - 独立版（不依赖 JimuReport）
直接读取 MySQL htma_dashboard，提供 API 与看板页面。
"""
import os
import urllib.parse
from datetime import date, timedelta, datetime

# 加载 .env（货盘比价、飞书登录等）；多路径、先 dotenv 再逐键解析，确保飞书登录能读到
_env_dir = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
_project_root = os.path.abspath(os.path.join(_env_dir, ".."))
_env_path = os.path.join(_project_root, ".env")
_ENV_KEYS = ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "HTMA_PUBLIC_URL", "FLASK_SECRET_KEY")


def _load_env_from_file(path, force_keys=None):
    """从 path 读 .env，将 _ENV_KEYS 注入 os.environ。force_keys 若给出则强制覆盖这些键。"""
    if not path or not os.path.isfile(path):
        return
    force_set = set(force_keys or [])
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip().strip("\r\n").strip("\r")
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip().lstrip("\ufeff")  # BOM
                key = key.strip()
                val = val.strip().strip("'\"").strip()
                if key not in _ENV_KEYS:
                    continue
                if not val:
                    continue
                if key in force_set or not (os.environ.get(key) or "").strip():
                    os.environ[key] = val
    except Exception:
        pass


def _read_feishu_from_env_file(path):
    """从指定路径的 .env 文件读取飞书配置，返回 (app_id, app_secret)。"""
    out_id, out_secret = "", ""
    if not path or not os.path.isfile(path):
        return out_id, out_secret
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip().strip("\r\n").strip("\r")
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip().lstrip("\ufeff").strip()
                val = val.strip().strip("'\"").strip()
                if key == "FEISHU_APP_ID" and val:
                    out_id = val
                elif key == "FEISHU_APP_SECRET" and val:
                    out_secret = val
    except Exception:
        pass
    return out_id, out_secret


def _read_feishu_from_project_env():
    """从项目根 .env 强制读取飞书配置；多路径尝试（__file__ 与 getcwd）。"""
    cwd = os.getcwd()
    candidates = [
        _env_path,
        os.path.join(cwd, ".env"),
        os.path.abspath(os.path.join(cwd, "..", ".env")),
    ]
    for p in candidates:
        if not p:
            continue
        a, b = _read_feishu_from_env_file(p)
        if a and b:
            return a, b
    return "", ""


try:
    from dotenv import load_dotenv
    load_dotenv(_env_path)
except ImportError:
    pass
# 先强制从项目根 .env 注入飞书相关（覆盖空值），再按原逻辑补其他
_load_env_from_file(_env_path, force_keys=("FEISHU_APP_ID", "FEISHU_APP_SECRET"))
for _p in (_env_path, os.path.join(os.getcwd(), ".env"), os.path.abspath(os.path.join(os.getcwd(), "..", ".env"))):
    _load_env_from_file(_p)
import subprocess
import tempfile
import threading
import pymysql
from db_config import DB_CONFIG, get_conn
from flask import Flask, Response, jsonify, send_from_directory, request, session, redirect
from werkzeug.utils import secure_filename

from import_logic import import_sale_daily, import_sale_summary, import_stock, import_category, import_profit, import_tax_burden, refresh_profit, refresh_category_from_sale, sync_products_table, sync_category_table, preview_sale_excel, import_labor_cost, import_labor_cost_from_image, refresh_labor_cost_analysis, import_product_master
from analytics import build_insights, category_rank_data

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB，避免大 Excel 413
app.config["PROJECT_ROOT"] = _project_root
app.config["ENV_PATH"] = _env_path
# 飞书登录：启动时从项目根 .env 直接读 + os.environ 写入 app.config（保证子进程未继承 env 时也能用）
_direct_id, _direct_secret = _read_feishu_from_project_env()
app.config["FEISHU_APP_ID"] = (_direct_id or (os.environ.get("FEISHU_APP_ID") or "").strip()).strip()
app.config["FEISHU_APP_SECRET"] = (_direct_secret or (os.environ.get("FEISHU_APP_SECRET") or "").strip()).strip()
if not app.config["FEISHU_APP_ID"]:
    for _p in (_env_path, os.path.abspath(os.path.join(os.getcwd(), "..", ".env"))):
        _load_env_from_file(_p)
        app.config["FEISHU_APP_ID"] = (os.environ.get("FEISHU_APP_ID") or "").strip()
        app.config["FEISHU_APP_SECRET"] = (os.environ.get("FEISHU_APP_SECRET") or "").strip()
        if app.config["FEISHU_APP_ID"]:
            break
if not app.config["FEISHU_APP_ID"] and (os.environ.get("FEISHU_APP_ID") or "").strip():
    app.config["FEISHU_APP_ID"] = (os.environ.get("FEISHU_APP_ID") or "").strip()
    app.config["FEISHU_APP_SECRET"] = (os.environ.get("FEISHU_APP_SECRET") or "").strip()
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY") or "htma-dev-secret-change-in-production"
# 登录态：session cookie 同站有效，HTTPS 下可设 SESSION_COOKIE_SECURE=1
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
if os.environ.get("SESSION_COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes"):
    app.config["SESSION_COOKIE_SECURE"] = True
else:
    _pu = (os.environ.get("HTMA_PUBLIC_URL") or os.environ.get("PUBLIC_URL") or "").strip()
    if _pu.lower().startswith("https://"):
        app.config["SESSION_COOKIE_SECURE"] = True


def _auth_enabled():
    """是否启用登录（配置了飞书应用则启用）；优先以 app.config 为准，避免进程未继承 shell 变量"""
    try:
        from auth import is_feishu_configured
        return is_feishu_configured(
            app_id=app.config.get("FEISHU_APP_ID"),
            app_secret=app.config.get("FEISHU_APP_SECRET"),
        )
    except Exception:
        return False


def _parse_id_list(env_name):
    """从环境变量解析以逗号/分号分隔的 open_id / user_id 列表"""
    raw = (os.environ.get(env_name) or "").strip()
    if not raw:
        return set()
    parts = []
    for token in raw.replace(";", ",").split(","):
        t = token.strip()
        if t:
            parts.append(t)
    return set(parts)


def _has_module_access(module, user_id=None):
    """基于环境变量控制模块访问权限。
    - 超级管理员（HTMA_SUPER_ADMIN_OPEN_ID，默认余为军）拥有所有模块权限，便于通过飞书调试
    - HTMA_ADMIN_FEISHU_OPEN_IDS 中的用户也拥有所有模块权限
    - 各模块 env 为空时默认放行
    - module: 'import' | 'labor' | 'profit' | 'product_master'"""
    uid = (user_id or session.get("open_id") or session.get("user_id") or "").strip()
    if not uid:
        return False
    # 超级管理员（余为军等）：拥有全部模块权限，便于飞书登录后调试
    try:
        from auth import _super_admin_open_id
        admin_oid = (_super_admin_open_id() or "").strip()
        if admin_oid:
            def _norm(o):
                return (o or "").strip().replace("ou_", "").lower()
            if _norm(uid) == _norm(admin_oid):
                return True
    except Exception:
        pass
    # 额外管理员列表
    admins = _parse_id_list("HTMA_ADMIN_FEISHU_OPEN_IDS")
    if admins and uid in admins:
        return True
    env_map = {
        "import": "HTMA_IMPORT_ALLOWED_FEISHU_OPEN_IDS",
        "labor": "HTMA_LABOR_ALLOWED_FEISHU_OPEN_IDS",
        "profit": "HTMA_PROFIT_ALLOWED_FEISHU_OPEN_IDS",
        "product_master": "HTMA_PRODUCT_MASTER_ALLOWED_FEISHU_OPEN_IDS",
    }
    env_name = env_map.get(module)
    if not env_name:
        return True
    allowed = _parse_id_list(env_name)
    # 未配置模块白名单时默认放行
    if not allowed:
        return True
    return uid in allowed


def _is_logged_in():
    return bool(session.get("user_id") or session.get("open_id"))


@app.before_request
def _require_auth():
    """未配置登录时放行；已配置则未登录用户只能访问登录页与 auth 接口，必须登录后才能看运营看板"""
    # 从 app.config 回填飞书配置到 os.environ（解决启动时 .env 未加载到进程的情况）
    for _k in ("FEISHU_APP_ID", "FEISHU_APP_SECRET"):
        _v = (app.config.get(_k) or "").strip()
        if _v and not (os.environ.get(_k) or "").strip():
            os.environ[_k] = _v
    if not _auth_enabled():
        return None
    path = request.path.rstrip("/") or "/"
    # 放行：根路径（由路由内根据是否登录决定展示登录页或看板）、登录页、auth 回调、auth 接口、健康检查、静态资源
    if path == "/":
        return None
    if path == "/login":
        return None
    if path.startswith("/api/auth/"):
        return None
    if path == "/api/health":
        return None
    if path == "/api/date_range":
        return None
    if path == "/labor" or path == "/labor_analysis":
        return None
    # 人力成本：状态与主数据接口未登录也可读，便于点击 Tab 后直接展示（数据为内部经营用）
    if path == "/api/labor_cost_status" or path == "/api/labor_cost" or path == "/api/labor_cost_analysis":
        return None
    if path.startswith("/api/labor_analysis/"):
        return None
    if path.startswith("/static/") or (path != "/" and not path.startswith("/api/") and "." in path.split("/")[-1]):
        return None
    if _is_logged_in():
        return None
    # 未登录：页面请求重定向到登录页，API 返回 401
    if path in ("/import", "/product_master") or path.startswith("/api/"):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "请先登录", "login_required": True}), 401
        return redirect("/login?next=" + (urllib.parse.quote(request.url) if request.url else "/"))
    return None


@app.after_request
def add_cors_headers(response):
    """允许跨域，便于 Cursor 预览、OpenClaw 等不同源访问"""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/api/category_rank_mid", methods=["GET", "HEAD"])
def api_category_rank_mid():
    """品类排行-中类列表：按大类返回中类汇总（羽绒服、夹克等）。需传 category_large_code 或 category_large"""
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
                SELECT COALESCE(NULLIF(TRIM(category_mid), ''), '未分类') AS category_mid,
                       COALESCE(NULLIF(TRIM(category_mid_code), ''), NULLIF(TRIM(category_mid), ''), '') AS category_mid_code,
                       SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}{large_cond}
                  AND (COALESCE(TRIM(category_mid), '') != '' OR COALESCE(TRIM(category_mid_code), '') != '')
                GROUP BY category_mid, category_mid_code
                ORDER BY total_sale DESC
                LIMIT 100
            """, params)
            rows = cur.fetchall()
        out = []
        for i, r in enumerate(rows, 1):
            sale = float(r["total_sale"] or 0)
            profit = float(r["total_profit"] or 0)
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "rank": i,
                "category_mid": r.get("category_mid") or "未分类",
                "category_mid_code": r.get("category_mid_code") or "",
                "sale_amount": round(sale, 2),
                "profit_amount": round(profit, 2),
                "margin_pct": round(margin, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


@app.route("/api/category_rank_small", methods=["GET", "HEAD"])
def api_category_rank_small():
    """品类排行-小类列表：按大类+中类返回小类明细。需传 category_large_code、category_mid_code 或 category_mid"""
    category_large_code = request.args.get("category_large_code", "").strip() or request.args.get("category_large", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip() or request.args.get("category_mid", "").strip()
    if not category_large_code:
        return jsonify([])
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    large_cond = " AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)"
    mid_cond = " AND (COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)" if category_mid_code else ""
    params = (STORE_ID,) + date_params + profit_cat_params + (category_large_code, category_large_code)
    if category_mid_code:
        params = params + (category_mid_code, category_mid_code)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(category, '未分类') AS category_small,
                       MAX(COALESCE(NULLIF(TRIM(category_small_code), ''), NULLIF(TRIM(category_code), ''), '')) AS category_small_code,
                       SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit
                FROM t_htma_profit
                WHERE store_id = %s AND {date_cond}{profit_cat_cond}{large_cond}{mid_cond}
                GROUP BY category
                ORDER BY total_sale DESC
                LIMIT 200
            """, params)
            rows = cur.fetchall()
        out = []
        for i, r in enumerate(rows, 1):
            sale = float(r["total_sale"] or 0)
            profit = float(r["total_profit"] or 0)
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "rank": i,
                "category_small": r.get("category_small") or r.get("category") or "未分类",
                "category_small_code": r.get("category_small_code") or "",
                "sale_amount": round(sale, 2),
                "profit_amount": round(profit, 2),
                "margin_pct": round(margin, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


@app.route("/api/consumer_insight", methods=["GET", "POST", "HEAD", "OPTIONS"])
def api_consumer_insight():
    """消费洞察：概览、品类/品牌/价格带/经销方式/新品。GET/POST 均支持，参数从 query 取，便于代理只放行 POST 时使用。"""
    if request.method in ("OPTIONS", "HEAD"):
        return "", 204 if request.method == "OPTIONS" else 200
    try:
        data = _get_consumer_insight_data()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e), "overview": {}, "category_matrix": [], "category_top_sale": [], "category_top_profit": [], "category_top_margin": [], "brand": [], "price_band": [], "supplier": [], "top_sku": [], "distribution": [], "new_product": {}, "return_rate_pct": 0, "return_by_cat": [], "color_style": {}, "period_over_period": {}, "date_range": "", "discount_band": [], "zero_sale_skus": [], "high_discount_low_margin": []}), 500


@app.route("/api/<path:path>", methods=["OPTIONS"])
def api_options(path):
    """CORS 预检"""
    return "", 204


def _get_tax_burden_data():
    """税率计算数据：按税率汇总 销售额、不含税、税额。返回 dict 或抛出异常。"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT 1 FROM t_htma_tax_burden LIMIT 1")
            except Exception:
                return {
                    "total_sale_amount": 0, "total_tax_amount": 0, "tax_rate_pct": 0,
                    "by_tax_rate": [], "date_range": "",
                    "message": "请先导入税率负担表并执行 scripts/12_create_tax_burden_table.sql",
                }
            # 按税率汇总：每行取匹配到的税率，计算税额；再在 Python 里按税率分组得 销售额、不含税、税额
            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(TRIM(s.category_large), ''), NULLIF(TRIM(s.category_mid), ''), NULLIF(TRIM(s.category_small), ''), NULLIF(TRIM(s.category), ''), '未分类') AS category_display,
                    SUM(s.sale_amount) AS sale_amount,
                    COALESCE(
                        (SELECT tb.tax_rate FROM t_htma_category c JOIN t_htma_tax_burden tb ON tb.code = c.category_small_code WHERE TRIM(COALESCE(c.category_small,'')) != '' AND c.category_small = COALESCE(s.category_small, s.category) LIMIT 1),
                        (SELECT tb.tax_rate FROM t_htma_category c JOIN t_htma_tax_burden tb ON tb.code = c.category_mid_code WHERE TRIM(COALESCE(c.category_mid,'')) != '' AND c.category_mid = COALESCE(s.category_mid, s.category) LIMIT 1),
                        (SELECT tb.tax_rate FROM t_htma_category c JOIN t_htma_tax_burden tb ON tb.code = c.category_large_code WHERE TRIM(COALESCE(c.category_large,'')) != '' AND c.category_large = COALESCE(s.category_large, s.category) LIMIT 1),
                        0
                    ) AS tax_rate
                FROM t_htma_sale s
                WHERE s.store_id = %s AND {date_cond}{category_cond}
                GROUP BY category_display, tax_rate
                ORDER BY sale_amount DESC
            """, params)
            rows = cur.fetchall()
        # 按税率分组汇总，并保留各税率下的品类明细（销售额、不含税、税额）
        rate_map = {}
        for r in rows:
            sale_amt = float(r["sale_amount"] or 0)
            rate = float(r["tax_rate"] or 0)
            key = round(rate, 4)
            if key not in rate_map:
                rate_map[key] = {"sale_amount": 0, "tax_amount": 0, "categories": []}
            # 税额 = 销售额 - 销售额/(1+税率)
            if rate >= 0 and rate < 1:
                excl = sale_amt / (1 + rate)
                tax_row = round(sale_amt - excl, 2)
            else:
                tax_row = round(sale_amt * rate, 2)
            rate_map[key]["sale_amount"] += sale_amt
            rate_map[key]["tax_amount"] += tax_row
            rate_map[key]["categories"].append({
                "category": (r["category_display"] or "未分类").strip(),
                "sale_amount": round(sale_amt, 2),
                "amount_excluding_tax": round(sale_amt - tax_row, 2),
                "tax_amount": tax_row,
            })
        by_tax_rate = []
        total_sale = 0.0
        total_tax = 0.0
        for rate in sorted(rate_map.keys(), reverse=True):
            sale_amt = round(rate_map[rate]["sale_amount"], 2)
            tax_amt = round(rate_map[rate]["tax_amount"], 2)
            excl_amt = round(sale_amt - tax_amt, 2)
            total_sale += sale_amt
            total_tax += tax_amt
            # 品类明细按税额从高到低排序
            cats = sorted(rate_map[rate]["categories"], key=lambda x: -(x["tax_amount"] or 0))
            by_tax_rate.append({
                "tax_rate": rate,
                "tax_rate_pct": round(rate * 100, 2),
                "sale_amount": sale_amt,
                "amount_excluding_tax": excl_amt,
                "tax_amount": tax_amt,
                "by_category": cats,
            })
        tax_rate_pct = round((total_tax / total_sale * 100), 2) if total_sale else 0
        start_d = request.args.get("start_date", "").strip()
        end_d = request.args.get("end_date", "").strip()
        period = request.args.get("period", "recent30")
        date_range = f"{start_d} ~ {end_d}" if (start_d and end_d) else {"day": "今日", "week": "本周", "month": "本月", "recent30": "近30天"}.get(period, "近30天")
        return {
            "total_sale_amount": round(total_sale, 2),
            "total_tax_amount": round(total_tax, 2),
            "tax_rate_pct": tax_rate_pct,
            "by_tax_rate": by_tax_rate,
            "date_range": date_range,
        }
    except Exception as e:
        raise
    finally:
        conn.close()


@app.route("/api/tax_burden_summary", methods=["GET", "HEAD", "OPTIONS"])
def api_tax_burden_summary():
    """税率计算：按税率汇总 销售额、不含税、税额。GET 返回 JSON；OPTIONS 返回 204 避免 405。"""
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "HEAD":
        return "", 200
    try:
        data = _get_tax_burden_data()
        return jsonify(data)
    except Exception as e:
        return jsonify({"total_sale_amount": 0, "total_tax_amount": 0, "tax_rate_pct": 0, "by_tax_rate": [], "date_range": "", "error": str(e)}), 500


@app.route("/api/tax_burden_export", methods=["GET"])
def api_tax_burden_export():
    """导出税率汇总：format=csv 返回 Excel 可打开的 CSV；format=pdf 返回 HTML 供打印为 PDF。"""
    fmt = request.args.get("format", "csv").strip().lower()
    try:
        data = _get_tax_burden_data()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    if data.get("message") and not data.get("by_tax_rate"):
        return jsonify({"success": False, "message": data.get("message")}), 400
    by_tax_rate = data.get("by_tax_rate") or []
    date_range = data.get("date_range", "")
    total_sale = data.get("total_sale_amount", 0)
    total_tax = data.get("total_tax_amount", 0)
    total_excl = round(total_sale - total_tax, 2)

    if fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        buf.write("\ufeff")
        w = csv.writer(buf)
        w.writerow(["税率", "销售额", "不含税", "税额"])
        for row in by_tax_rate:
            w.writerow([
                str(row.get("tax_rate_pct", 0)) + "%",
                row.get("sale_amount", 0),
                row.get("amount_excluding_tax", 0),
                row.get("tax_amount", 0),
            ])
        w.writerow(["合计", total_sale, total_excl, total_tax])
        fname = f"税率负担汇总_{date_range.replace(' ', '').replace('~', '-')}.csv"
        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"},
        )
    if fmt == "pdf" or fmt == "html":
        def _num(x):
            if x is None:
                return "0.00"
            try:
                return "{:,.2f}".format(float(x))
            except (TypeError, ValueError):
                return "0.00"
        rows_html = "".join(
            "<tr><td>{}%</td><td class='num'>{}</td><td class='num'>{}</td><td class='num'>{}</td></tr>".format(
                row.get("tax_rate_pct", 0), _num(row.get("sale_amount")), _num(row.get("amount_excluding_tax")), _num(row.get("tax_amount"))
            )
            for row in by_tax_rate
        )
        safe_date_range = str(date_range).replace("<", "&lt;").replace(">", "&gt;") if date_range else ""
        export_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        html = (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>税率负担汇总</title>"
            "<style>body{font-family:system-ui,sans-serif;margin:24px;} table{border-collapse:collapse;width:100%;} th,td{border:1px solid #333;padding:8px;text-align:left;} th{background:#eee;} .num{text-align:right;} @media print{body{margin:12px;}}</style></head><body>"
            "<h2>税率负担汇总（" + safe_date_range + "）</h2>"
            "<table><thead><tr><th>税率</th><th class=\"num\">销售额</th><th class=\"num\">不含税</th><th class=\"num\">税额</th></tr></thead><tbody>"
            + rows_html +
            "<tr><th>合计</th><td class=\"num\">" + _num(total_sale) + "</td><td class=\"num\">" + _num(total_excl) + "</td><td class=\"num\">" + _num(total_tax) + "</td></tr>"
            "</tbody></table><p style=\"margin-top:16px;color:#666;\">导出时间：" + export_time + " · 使用浏览器「打印」→「另存为 PDF」保存为 PDF。</p></body></html>"
        )
        if fmt == "pdf":
            return Response(html, mimetype="text/html; charset=utf-8", headers={"Content-Disposition": "inline; filename=tax_summary.html"})
        return Response(html, mimetype="text/html; charset=utf-8")
    return jsonify({"success": False, "error": "format 仅支持 csv 或 pdf"}), 400


def _get_consumer_insight_data():
    """消费洞察：概览 KPI、品类贡献、品牌贡献、价格带、经销方式、新品表现。与经营分析/税率同周期。"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        category_matrix = []
        discount_band = []
        zero_sale_skus = []
        high_discount_low_margin = []
        # 1. 概览
        cur.execute(f"""
            SELECT
                COALESCE(SUM(sale_amount), 0) AS total_sale,
                COALESCE(SUM(gross_profit), 0) AS total_profit,
                COUNT(DISTINCT sku_code) AS sku_sold,
                COALESCE(SUM(sale_qty), 0) AS total_qty
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
        """, params)
        row = cur.fetchone()
        total_sale = float(row.get("total_sale") or 0)
        total_profit = float(row.get("total_profit") or 0)
        sku_sold = int(row.get("sku_sold") or 0)
        total_qty = float(row.get("total_qty") or 0)
        margin_pct = (total_profit / total_sale * 100) if total_sale > 0 else 0
        unit_price = (total_sale / total_qty) if total_qty > 0 else 0
        # 商品主数据总数（动销率分母）
        cur.execute("SELECT COUNT(*) AS c FROM t_htma_product_master WHERE store_id = %s", (STORE_ID,))
        r2 = cur.fetchone()
        sku_total = int(r2.get("c") or 0)
        sell_through_pct = (sku_sold / sku_total * 100) if sku_total > 0 else None
        # 平均零售价（商品主数据）
        cur.execute("SELECT AVG(retail_price) AS avg_retail FROM t_htma_product_master WHERE store_id = %s AND COALESCE(retail_price, 0) > 0", (STORE_ID,))
        r_retail = cur.fetchone()
        avg_retail_price = round(float(r_retail.get("avg_retail") or 0), 2) if r_retail and r_retail.get("avg_retail") else None
        # 库存周转天数（近期库存/日均销量）
        try:
            cur.execute("SELECT COALESCE(SUM(stock_qty), 0) AS total_stock FROM t_htma_stock WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)", (STORE_ID, STORE_ID))
            stock_row = cur.fetchone()
            total_stock = float(stock_row.get("total_stock") or 0)
            interval_days = max(1, int(params[1]) if len(params) > 1 and isinstance(params[1], (int, float)) else 30)
            daily_sale_qty = total_qty / interval_days if interval_days else 0
            inventory_turnover_days = round(total_stock / daily_sale_qty, 1) if daily_sale_qty > 0 and total_stock >= 0 else None
        except Exception:
            inventory_turnover_days = None
        s_date_cond = date_cond.replace("data_date", "s.data_date")
        overview = {
            "total_sale": round(total_sale, 2),
            "total_profit": round(total_profit, 2),
            "margin_pct": round(margin_pct, 2),
            "sku_sold": sku_sold,
            "sku_total": sku_total,
            "sell_through_pct": round(sell_through_pct, 2) if sell_through_pct is not None else None,
            "unit_price": round(unit_price, 2),
            "avg_retail_price": avg_retail_price,
            "inventory_turnover_days": inventory_turnover_days,
        }
        # 2. 品类贡献矩阵（单表：动销SKU、销售额、占比、毛利、毛利率、平均售价、平均折扣率）+ Top 列表供图表
        cur.execute(f"""
            SELECT
                COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category_mid), ''), NULLIF(TRIM(category), ''), '未分类') AS cat,
                COUNT(DISTINCT sku_code) AS sku_sold,
                SUM(sale_amount) AS sale_amount,
                SUM(gross_profit) AS profit,
                CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct,
                AVG(sale_price) AS avg_sale_price
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
            GROUP BY cat
            HAVING SUM(sale_amount) > 0
            ORDER BY sale_amount DESC
            LIMIT 20
        """, params)
        cat_matrix_rows = cur.fetchall()
        total_sale_for_contrib = total_sale or 1
        category_matrix = []
        for r in cat_matrix_rows:
            cat = r.get("cat") or "未分类"
            sale_amt = float(r.get("sale_amount") or 0)
            category_matrix.append({
                "category": cat,
                "sku_sold": int(r.get("sku_sold") or 0),
                "sale_amount": round(sale_amt, 2),
                "sale_contrib_pct": round(sale_amt / total_sale_for_contrib * 100, 2),
                "profit": round(float(r.get("profit") or 0), 2),
                "margin_pct": round(float(r.get("margin_pct") or 0), 2),
                "avg_sale_price": round(float(r.get("avg_sale_price") or 0), 2),
                "avg_discount_pct": None,
            })
        # 品类平均折扣率（按品类 join 主数据）
        try:
            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(TRIM(s.category_large), ''), NULLIF(TRIM(s.category_mid), ''), NULLIF(TRIM(s.category), ''), '未分类') AS cat,
                    SUM(s.sale_amount * (1 - s.sale_price / NULLIF(m.list_price, 0))) / NULLIF(SUM(s.sale_amount), 0) * 100 AS avg_discount_pct
                FROM t_htma_sale s
                INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND COALESCE(m.list_price, 0) > 0
                WHERE s.store_id = %s AND {s_date_cond}
                GROUP BY cat
            """, params)
            for row in cur.fetchall():
                c = row.get("cat") or "未分类"
                for cm in category_matrix:
                    if cm["category"] == c:
                        cm["avg_discount_pct"] = round(float(row.get("avg_discount_pct") or 0), 2)
                        break
        except Exception:
            pass
        category_top_sale = [{"category": c["category"], "sale_amount": c["sale_amount"], "profit": c["profit"], "margin_pct": c["margin_pct"]} for c in category_matrix[:10]]
        category_top_profit = sorted([{"category": c["category"], "sale_amount": c["sale_amount"], "profit": c["profit"], "margin_pct": c["margin_pct"]} for c in category_matrix], key=lambda x: x["profit"], reverse=True)[:10]
        category_top_margin = sorted([{"category": c["category"], "sale_amount": c["sale_amount"], "profit": c["profit"], "margin_pct": c["margin_pct"]} for c in category_matrix if c["margin_pct"] > 0], key=lambda x: x["margin_pct"], reverse=True)[:5]
        # 3. 品牌贡献（含 sku_sold 供气泡图）
        cur.execute(f"""
            SELECT
                COALESCE(NULLIF(TRIM(brand_name), ''), '未分类') AS brand,
                COUNT(DISTINCT sku_code) AS sku_sold,
                SUM(sale_amount) AS sale_amount,
                SUM(gross_profit) AS profit,
                SUM(sale_qty) AS qty,
                CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
            GROUP BY brand
            HAVING SUM(sale_amount) > 0
            ORDER BY sale_amount DESC
            LIMIT 30
        """, params)
        brand_rows = cur.fetchall()
        brand = [{"brand": r.get("brand") or "未分类", "sku_sold": int(r.get("sku_sold") or 0), "sale_amount": round(float(r.get("sale_amount") or 0), 2), "profit": round(float(r.get("profit") or 0), 2), "qty": round(float(r.get("qty") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2), "contrib_pct": round(float(r.get("sale_amount") or 0) / total_sale_for_contrib * 100, 2)} for r in brand_rows]
        # 4. 价格带（按实际售价分段）
        cur.execute(f"""
            SELECT
                CASE
                    WHEN COALESCE(sale_price, 0) <= 0 THEN '0'
                    WHEN sale_price < 50 THEN '1-49'
                    WHEN sale_price < 100 THEN '50-99'
                    WHEN sale_price < 200 THEN '100-199'
                    WHEN sale_price < 500 THEN '200-499'
                    WHEN sale_price < 1000 THEN '500-999'
                    ELSE '1000+'
                END AS band,
                SUM(sale_amount) AS sale_amount,
                SUM(sale_qty) AS qty,
                CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
            GROUP BY band
            ORDER BY FIELD(band, '0', '1-49', '50-99', '100-199', '200-499', '500-999', '1000+')
        """, params)
        price_rows = cur.fetchall()
        total_qty_for_band = total_qty or 1
        price_band = [{"band": r.get("band") or "0", "sale_amount": round(float(r.get("sale_amount") or 0), 2), "qty": round(float(r.get("qty") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2)} for r in price_rows]
        for pb in price_band:
            pb["sale_contrib_pct"] = round(pb["sale_amount"] / total_sale_for_contrib * 100, 2) if total_sale > 0 else 0
            pb["qty_contrib_pct"] = round(pb["qty"] / total_qty_for_band * 100, 2) if total_qty > 0 else 0
        # 4b. 供应商贡献（与品牌同维）
        cur.execute(f"""
            SELECT
                COALESCE(NULLIF(TRIM(supplier_name), ''), '未填') AS supplier,
                SUM(sale_amount) AS sale_amount,
                SUM(gross_profit) AS profit,
                SUM(sale_qty) AS qty,
                CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
            GROUP BY supplier
            HAVING SUM(sale_amount) > 0
            ORDER BY sale_amount DESC
            LIMIT 20
        """, params)
        supplier_rows = cur.fetchall()
        supplier = [{"supplier": r.get("supplier") or "未填", "sale_amount": round(float(r.get("sale_amount") or 0), 2), "profit": round(float(r.get("profit") or 0), 2), "qty": round(float(r.get("qty") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2), "contrib_pct": round(float(r.get("sale_amount") or 0) / total_sale_for_contrib * 100, 2)} for r in supplier_rows]
        # 4c. 单品销售 Top20（SKU 维度）
        cur.execute(f"""
            SELECT
                sku_code,
                COALESCE(NULLIF(TRIM(product_name), ''), sku_code) AS product_name,
                SUM(sale_amount) AS sale_amount,
                SUM(gross_profit) AS profit,
                SUM(sale_qty) AS qty,
                CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
            GROUP BY sku_code, product_name
            HAVING SUM(sale_amount) > 0
            ORDER BY sale_amount DESC
            LIMIT 20
        """, params)
        sku_rows = cur.fetchall()
        top_sku = [{"sku_code": r.get("sku_code") or "", "product_name": (r.get("product_name") or "")[:40], "sale_amount": round(float(r.get("sale_amount") or 0), 2), "profit": round(float(r.get("profit") or 0), 2), "qty": round(float(r.get("qty") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2)} for r in sku_rows]
        # 4d. 平均折扣率（sale 关联 product_master.list_price，有划线价的记录）
        try:
            cur.execute(f"""
                SELECT
                    SUM(s.sale_amount) AS sale_with_list,
                    SUM(s.sale_qty) AS qty_with_list,
                    SUM(s.sale_amount * (1 - s.sale_price / NULLIF(m.list_price, 0))) / NULLIF(SUM(s.sale_amount), 0) * 100 AS avg_discount_pct
                FROM t_htma_sale s
                INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND COALESCE(m.list_price, 0) > 0 AND s.sale_price <= m.list_price
                WHERE s.store_id = %s AND {s_date_cond}
            """, params)
            dr = cur.fetchone()
            if dr and float(dr.get("sale_with_list") or 0) > 0:
                avg_discount_pct = round(float(dr.get("avg_discount_pct") or 0), 2)
            else:
                avg_discount_pct = None
        except Exception:
            avg_discount_pct = None
        overview["avg_discount_pct"] = avg_discount_pct
        # 5. 经销方式（关联商品主数据，仅按日期筛选）
        try:
            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(TRIM(m.distribution_mode), ''), '未分类') AS mode_name,
                    SUM(s.sale_amount) AS sale_amount,
                    SUM(s.gross_profit) AS profit,
                    CASE WHEN SUM(s.sale_amount) > 0 THEN SUM(s.gross_profit)/SUM(s.sale_amount)*100 ELSE 0 END AS margin_pct
                FROM t_htma_sale s
                LEFT JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id
                WHERE s.store_id = %s AND {s_date_cond}
                GROUP BY mode_name
                HAVING SUM(s.sale_amount) > 0
                ORDER BY sale_amount DESC
            """, params)
        except Exception:
            cur.execute(f"""
                SELECT
                    '购销' AS mode_name,
                    SUM(sale_amount) AS sale_amount,
                    SUM(gross_profit) AS profit,
                    CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}
            """, params)
        dist_rows = cur.fetchall()
        distribution = [{"mode": r.get("mode_name") or "未分类", "sale_amount": round(float(r.get("sale_amount") or 0), 2), "profit": round(float(r.get("profit") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2), "contrib_pct": round(float(r.get("sale_amount") or 0) / total_sale_for_contrib * 100, 2)} for r in dist_rows]
        # 6. 新品表现（关联商品主数据 product_status=新品）
        try:
            cur.execute(f"""
                SELECT
                    SUM(s.sale_amount) AS new_sale,
                    SUM(s.gross_profit) AS new_profit,
                    COUNT(DISTINCT s.sku_code) AS new_sku_sold
                FROM t_htma_sale s
                INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND TRIM(COALESCE(m.product_status,'')) = '新品'
                WHERE s.store_id = %s AND {s_date_cond}
            """, params)
            nr = cur.fetchone()
            new_sale = float(nr.get("new_sale") or 0)
            new_profit = float(nr.get("new_profit") or 0)
            new_sku_sold = int(nr.get("new_sku_sold") or 0)
            cur.execute("SELECT COUNT(*) AS c FROM t_htma_product_master WHERE store_id = %s AND TRIM(COALESCE(product_status,'')) = '新品'", (STORE_ID,))
            new_sku_total = int(cur.fetchone().get("c") or 0)
        except Exception:
            new_sale = new_profit = 0
            new_sku_sold = new_sku_total = 0
        new_product = {
            "new_sale": round(new_sale, 2),
            "new_profit": round(new_profit, 2),
            "new_sale_contrib_pct": round(new_sale / total_sale_for_contrib * 100, 2) if total_sale > 0 else 0,
            "new_margin_pct": round(new_profit / new_sale * 100, 2) if new_sale > 0 else 0,
            "new_sku_sold": new_sku_sold,
            "new_sku_total": new_sku_total,
            "new_sell_through_pct": round(new_sku_sold / new_sku_total * 100, 2) if new_sku_total > 0 else None,
        }
        # 6b. 老品销售额占比（非新品）
        old_sale = total_sale - new_sale
        new_product["old_sale_contrib_pct"] = round(old_sale / total_sale_for_contrib * 100, 2) if total_sale > 0 else 0
        # 7. 退货率（整体 + 按品类）
        cur.execute(f"""
            SELECT
                COALESCE(SUM(return_amount), 0) AS total_return,
                COALESCE(SUM(return_qty), 0) AS total_return_qty
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
        """, params)
        ret_row = cur.fetchone()
        total_return = float(ret_row.get("total_return") or 0)
        return_rate_pct = round(total_return / total_sale_for_contrib * 100, 2) if total_sale > 0 else 0
        cur.execute(f"""
            SELECT
                COALESCE(NULLIF(TRIM(category_large), ''), NULLIF(TRIM(category_mid), ''), NULLIF(TRIM(category), ''), '未分类') AS cat,
                SUM(sale_amount) AS sale_amount,
                SUM(return_amount) AS return_amount,
                CASE WHEN SUM(sale_amount) > 0 THEN SUM(return_amount)/SUM(sale_amount)*100 ELSE 0 END AS return_rate_pct
            FROM t_htma_sale
            WHERE store_id = %s AND {date_cond}{category_cond}
            GROUP BY cat
            HAVING SUM(sale_amount) > 0 AND SUM(return_amount) > 0
            ORDER BY return_amount DESC
            LIMIT 10
        """, params)
        return_by_cat = [{"category": r.get("cat") or "未分类", "sale_amount": round(float(r.get("sale_amount") or 0), 2), "return_amount": round(float(r.get("return_amount") or 0), 2), "return_rate_pct": round(float(r.get("return_rate_pct") or 0), 2)} for r in cur.fetchall()]
        # 8. 色系/风格（有字段则查）
        color_style = {}
        try:
            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(TRIM(color_system), ''), '未填') AS k,
                    SUM(sale_amount) AS sale_amount,
                    CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}
                GROUP BY k HAVING SUM(sale_amount) > 0 ORDER BY sale_amount DESC LIMIT 10
            """, params)
            color_style["color_system"] = [{"name": r.get("k") or "未填", "sale_amount": round(float(r.get("sale_amount") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2)} for r in cur.fetchall()]
        except Exception:
            color_style["color_system"] = []
        try:
            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(TRIM(style), ''), '未填') AS k,
                    SUM(sale_amount) AS sale_amount,
                    CASE WHEN SUM(sale_amount) > 0 THEN SUM(gross_profit)/SUM(sale_amount)*100 ELSE 0 END AS margin_pct
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond}
                GROUP BY k HAVING SUM(sale_amount) > 0 ORDER BY sale_amount DESC LIMIT 10
            """, params)
            color_style["style"] = [{"name": r.get("k") or "未填", "sale_amount": round(float(r.get("sale_amount") or 0), 2), "margin_pct": round(float(r.get("margin_pct") or 0), 2)} for r in cur.fetchall()]
        except Exception:
            color_style["style"] = []
        # 8b. 折扣区间分析（0-10%、10-20%、20-30%、30%+）
        discount_band = []
        try:
            cur.execute(f"""
                SELECT
                    CASE
                        WHEN (1 - s.sale_price / NULLIF(m.list_price, 0)) * 100 < 0 THEN '0-10%'
                        WHEN (1 - s.sale_price / NULLIF(m.list_price, 0)) * 100 < 10 THEN '0-10%'
                        WHEN (1 - s.sale_price / NULLIF(m.list_price, 0)) * 100 < 20 THEN '10-20%'
                        WHEN (1 - s.sale_price / NULLIF(m.list_price, 0)) * 100 < 30 THEN '20-30%'
                        ELSE '30%+'
                    END AS band,
                    COUNT(DISTINCT s.sku_code) AS sku_cnt,
                    SUM(s.sale_amount) AS sale_amount,
                    SUM(s.gross_profit) AS profit,
                    SUM(s.sale_qty) AS qty,
                    CASE WHEN SUM(s.sale_amount) > 0 THEN SUM(s.gross_profit)/SUM(s.sale_amount)*100 ELSE 0 END AS margin_pct
                FROM t_htma_sale s
                INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND COALESCE(m.list_price, 0) > 0
                WHERE s.store_id = %s AND {s_date_cond}
                GROUP BY band
                ORDER BY FIELD(band, '0-10%', '10-20%', '20-30%', '30%+')
            """, params)
            for r in cur.fetchall():
                discount_band.append({
                    "band": r.get("band") or "0-10%",
                    "sku_cnt": int(r.get("sku_cnt") or 0),
                    "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                    "profit": round(float(r.get("profit") or 0), 2),
                    "qty": round(float(r.get("qty") or 0), 2),
                    "margin_pct": round(float(r.get("margin_pct") or 0), 2),
                })
        except Exception:
            pass
        # 8c. 零销售商品（主数据中有、本周期内无销售的 SKU，限 100 条）
        try:
            store_id = params[0] if params else STORE_ID
            use_date_range = len(params) >= 3 and isinstance(params[1], str) and isinstance(params[2], str) and "-" in str(params[1]) and "-" in str(params[2])
            if use_date_range:
                cur.execute("""
                    SELECT pm.sku_code, pm.product_name, pm.category_name, pm.brand_name, pm.retail_price
                    FROM t_htma_product_master pm
                    LEFT JOIN (SELECT DISTINCT sku_code FROM t_htma_sale WHERE store_id = %s AND data_date BETWEEN %s AND %s) s ON pm.sku_code = s.sku_code
                    WHERE pm.store_id = %s AND s.sku_code IS NULL
                    LIMIT 100
                """, (store_id, params[1], params[2], store_id))
            else:
                interval_days = int(params[1]) if len(params) > 1 and isinstance(params[1], (int, float)) else 30
                cur.execute("""
                    SELECT pm.sku_code, pm.product_name, pm.category_name, pm.brand_name, pm.retail_price
                    FROM t_htma_product_master pm
                    LEFT JOIN (SELECT DISTINCT sku_code FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)) s ON pm.sku_code = s.sku_code
                    WHERE pm.store_id = %s AND s.sku_code IS NULL
                    LIMIT 100
                """, (store_id, interval_days, store_id))
            for r in cur.fetchall():
                zero_sale_skus.append({
                    "sku_code": r.get("sku_code") or "",
                    "product_name": (r.get("product_name") or "")[:50],
                    "category_name": (r.get("category_name") or "")[:32],
                    "brand_name": (r.get("brand_name") or "")[:32],
                    "retail_price": round(float(r.get("retail_price") or 0), 2),
                })
        except Exception:
            pass
        # 8d. 高折扣低毛利（平均折扣>30% 且 毛利率<10%，按 SKU 汇总取前 50）
        high_discount_low_margin = []
        try:
            cur.execute(f"""
                SELECT
                    s.sku_code,
                    MAX(s.product_name) AS product_name,
                    SUM(s.sale_amount) AS sale_amount,
                    SUM(s.gross_profit) AS profit,
                    CASE WHEN SUM(s.sale_amount) > 0 THEN SUM(s.gross_profit)/SUM(s.sale_amount)*100 ELSE 0 END AS margin_pct,
                    AVG((1 - s.sale_price / NULLIF(m.list_price, 0)) * 100) AS avg_discount_pct
                FROM t_htma_sale s
                INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND COALESCE(m.list_price, 0) > 0
                WHERE s.store_id = %s AND {s_date_cond}
                GROUP BY s.sku_code
                HAVING margin_pct < 10 AND avg_discount_pct > 30
                ORDER BY sale_amount DESC
                LIMIT 50
            """, params)
            for r in cur.fetchall():
                high_discount_low_margin.append({
                    "sku_code": r.get("sku_code") or "",
                    "product_name": (r.get("product_name") or "")[:40],
                    "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                    "profit": round(float(r.get("profit") or 0), 2),
                    "margin_pct": round(float(r.get("margin_pct") or 0), 2),
                    "avg_discount_pct": round(float(r.get("avg_discount_pct") or 0), 2),
                })
        except Exception:
            try:
                cur.execute(f"""
                    SELECT s.sku_code, MAX(s.product_name) AS product_name, SUM(s.sale_amount) AS sale_amount, SUM(s.gross_profit) AS profit,
                    CASE WHEN SUM(s.sale_amount) > 0 THEN SUM(s.gross_profit)/SUM(s.sale_amount)*100 ELSE 0 END AS margin_pct
                    FROM t_htma_sale s
                    INNER JOIN t_htma_product_master m ON m.sku_code = s.sku_code AND m.store_id = s.store_id AND COALESCE(m.list_price, 0) > 0
                    WHERE s.store_id = %s AND {s_date_cond} AND s.sale_price <= m.list_price * 0.7
                    GROUP BY s.sku_code
                    HAVING margin_pct < 10
                    ORDER BY sale_amount DESC LIMIT 50
                """, params)
                for r in cur.fetchall():
                    high_discount_low_margin.append({
                        "sku_code": r.get("sku_code") or "",
                        "product_name": (r.get("product_name") or "")[:40],
                        "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                        "profit": round(float(r.get("profit") or 0), 2),
                        "margin_pct": round(float(r.get("margin_pct") or 0), 2),
                    })
            except Exception:
                pass
        # 9. 环比趋势（本期 vs 上期同长度：近30天则对比前30天）
        period_over_period = {}
        try:
            interval_days = int(params[1]) if len(params) > 1 and isinstance(params[1], (int, float)) else 30
            if interval_days >= 1:
                cur.execute("""
                    SELECT COALESCE(SUM(sale_amount), 0) AS prev_sale
                    FROM t_htma_sale
                    WHERE store_id = %s AND data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL %s DAY) AND DATE_SUB(CURDATE(), INTERVAL %s DAY)
                """, (STORE_ID, interval_days * 2, interval_days + 1))
                prev_row = cur.fetchone()
                prev_sale = float(prev_row.get("prev_sale") or 0)
                pct_change = round((total_sale - prev_sale) / prev_sale * 100, 2) if prev_sale > 0 else None
                period_over_period = {"prev_sale": round(prev_sale, 2), "pct_change": pct_change}
        except Exception:
            period_over_period = {}
        # 日期范围文案（与税率计算一致：自定义用 start_date~end_date，否则用 period 标签）
        start_d = (request.args.get("start_date") or "").strip()
        end_d = (request.args.get("end_date") or "").strip()
        period = request.args.get("period", "recent30")
        date_range = f"{start_d} ~ {end_d}" if (start_d and end_d) else {"day": "今日", "week": "本周", "month": "本月", "recent30": "近30天"}.get(period, "近30天")
        return {
            "overview": overview,
            "category_matrix": category_matrix,
            "category_top_sale": category_top_sale,
            "category_top_profit": category_top_profit,
            "category_top_margin": category_top_margin,
            "brand": brand,
            "price_band": price_band,
            "supplier": supplier,
            "top_sku": top_sku,
            "distribution": distribution,
            "new_product": new_product,
            "return_rate_pct": return_rate_pct,
            "return_by_cat": return_by_cat,
            "color_style": color_style,
            "period_over_period": period_over_period,
            "date_range": date_range,
            "discount_band": discount_band,
            "zero_sale_skus": zero_sale_skus,
            "high_discount_low_margin": high_discount_low_margin,
        }
    finally:
        conn.close()


@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(500)
@app.errorhandler(413)
def json_error(e):
    """API 请求返回 JSON；405 方法不允许时也返回 JSON 避免前端解析到 HTML"""
    if request.path.startswith("/api/"):
        code = getattr(e, "code", 500)
        msg = str(e)
        if code == 405:
            msg = "请求方法不允许，请使用 GET 或 POST"
        elif code == 413:
            msg = "文件过大，请上传小于 200MB 的 Excel 文件"
        return jsonify({"success": False, "message": msg}), code
    code = getattr(e, "code", 500)
    if code == 404:
        return "Not Found", 404
    raise

# MySQL 配置由 db_config 统一从 .env 读取
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


@app.route("/")
def index():
    """根路径：未登录展示登录页，已登录展示运营看板（登录前置，必须登录后才能看详细数据）"""
    if not _is_logged_in():
        return send_from_directory("static", "login.html")
    resp = send_from_directory("static", "index.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/login")
def login_page():
    """登录页：已登录则跳转到看板首页；未登录则展示飞书/企微扫码"""
    if _is_logged_in():
        next_url = request.args.get("next", "").strip()
        return redirect(next_url if next_url.startswith("/") and not next_url.startswith("//") else "/")
    return send_from_directory("static", "login.html")


@app.route("/api/auth/me")
def api_auth_me():
    """当前登录用户信息；未登录返回 401"""
    if not _is_logged_in():
        return jsonify({"success": False, "login_required": True}), 401
    user_id = session.get("open_id") or session.get("user_id")
    # 权限：基于飞书 open_id 与环境变量
    perms = {
        "can_import": _has_module_access("import", user_id),
        "can_labor": _has_module_access("labor", user_id),
        "can_profit": _has_module_access("profit", user_id),
        "can_product_master": _has_module_access("product_master", user_id),
    }
    return jsonify({
        "success": True,
        "user_id": user_id,
        "name": session.get("user_name", ""),
        "avatar_url": session.get("avatar_url"),
        "permissions": perms,
    })


def _feishu_callback_base_url():
    """飞书回调 redirect_uri 的站点根 URL。本机用当前站点；外网必须用 HTMA_PUBLIC_URL（与飞书控制台重定向 URL 完全一致，避免 20029）。"""
    try:
        host = (request.host or "").split(":")[0]
        if host in ("127.0.0.1", "localhost") or host.startswith("127.0.0."):
            return request.url_root.rstrip("/")
    except Exception:
        pass
    base = (os.environ.get("HTMA_PUBLIC_URL") or os.environ.get("PUBLIC_URL") or "").strip()
    if base:
        return base.rstrip("/")
    # 外网未配置 HTMA_PUBLIC_URL 时，用 request 并优先 https（代理常见 X-Forwarded-Proto）
    try:
        proto = request.headers.get("X-Forwarded-Proto", request.scheme or "http")
        if (proto or "").lower() == "https":
            return ("https://" + (request.host or "")).rstrip("/")
    except Exception:
        pass
    return request.url_root.rstrip("/")


def _ensure_env_loaded():
    """请求时若飞书未配置则再次从 .env 注入，并写入 app.config 供后续请求使用"""
    if not (app.config.get("FEISHU_APP_ID") or "").strip() and (os.environ.get("FEISHU_APP_ID") or "").strip():
        app.config["FEISHU_APP_ID"] = (os.environ.get("FEISHU_APP_ID") or "").strip()
        app.config["FEISHU_APP_SECRET"] = (os.environ.get("FEISHU_APP_SECRET") or "").strip()
    if not (app.config.get("FEISHU_APP_ID") or "").strip():
        direct_id, direct_secret = _read_feishu_from_project_env()
        if direct_id and direct_secret:
            app.config["FEISHU_APP_ID"] = direct_id
            app.config["FEISHU_APP_SECRET"] = direct_secret
    if _auth_enabled():
        return True
    root = app.config.get("PROJECT_ROOT") or _project_root
    candidates = [
        app.config.get("ENV_PATH"),
        os.path.join(root, ".env") if root else None,
        os.path.join(os.getcwd(), ".env"),
        os.path.abspath(os.path.join(os.getcwd(), "..", ".env")),
    ]
    for path in candidates:
        if path:
            _load_env_from_file(path, force_keys=("FEISHU_APP_ID", "FEISHU_APP_SECRET"))
        if not (app.config.get("FEISHU_APP_ID") or "").strip() and (os.environ.get("FEISHU_APP_ID") or "").strip():
            app.config["FEISHU_APP_ID"] = (os.environ.get("FEISHU_APP_ID") or "").strip()
            app.config["FEISHU_APP_SECRET"] = (os.environ.get("FEISHU_APP_SECRET") or "").strip()
        if _auth_enabled():
            return True
    return False


@app.route("/api/auth/feishu_url")
def api_auth_feishu_url():
    """获取飞书授权 URL，前端跳转后用户扫码授权"""
    _ensure_env_loaded()
    env_path = app.config.get("ENV_PATH", "")
    if env_path:
        direct_id, direct_secret = _read_feishu_from_env_file(env_path)
        if direct_id and direct_secret:
            app.config["FEISHU_APP_ID"] = direct_id
            app.config["FEISHU_APP_SECRET"] = direct_secret
    feishu_id = (app.config.get("FEISHU_APP_ID") or "").strip()
    feishu_secret = (app.config.get("FEISHU_APP_SECRET") or "").strip()
    if not feishu_id or not feishu_secret:
        return jsonify({
            "success": False,
            "message": "未配置飞书登录。请确认项目根目录 .env 中已填写 FEISHU_APP_ID 与 FEISHU_APP_SECRET，并完全重启看板（先 Ctrl+C 停掉再 npm run htma:run）",
            "env_path": env_path,
            "env_exists": os.path.isfile(env_path) if env_path else False,
        }), 400
    from auth import get_feishu_authorize_url
    base = _feishu_callback_base_url()
    redirect_uri = request.args.get("redirect_uri") or (base + "/api/auth/feishu_callback")
    url, err = get_feishu_authorize_url(
        redirect_uri,
        state=request.args.get("state") or request.args.get("next"),  # 用 state 携带登录后跳转路径
        app_id=feishu_id,
        app_secret=feishu_secret,
    )
    if err:
        return jsonify({"success": False, "message": err}), 400
    return jsonify({"success": True, "url": url})


@app.route("/api/auth/feishu_callback")
def api_auth_feishu_callback():
    """飞书授权回调：企业内直接登录；企业外需审批通过后才可访问。"""
    from auth import feishu_exchange_code_and_user, _super_admin_open_id
    code = request.args.get("code")
    if not code:
        return redirect("/login?error=missing_code")
    base = _feishu_callback_base_url()
    redirect_uri = base + "/api/auth/feishu_callback"
    user, err = feishu_exchange_code_and_user(
        code,
        redirect_uri,
        app_id=app.config.get("FEISHU_APP_ID"),
        app_secret=app.config.get("FEISHU_APP_SECRET"),
    )
    if err:
        return redirect("/login?error=" + urllib.parse.quote(err))

    # 企业外用户：检查是否已审批通过
    if user.get("is_external"):
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT status FROM t_htma_external_access WHERE open_id = %s",
                (user["open_id"],),
            )
            row = cur.fetchone()
            status = (row.get("status") if isinstance(row, dict) else (row[0] if row else None)) if row else None
            if status != "approved":
                # 写入或更新为待审批
                cur.execute(
                    """INSERT INTO t_htma_external_access (open_id, name, union_id, status)
                       VALUES (%s, %s, %s, 'pending')
                       ON DUPLICATE KEY UPDATE name = VALUES(name), union_id = VALUES(union_id), status = 'pending', requested_at = CURRENT_TIMESTAMP""",
                    (user["open_id"], user.get("name") or "", user.get("union_id") or ""),
                )
                conn.commit()
                cur.close()
                conn.close()
                # 通知超级管理员余为军
                try:
                    from notify_util import send_feishu
                    approve_url = base.rstrip("/") + "/approval"
                    send_feishu(
                        "【好特卖看板】企业外用户申请访问\n申请人：%s\nopen_id：%s\n请打开链接审批：%s" % (user.get("name", ""), user["open_id"], approve_url),
                        at_user_id=_super_admin_open_id(),
                        at_user_name="余为军",
                        title="企业外用户访问审批",
                    )
                except Exception:
                    pass
                return redirect("/pending")
            cur.close()
            conn.close()
        except Exception:
            return redirect("/pending")

    session["open_id"] = user["open_id"]
    session["user_id"] = user["open_id"]
    session["user_name"] = user.get("name", "")
    session["avatar_url"] = user.get("avatar_url") or ""
    session.permanent = True
    next_url = (request.args.get("next", "").strip() or request.args.get("state", "").strip() or "/")
    if not next_url or next_url.startswith("//"):
        next_url = "/"
    if next_url.startswith("http"):
        allow_base = base
        if not next_url.startswith(allow_base):
            try:
                p = urllib.parse.urlparse(next_url)
                path_query = (p.path or "/") + (("?" + p.query) if p.query else "")
                next_url = path_query or "/"
            except Exception:
                next_url = "/"
    if not next_url.startswith("/"):
        next_url = "/"
    return redirect(next_url or "/")


@app.route("/pending")
def pending_page():
    """企业外用户提交申请后的等待页"""
    return send_from_directory("static", "pending.html")


def _is_super_admin():
    """当前登录用户是否为超级管理员（余为军）"""
    from auth import _super_admin_open_id
    oid = (session.get("open_id") or session.get("user_id") or "").strip()
    if not oid:
        return False
    admin = _super_admin_open_id()
    return oid == admin or oid == admin.replace("ou_", "")


@app.route("/approval")
def approval_page():
    """访问审批页（仅超级管理员余为军可见）"""
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + urllib.parse.quote(request.url or "/approval"))
    if not _is_super_admin():
        return redirect("/login?error=" + urllib.parse.quote("仅超级管理员可访问审批页"))
    return send_from_directory("static", "approval.html")


@app.route("/api/auth/approvals")
def api_auth_approvals():
    """待审批列表（仅超级管理员）"""
    if not _is_super_admin():
        return jsonify({"success": False, "message": "仅超级管理员可查看"}), 403
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT open_id, name, union_id, status, requested_at FROM t_htma_external_access WHERE status = 'pending' ORDER BY requested_at DESC"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        pending = []
        for r in rows:
            pending.append({
                "open_id": r.get("open_id"),
                "name": r.get("name"),
                "requested_at": (r.get("requested_at").strftime("%Y-%m-%d %H:%M") if r.get("requested_at") else ""),
            })
        return jsonify({"success": True, "pending": pending})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/auth/approve", methods=["POST"])
def api_auth_approve():
    """审批通过/拒绝（仅超级管理员）"""
    if not _is_super_admin():
        return jsonify({"success": False, "message": "仅超级管理员可审批"}), 403
    data = request.get_json() or {}
    open_id = (data.get("open_id") or "").strip()
    action = (data.get("action") or "").strip().lower()
    if not open_id or action not in ("approve", "reject"):
        return jsonify({"success": False, "message": "参数 open_id 与 action(approve/reject) 必填"}), 400
    status = "approved" if action == "approve" else "rejected"
    admin_oid = (session.get("open_id") or session.get("user_id") or "").strip()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE t_htma_external_access SET status = %s, decided_by_open_id = %s, decided_at = CURRENT_TIMESTAMP WHERE open_id = %s",
            (status, admin_oid, open_id),
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/auth/logout")
def api_auth_logout():
    """退出登录"""
    session.clear()
    return redirect("/login")


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
    # 仅登录且拥有导入权限的用户可访问
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + (urllib.parse.quote(request.url) if request.url else "/"))
    if _auth_enabled() and not _has_module_access("import"):
        return Response("您无权访问数据导入模块，请联系管理员。", status=403)
    return send_from_directory("static", "import.html")


@app.route("/api/import", methods=["POST"])
def api_import():
    """上传 Excel，覆盖式导入 MySQL。preview_only=1 时仅预览销售表结构，不导入"""
    if _auth_enabled() and not _has_module_access("import"):
        return jsonify({"success": False, "message": "无权访问数据导入模块，请联系管理员"}), 403
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

    # 至少有一个已选中的文件（有 filename），避免仅选税率表时被误判为“未上传”
    def _has_any_file():
        for key in ("sale_daily", "sale_summary", "stock", "category", "profit", "tax_burden"):
            f = request.files.get(key)
            if f and getattr(f, "filename", None) and str(f.filename).strip():
                return True
        return False
    if not _has_any_file():
        return jsonify({"success": False, "message": "请至少上传一个 Excel 文件"}), 400

    conn = None
    result = {"sale_daily": 0, "sale_summary": 0, "stock": 0, "category": 0, "profit": 0, "profit_refreshed": 0, "tax_burden": 0, "errors": []}

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

        # 销售/库存/毛利导入改为**增量**：不再在导入前全表清空，依赖 ON DUPLICATE KEY 去重与覆盖。
        # 如需全量重建，请使用专门的脚本（如 scripts/run_full_import.py），避免误删历史数据。

        # 品类附表：import_category 内部会 TRUNCATE（维表可安全重建）
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
                            # 与日报同传时：同(日期,货号)覆盖不累加，避免销售额翻倍（日报与汇总常为同一批数据两种导出）
                            cnt, diag = import_sale_summary(tmp.name, conn, overwrite_on_duplicate=_has_valid_file(["sale_daily"]))
                            result["sale_summary"] = cnt
                            if diag:
                                result.setdefault("diagnostics", []).append(diag)
                        elif key == "stock":
                            cnt, diag = import_stock(tmp.name, conn)
                            result["stock"] = cnt
                            if diag:
                                result.setdefault("diagnostics", []).append(diag)
                        elif key == "category":
                            result["category"] = import_category(tmp.name, conn)
                        elif key == "tax_burden":
                            result["tax_burden"] = import_tax_burden(tmp.name, conn)
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

        # 导入后自动化更新：毛利表 → 品类主数据 → 商品表 → 品类毛利表，确保后续看板/导出/比价正常
        # 1) 有销售数据且未上传毛利 Excel 时，从销售表汇总刷新毛利表
        if (result["sale_daily"] > 0 or result["sale_summary"] > 0) and not _has_valid_file(["profit"]):
            result["profit_refreshed"] = refresh_profit(conn)
        # 2) 从销售表透视生成品类主数据 t_htma_category（大类/中类/小类）
        if result["sale_daily"] > 0 or result["sale_summary"] > 0:
            try:
                result["category_refreshed"] = refresh_category_from_sale(conn)
            except Exception as e:
                result.setdefault("errors", []).append(f"品类表刷新: {str(e)}")
        # 3) 同步商品表 t_htma_products（供导出与比价）
        if result["sale_daily"] > 0 or result["sale_summary"] > 0 or result.get("stock"):
            try:
                result["products_synced"] = sync_products_table(conn)
            except Exception as e:
                result.setdefault("errors", []).append(f"商品表同步: {str(e)}")
        # 4) 从毛利表同步品类毛利表 t_htma_category_profit（供导出品类）
        if result.get("profit_refreshed") is not None or result.get("profit"):
            try:
                result["category_synced"] = sync_category_table(conn)
            except Exception as e:
                result.setdefault("errors", []).append(f"品类表同步: {str(e)}")

        cur.execute("SELECT COUNT(*) FROM t_htma_sale")
        result["sale_total"] = cur.fetchone()["COUNT(*)"]
        try:
            cur.execute("SELECT COALESCE(SUM(sale_amount), 0) AS v FROM t_htma_sale")
            row = cur.fetchone()
            result["sale_total_amount"] = round(float((row.get("v") if isinstance(row, dict) else row[0]) or 0), 2)
        except Exception:
            result["sale_total_amount"] = 0.0
        cur.execute("SELECT COUNT(*) FROM t_htma_stock")
        result["stock_total"] = cur.fetchone()["COUNT(*)"]
        try:
            cur.execute("""
                SELECT COALESCE(SUM(stock_amount), 0) AS v FROM t_htma_stock
                WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
            """, (STORE_ID, STORE_ID))
            row = cur.fetchone()
            result["stock_total_amount"] = round(float((row.get("v") if isinstance(row, dict) else row[0]) or 0), 2)
        except Exception:
            result["stock_total_amount"] = 0.0
        cur.execute("SELECT COUNT(*) FROM t_htma_profit")
        result["profit_total"] = cur.fetchone()["COUNT(*)"]
        try:
            cur.execute("SELECT COUNT(*) FROM t_htma_tax_burden")
            result["tax_burden_total"] = cur.fetchone()["COUNT(*)"]
        except Exception:
            result["tax_burden_total"] = 0
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
        result["data_import_target"] = "server"  # 导入始终写入本接口所在服务器的 MySQL，与访问者设备无关
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
        tb = traceback.format_exc()
        return jsonify({
            "success": False,
            "message": str(e),
            "data_import_target": "server",
            "traceback": tb[-2000:] if len(tb) > 2000 else tb  # 限制长度，避免响应过大导致前端超时
        }), 500


@app.route("/api/import_labor_cost", methods=["POST", "OPTIONS"])
def api_import_labor_cost():
    """上传人力成本 Excel（组长+全职+兼职/小时工/保洁/管理岗），按报表月份导入。
    支持单 sheet 或多 sheet，自动识别类目并清洗岗位名、归类写入。
    表单: file=Excel, report_month=YYYY-MM。与 scripts/import_labor_excel_and_analyze.py 使用同一 import_labor_cost 逻辑。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力成本模块，请联系管理员"}), 403
    report_month = (request.form.get("report_month") or "").strip()
    if not report_month:
        return jsonify({"success": False, "message": "请提供 report_month，如 2026-01"}), 400
    import re
    if not re.match(r"^\d{4}-\d{2}$", report_month):
        return jsonify({"success": False, "message": "report_month 格式为 YYYY-MM，如 2026-01"}), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"success": False, "message": "请上传 Excel 文件（file）"}), 400
    if not (f.filename.lower().endswith(".xls") or f.filename.lower().endswith(".xlsx")):
        return jsonify({"success": False, "message": "仅支持 .xls / .xlsx"}), 400
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.filename)[1]) as tmp:
            f.save(tmp.name)
            try:
                conn = get_conn()
                counts, diag, _ = import_labor_cost(tmp.name, report_month, conn)
                try:
                    refresh_labor_cost_analysis(conn)
                except Exception:
                    pass
                conn.close()
                # 按类目拼导入结果文案（仅列出有数据的类目）
                labels = {"leader": "组长/职能", "fulltime": "全职", "parttime": "兼职", "hourly": "小时工", "cleaner": "保洁", "management": "管理岗"}
                parts = [f"{labels.get(k, k)} {v} 条" for k, v in counts.items() if v and isinstance(v, int)]
                msg = "导入完成：" + "，".join(parts) + "；已自动清洗并归类，已刷新汇总表。请在看板「人力成本」Tab 查看（报表月份留空即最近月份）。" if parts else "导入完成：已刷新汇总表。请在看板「人力成本」Tab 查看。"
                return jsonify({
                    "success": True,
                    "report_month": report_month,
                    "leader_count": counts.get("leader", 0),
                    "fulltime_count": counts.get("fulltime", 0),
                    "counts": counts,
                    "message": msg,
                    "diagnostics": diag or [],
                })
            finally:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass
    except Exception as e:
        import traceback
        return jsonify({"success": False, "message": str(e), "traceback": traceback.format_exc()[-1500:]}), 500


@app.route("/api/import_labor_cost_image", methods=["POST", "OPTIONS"])
def api_import_labor_cost_image():
    """上传人力成本附表截图/照片，OCR 识别后写入 MySQL。表单: file=图片, report_month=YYYY-MM, position_type=leader|fulltime（必填：组长表/组员表二选一）"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力成本模块，请联系管理员"}), 403
    report_month = (request.form.get("report_month") or "").strip()
    if not report_month:
        return jsonify({"success": False, "message": "请提供 report_month，如 2026-01"}), 400
    import re
    if not re.match(r"^\d{4}-\d{2}$", report_month):
        return jsonify({"success": False, "message": "report_month 格式为 YYYY-MM"}), 400
    position_type = (request.form.get("position_type") or "").strip().lower()
    if position_type not in ("leader", "fulltime"):
        return jsonify({"success": False, "message": "请选择表类型：组长表(leader) 或 组员表(fulltime)，与附图一一对应"}), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"success": False, "message": "请上传图片文件（file）"}), 400
    low = f.filename.lower()
    if not (low.endswith(".png") or low.endswith(".jpg") or low.endswith(".jpeg")):
        return jsonify({"success": False, "message": "仅支持 .png / .jpg / .jpeg 图片"}), 400
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.filename)[1]) as tmp:
            f.save(tmp.name)
            tmp_path = tmp.name
        result = {"done": False, "leader_count": 0, "fulltime_count": 0, "diag": [], "err": None}

        def run_import():
            try:
                conn = get_conn()
                lc, fc, diag = import_labor_cost_from_image(tmp_path, report_month, conn, position_type=position_type)
                conn.close()
                result["leader_count"] = lc
                result["fulltime_count"] = fc
                result["diag"] = diag or []
            except Exception as e:
                result["err"] = str(e)
            finally:
                result["done"] = True

        th = threading.Thread(target=run_import, daemon=True)
        th.start()
        th.join(timeout=90)
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        if not result["done"]:
            return jsonify({
                "success": False,
                "message": "OCR 识别超时（90 秒），请缩小图片、裁剪仅保留表格区域，或改用 Excel 导入",
                "diagnostics": ["请求已取消"],
            })
        if result["err"]:
            return jsonify({"success": False, "message": result["err"], "diagnostics": result["diag"]})
        lc, fc = result["leader_count"], result["fulltime_count"]
        return jsonify({
            "success": True,
            "report_month": report_month,
            "leader_count": lc,
            "fulltime_count": fc,
            "message": f"附图导入完成：组长 {lc} 条，组员 {fc} 条",
            "diagnostics": result["diag"] or [],
        })
    except Exception as e:
        import traceback
        return jsonify({"success": False, "message": str(e), "traceback": traceback.format_exc()[-1500:]}), 500


# ---------- 分店商品档案（与数据导入、人力成本同级权限）----------
@app.route("/api/import_product_master", methods=["POST", "OPTIONS"])
def api_import_product_master():
    """上传分店商品档案 Excel，导入 t_htma_product_master。表单: file=Excel。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问分店商品档案模块，请联系管理员"}), 403
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"success": False, "message": "请上传 Excel 文件（file）"}), 400
    if not (f.filename.lower().endswith(".xls") or f.filename.lower().endswith(".xlsx")):
        return jsonify({"success": False, "message": "仅支持 .xls / .xlsx"}), 400
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.filename)[1]) as tmp:
            f.save(tmp.name)
            try:
                conn = get_conn()
                cnt, msg = import_product_master(tmp.name, conn)
                conn.close()
                return jsonify({"success": True, "inserted": cnt, "message": msg})
            finally:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass
    except Exception as e:
        import traceback
        return jsonify({"success": False, "message": str(e), "traceback": traceback.format_exc()[-1500:]}), 500


@app.route("/api/product_master_status")
def api_product_master_status():
    """分店商品档案状态：总条数、最新档案日期。需 product_master 权限。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM t_htma_product_master")
        row = cur.fetchone()
        total = (row[0] if row and isinstance(row, (list, tuple)) else (row.get("c", 0) if isinstance(row, dict) else 0)) or 0
        cur.execute("SELECT MAX(archive_date) AS d FROM t_htma_product_master")
        r2 = cur.fetchone()
        latest = r2[0] if r2 and isinstance(r2, (list, tuple)) else (r2.get("d") if isinstance(r2, dict) else None)
        cur.close()
        conn.close()
        return jsonify({"success": True, "total": total, "latest_archive_date": latest.isoformat() if hasattr(latest, "isoformat") else str(latest) if latest else None})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


def _product_master_analysis(conn):
    """从 t_htma_product_master 聚合：按状态、品类、品牌、经销方式、价格带。返回 dict。"""
    cur = conn.cursor()
    def _row_name(r):
        return (r.get("k") or r.get("name") or "").strip() if isinstance(r, dict) else (r[0] or "").strip()
    def _row_count(r):
        return r.get("cnt") or r.get("count") or 0 if isinstance(r, dict) else (r[1] if len(r) > 1 else 0)
    # 按商品状态
    cur.execute("""
        SELECT product_status AS k, COUNT(*) AS cnt FROM t_htma_product_master
        WHERE COALESCE(TRIM(product_status), '') != '' GROUP BY product_status ORDER BY cnt DESC LIMIT 20
    """)
    by_status = [{"name": _row_name(r) or "（空）", "count": _row_count(r)} for r in cur.fetchall()]
    # 按类别（品类）
    cur.execute("""
        SELECT category_name AS k, COUNT(*) AS cnt FROM t_htma_product_master
        WHERE COALESCE(TRIM(category_name), '') != '' GROUP BY category_name ORDER BY cnt DESC LIMIT 25
    """)
    by_category = [{"name": _row_name(r), "count": _row_count(r)} for r in cur.fetchall()]
    # 按品牌
    cur.execute("""
        SELECT brand_name AS k, COUNT(*) AS cnt FROM t_htma_product_master
        WHERE COALESCE(TRIM(brand_name), '') != '' GROUP BY brand_name ORDER BY cnt DESC LIMIT 25
    """)
    by_brand = [{"name": _row_name(r), "count": _row_count(r)} for r in cur.fetchall()]
    # 按经销方式
    cur.execute("""
        SELECT distribution_mode AS k, COUNT(*) AS cnt FROM t_htma_product_master
        WHERE COALESCE(TRIM(distribution_mode), '') != '' GROUP BY distribution_mode ORDER BY cnt DESC LIMIT 10
    """)
    by_distribution = [{"name": _row_name(r), "count": _row_count(r)} for r in cur.fetchall()]
    # 零售价分布（区间）
    cur.execute("""
        SELECT
            CASE
                WHEN COALESCE(retail_price, 0) = 0 THEN '0'
                WHEN retail_price < 50 THEN '1-49'
                WHEN retail_price < 100 THEN '50-99'
                WHEN retail_price < 200 THEN '100-199'
                WHEN retail_price < 500 THEN '200-499'
                WHEN retail_price < 1000 THEN '500-999'
                ELSE '1000+'
            END AS band,
            COUNT(*) AS cnt
        FROM t_htma_product_master
        GROUP BY band ORDER BY FIELD(band,'0','1-49','50-99','100-199','200-499','500-999','1000+')
    """)
    by_price = [{"band": (r.get("band") or r.get("k") or "0") if isinstance(r, dict) else (r[0] or "0"), "count": _row_count(r)} for r in cur.fetchall()]
    cur.close()
    return {
        "by_status": by_status,
        "by_category": by_category,
        "by_brand": by_brand,
        "by_distribution": by_distribution,
        "by_price_band": by_price,
    }


@app.route("/api/product_master_analysis")
def api_product_master_analysis():
    """分店商品档案分析数据。需 product_master 权限。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    try:
        conn = get_conn()
        data = _product_master_analysis(conn)
        conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/product_master")
def page_product_master():
    """分店商品档案页：总览 + 按状态/品类/品牌/经销方式/价格带分析。与数据导入、人力成本同级权限。"""
    if _auth_enabled() and (not _is_logged_in() or not _has_module_access("product_master")):
        return Response("您无权访问分店商品档案模块，请联系管理员。", status=403)
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM t_htma_product_master")
        row = cur.fetchone()
        total = row[0] if row and isinstance(row, (list, tuple)) else (row.get("c", 0) if isinstance(row, dict) else 0)
        cur.execute("SELECT MAX(archive_date) AS d FROM t_htma_product_master")
        r2 = cur.fetchone()
        latest = r2[0] if r2 and isinstance(r2, (list, tuple)) else (r2.get("d") if isinstance(r2, dict) else None)
        analysis = _product_master_analysis(conn)
        cur.close()
        conn.close()
    except Exception as e:
        total = 0
        latest = None
        analysis = {"by_status": [], "by_category": [], "by_brand": [], "by_distribution": [], "by_price_band": []}
    base_css = (
        "body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:20px;}"
        ".box{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:16px;margin-bottom:12px;}"
        ".label{color:#94a3b8;font-size:0.9rem;} .value{font-size:1.2rem;font-weight:700;color:#38bdf8;}"
        "table{border-collapse:collapse;width:100%;margin-top:8px;} th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #334155;} th{color:#94a3b8;} .num{text-align:right;} a{color:#38bdf8;}"
    )
    def _tbl(rows, col_name="name", col_count="count"):
        if not rows:
            return "<p class='label'>无数据</p>"
        return (
            "<table><thead><tr><th>%s</th><th class='num'>数量</th></tr></thead><tbody>"
            % (col_name if col_name == "name" else "区间")
            + "".join("<tr><td>%s</td><td class='num'>%s</td></tr>" % (str(r.get(col_name, r.get("band", ""))).replace("<", "&lt;"), r.get(col_count, 0)) for r in rows)
            + "</tbody></table>"
        )
    status_tbl = _tbl(analysis.get("by_status", []))
    category_tbl = _tbl(analysis.get("by_category", []), "name", "count")
    brand_tbl = _tbl(analysis.get("by_brand", []), "name", "count")
    dist_tbl = _tbl(analysis.get("by_distribution", []), "name", "count")
    price_tbl = _tbl([{"name": r.get("band", ""), "count": r.get("count", 0)} for r in analysis.get("by_price_band", [])], "name", "count")
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/><title>分店商品档案</title><style>%s</style></head><body>"
        "<div class='box'><h2>📦 分店商品档案 · 数据分析</h2>"
        "<p class='label'>总条数：<span class='value'>%s</span> &nbsp; 最新档案日期：<span class='value'>%s</span></p>"
        "<p><a href='/import'>数据导入</a> | <a href='/'>返回看板</a></p></div>"
        "<div class='box'><h3 class='label'>按商品状态</h3>%s</div>"
        "<div class='box'><h3 class='label'>按品类（类别）</h3>%s</div>"
        "<div class='box'><h3 class='label'>按品牌</h3>%s</div>"
        "<div class='box'><h3 class='label'>按经销方式</h3>%s</div>"
        "<div class='box'><h3 class='label'>零售价分布</h3>%s</div>"
        "</body></html>"
    ) % (base_css, total, (latest.isoformat() if hasattr(latest, "isoformat") else str(latest)) if latest else "-", status_tbl, category_tbl, brand_tbl, dist_tbl, price_tbl)
    return Response(html, mimetype="text/html; charset=utf-8")


# 人力成本 position_type -> 前端展示类目名（与 12月薪资表 各 sheet 对应）
LABOR_POSITION_TYPE_NAMES = {
    "leader": "组长",
    "fulltime": "组员",
    "parttime": "兼职",
    "hourly": "小时工",
    "cleaner": "保洁",
    "management": "管理岗",
}
LABOR_CATEGORY_ORDER = ("组长", "组员", "兼职", "小时工", "保洁", "管理岗")
# 类目列表展示顺序：组长+组员合并为一行，便于人效分析；明细区仍保留组长/组员分表
LABOR_CATEGORY_ORDER_DISPLAY = ("组长+组员", "兼职", "小时工", "保洁", "管理岗")


def _labor_category_by_month(limit=24):
    """按类目×月份汇总：每个类目下有小计 + 各月数据，用于类目列表多行展示。
    组长与组员合并为「组长+组员」一行，并注明月份，便于人效分析。
    返回 (months_asc, by_cat)：months_asc 为月份升序，by_cat[类目名][月份] = {position_count, total_wage}，月份含 '小计'。"""
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT report_month, position_type,
                   COUNT(*) AS position_count,
                   COALESCE(SUM(COALESCE(total_cost, company_cost)), 0) AS total_wage
            FROM t_htma_labor_cost
            GROUP BY report_month, position_type
            ORDER BY report_month ASC
        """)
        rows = cur.fetchall()
        name_to_type = {v: k for k, v in LABOR_POSITION_TYPE_NAMES.items()}
        months_set = set()
        by_type_month = {}  # (position_type, report_month) -> {count, wage}
        for r in rows:
            m = (r.get("report_month") or "").strip()
            t = (r.get("position_type") or "").strip().lower()
            if not m or not t:
                continue
            months_set.add(m)
            cnt = int(r.get("position_count") or 0)
            wage = round(float(r.get("total_wage") or 0), 2)
            by_type_month[(t, m)] = {"position_count": cnt, "total_wage": wage}
        months_asc = sorted(months_set)[:limit]
        # 全口径 + 类目（组长+组员合并）+ 其他类目；每类目下 小计 + 各月
        by_cat = {}
        for display_name in ("全口径",) + tuple(LABOR_CATEGORY_ORDER_DISPLAY):
            by_cat[display_name] = {"小计": {"position_count": 0, "total_wage": 0}}
            for m in months_asc:
                if display_name == "全口径":
                    cnt = 0
                    wage = 0
                    for t in LABOR_POSITION_TYPE_NAMES:
                        v = by_type_month.get((t, m), {"position_count": 0, "total_wage": 0})
                        cnt += v["position_count"]
                        wage += v["total_wage"]
                    by_cat[display_name][m] = {"position_count": cnt, "total_wage": round(wage, 2)}
                elif display_name == "组长+组员":
                    # 组长 + 组员 合并计算，并注明月份（各列已是该月）
                    v_leader = by_type_month.get(("leader", m), {"position_count": 0, "total_wage": 0})
                    v_fulltime = by_type_month.get(("fulltime", m), {"position_count": 0, "total_wage": 0})
                    cnt = v_leader["position_count"] + v_fulltime["position_count"]
                    wage = round(v_leader["total_wage"] + v_fulltime["total_wage"], 2)
                    by_cat[display_name][m] = {"position_count": cnt, "total_wage": wage}
                else:
                    t = name_to_type.get(display_name, "")
                    v = by_type_month.get((t, m), {"position_count": 0, "total_wage": 0})
                    by_cat[display_name][m] = {"position_count": v["position_count"], "total_wage": v["total_wage"]}
                by_cat[display_name]["小计"]["position_count"] += by_cat[display_name][m]["position_count"]
                by_cat[display_name]["小计"]["total_wage"] += by_cat[display_name][m]["total_wage"]
            by_cat[display_name]["小计"]["total_wage"] = round(by_cat[display_name]["小计"]["total_wage"], 2)
        return months_asc, by_cat
    finally:
        conn.close()


def _labor_person_display(p):
    """姓名展示：空、纯数字（含 12.0、序号）均显示为「-」，避免把序号当姓名。供 /labor 页与 API 共用。"""
    if p is None:
        return "-"
    s = str(p).strip()
    if not s:
        return "-"
    try:
        float(s)
        return "-"
    except (ValueError, TypeError):
        pass
    if s.isdigit() or (len(s) <= 6 and s.replace(".", "", 1).replace("-", "", 1).isdigit()):
        return "-"
    return s.replace("<", "&lt;")


def _labor_cost_analysis_response(month):
    """人力成本分析逻辑，返回 (month, leaders, fulltime, summary) 或 (None, [], [], {})。
    全口径：汇总所有 position_type（组长/组员/兼职/小时工/保洁/管理岗）；再按类目拆分展示。"""
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        if not month:
            cur.execute("SELECT DISTINCT report_month FROM t_htma_labor_cost ORDER BY report_month DESC LIMIT 1")
            row = cur.fetchone()
            month = row["report_month"] if row and row.get("report_month") else None
            if not month:
                cur.execute("SELECT report_month FROM t_htma_labor_cost_analysis ORDER BY report_month DESC LIMIT 1")
                row = cur.fetchone()
                month = row["report_month"] if row and row.get("report_month") else None
            if not month:
                return None, [], [], {}

        cur.execute("""
            SELECT position_name, person_name, supplier_name, total_salary, pre_tax_pay, actual_salary, luxury_bonus, actual_income, company_cost, total_cost
            FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'leader' ORDER BY COALESCE(total_cost, 0) DESC
        """, (month,))
        leaders = cur.fetchall()
        cur.execute("""
            SELECT position_name, person_name, supplier_name, work_hours, base_salary, performance, position_allowance, total_salary, pre_tax_pay, luxury_amount, actual_income, company_cost, total_cost
            FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'fulltime' ORDER BY COALESCE(company_cost, 0) DESC
        """, (month,))
        fulltime = cur.fetchall()
        try:
            cur.execute("""
                SELECT position_name, person_name, supplier_name, company_cost, total_cost,
                       store_name, city, join_date, leave_date, work_hours, normal_hours, triple_pay_hours,
                       hourly_rate, pay_amount, service_fee_unit, service_fee_total, tax,
                       cost_include, department
                FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'parttime' ORDER BY position_name, COALESCE(total_cost, 0) DESC
            """, (month,))
            parttime = cur.fetchall()
        except Exception:
            cur.execute("""
                SELECT position_name, person_name, supplier_name, company_cost, total_cost
                FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'parttime' ORDER BY position_name, COALESCE(total_cost, 0) DESC
            """, (month,))
            parttime = cur.fetchall()
        cur.execute("""
            SELECT position_name, person_name, supplier_name, company_cost, total_cost
            FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'hourly' ORDER BY COALESCE(total_cost, 0) DESC
        """, (month,))
        hourly = cur.fetchall()
        cur.execute("""
            SELECT position_name, person_name, supplier_name, company_cost, total_cost
            FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'cleaner' ORDER BY COALESCE(total_cost, 0) DESC
        """, (month,))
        cleaner = cur.fetchall()
        cur.execute("""
            SELECT position_name, person_name, supplier_name, company_cost, total_cost
            FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'management' ORDER BY COALESCE(total_cost, 0) DESC
        """, (month,))
        management = cur.fetchall()
        # 全口径：按 position_type 汇总（含组长/组员/兼职/小时工/保洁/管理岗）
        cur.execute("""
            SELECT position_type, COUNT(*) AS position_count,
                   COALESCE(SUM(COALESCE(total_cost, company_cost)), 0) AS total_wage
            FROM t_htma_labor_cost WHERE report_month = %s
            GROUP BY position_type
        """, (month,))
        type_rows = cur.fetchall()
        total_labor_cost = 0
        total_positions = 0
        by_type = {}
        for r in type_rows:
            t = (r.get("position_type") or "").strip().lower()
            cnt = int(r.get("position_count") or 0)
            wage = round(float(r.get("total_wage") or 0), 2)
            by_type[t] = {"position_count": cnt, "total_wage": wage}
            total_labor_cost += wage
            total_positions += cnt
        total_labor_cost = round(total_labor_cost, 2)
        cur.execute("SELECT COALESCE(SUM(work_hours), 0) AS th FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'fulltime'", (month,))
        total_hours_row = cur.fetchone()
        total_hours = float(total_hours_row["th"] or 0) if total_hours_row else 0

        # 若明细表该月无数据，尝试从汇总表 t_htma_labor_cost_analysis 取汇总展示
        if total_positions == 0 and total_labor_cost == 0 and len(leaders) == 0 and len(fulltime) == 0:
            cur.execute("""
                SELECT report_month, leader_count, leader_total_cost, fulltime_count, fulltime_total_cost,
                       fulltime_total_hours, total_labor_cost, prev_month_total, mom_pct
                FROM t_htma_labor_cost_analysis WHERE report_month = %s
            """, (month,))
            ana = cur.fetchone()
            if ana:
                leader_total = float(ana.get("leader_total_cost") or 0)
                fulltime_total = float(ana.get("fulltime_total_cost") or 0)
                total_labor_cost = float(ana.get("total_labor_cost") or 0)
                total_hours = float(ana.get("fulltime_total_hours") or 0)
                lc = int(ana.get("leader_count") or 0)
                fc = int(ana.get("fulltime_count") or 0)
                by_category = [
                    {"name": "全口径", "total_wage": round(total_labor_cost, 2), "position_count": lc + fc},
                    {"name": "组长", "total_wage": round(leader_total, 2), "position_count": lc},
                    {"name": "组员", "total_wage": round(fulltime_total, 2), "position_count": fc},
                ]
                try:
                    _ty = (os.environ.get("TARGET_LABOR_COST_YUAN") or "530000").strip() or "530000"
                    _target_y = float(_ty)
                except Exception:
                    _target_y = 530000.0
                summary = {
                    "report_month": month,
                    "leader_position_count": lc,
                    "fulltime_position_count": fc,
                    "formal_employee_count": lc + fc,
                    "other_labor_count": 0,
                    "leader_total_cost": round(leader_total, 2),
                    "fulltime_total_cost": round(fulltime_total, 2),
                    "total_labor_cost": round(total_labor_cost, 2),
                    "fulltime_total_hours": round(total_hours, 2),
                    "by_category": by_category,
                    "target_labor_cost": _target_y,
                    "labor_cost_difference": round(_target_y - total_labor_cost, 2),
                    "labor_cost_difference_note": "实际支付约 53 万，本页全口径仅统计出 43 万，存在统计缺口。可能原因：① 部分类目或 sheet 未导入；② 薪资表与开票/实际支付口径不一致（如含税、服务费、社保等）；③ 某月或某店数据未覆盖。请核对「开票金额/总成本」及完整薪资表各 sheet 是否均已导入。",
                    "note": "以下为汇总表数据；组长/组员明细暂无。请使用「12月薪资表」完整 Excel 重新导入后可得到全口径（约 53 万）及兼职/小时工/保洁/管理岗等类目拆分。",
                }
                return month, [], [], summary
            return None, [], [], {}

        # 构建 by_category：先全口径，再按固定顺序各类目
        by_category = [{"name": "全口径", "total_wage": total_labor_cost, "position_count": total_positions}]
        type_to_name = LABOR_POSITION_TYPE_NAMES
        for display_name in LABOR_CATEGORY_ORDER:
            for ptype, dname in type_to_name.items():
                if dname != display_name:
                    continue
                if ptype in by_type and (by_type[ptype]["position_count"] or by_type[ptype]["total_wage"]):
                    by_category.append({
                        "name": display_name,
                        "total_wage": by_type[ptype]["total_wage"],
                        "position_count": by_type[ptype]["position_count"],
                    })
                    break

        leader_total = by_type.get("leader", {}).get("total_wage", 0)
        fulltime_total = by_type.get("fulltime", {}).get("total_wage", 0)
        leader_count = int(by_type.get("leader", {}).get("position_count", 0))
        fulltime_count = int(by_type.get("fulltime", {}).get("position_count", 0))
        parttime_count = int(by_type.get("parttime", {}).get("position_count", 0))
        hourly_count = int(by_type.get("hourly", {}).get("position_count", 0))
        cleaner_count = int(by_type.get("cleaner", {}).get("position_count", 0))
        management_count = int(by_type.get("management", {}).get("position_count", 0))
        formal_count = leader_count + fulltime_count
        other_count = parttime_count + hourly_count + cleaner_count + management_count
        try:
            _target_yuan = (os.environ.get("TARGET_LABOR_COST_YUAN") or "530000").strip() or "530000"
            target_labor_cost_yuan = float(_target_yuan)
        except Exception:
            target_labor_cost_yuan = 530000.0
        labor_cost_difference = round(target_labor_cost_yuan - total_labor_cost, 2)
        summary = {
            "report_month": month,
            "leader_position_count": leader_count,
            "fulltime_position_count": fulltime_count,
            "parttime_position_count": parttime_count,
            "hourly_position_count": hourly_count,
            "cleaner_position_count": cleaner_count,
            "management_position_count": management_count,
            "formal_employee_count": formal_count,
            "other_labor_count": other_count,
            "leader_total_cost": round(leader_total, 2),
            "fulltime_total_cost": round(fulltime_total, 2),
            "total_labor_cost": total_labor_cost,
            "fulltime_total_hours": round(total_hours, 2),
            "by_category": by_category,
            "target_labor_cost": target_labor_cost_yuan,
            "labor_cost_difference": labor_cost_difference,
            "labor_cost_difference_note": "实际支付约 53 万，本页全口径仅统计出 43 万，存在统计缺口。可能原因：① 部分类目或 sheet 未导入；② 薪资表与开票/实际支付口径不一致（如含税、服务费、社保等）；③ 某月或某店数据未覆盖。请核对「开票金额/总成本」及完整薪资表各 sheet 是否均已导入。",
            "note": "全口径为当月全部人员费用。正式职工=组长+组员，其他人力=兼职+小时工+保洁+管理岗，分开统计便于人效分析。",
        }
        def _decimals(obj):
            if obj is None:
                return None
            d = {}
            for k, v in obj.items():
                if k == "person_name":
                    d[k] = _labor_person_display(v)
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    d[k] = round(float(v), 2) if v is not None else None
                else:
                    d[k] = v
            return d
        summary["detail_parttime"] = [_decimals(r) for r in parttime]
        # 兼职按属性(岗位名)分组，便于先汇总再展开明细
        by_attr = {}
        for r in parttime:
            attr = (r.get("position_name") or "").strip() or "其他"
            if attr not in by_attr:
                by_attr[attr] = {"attribute": attr, "count": 0, "total_cost": 0, "persons": []}
            by_attr[attr]["count"] += 1
            by_attr[attr]["total_cost"] += float(r.get("total_cost") or r.get("company_cost") or 0)
            by_attr[attr]["persons"].append(_decimals(r))
        summary["parttime_by_attribute"] = list(by_attr.values())
        for g in summary["parttime_by_attribute"]:
            g["total_cost"] = round(g["total_cost"], 2)
        # 组员/全职按岗位分组，便于先汇总再展开明细（与兼职展示逻辑一致）
        fulltime_by_pos = {}
        for r in fulltime:
            pos = (r.get("position_name") or "").strip() or "其他"
            if pos not in fulltime_by_pos:
                fulltime_by_pos[pos] = {"position": pos, "count": 0, "total_cost": 0, "persons": []}
            fulltime_by_pos[pos]["count"] += 1
            fulltime_by_pos[pos]["total_cost"] += float(r.get("total_cost") or r.get("company_cost") or 0)
            fulltime_by_pos[pos]["persons"].append(_decimals(r))
        summary["fulltime_by_position"] = list(fulltime_by_pos.values())
        for g in summary["fulltime_by_position"]:
            g["total_cost"] = round(g["total_cost"], 2)
        summary["detail_hourly"] = [_decimals(r) for r in hourly]
        summary["detail_cleaner"] = [_decimals(r) for r in cleaner]
        summary["detail_management"] = [_decimals(r) for r in management]
        return month, [_decimals(r) for r in leaders], [_decimals(r) for r in fulltime], summary
    finally:
        conn.close()


def _labor_safe_response(f, fallback_success_json):
    """人力成本接口统一异常捕获：避免 DB/逻辑异常导致 500，始终返回 200 + JSON，便于前端独立展示错误。"""
    try:
        return f()
    except Exception as e:
        return jsonify({**fallback_success_json, "success": False, "message": "人力成本服务暂时异常，请稍后重试或使用独立页 /labor。（" + str(e)[:200] + "）"})


@app.route("/api/labor_cost_status", methods=["GET", "OPTIONS"])
def api_labor_cost_status():
    """人力成本数据状态：明细表条数、汇总表月份列表。独立于主看板 KPI 周期，异常时返回 200+success:false。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力成本模块，请联系管理员"}), 403

    def _do():
        conn = get_conn()
        try:
            cur = conn.cursor(pymysql.cursors.DictCursor)
            cur.execute("SELECT COUNT(*) AS n FROM t_htma_labor_cost")
            raw_count = (cur.fetchone() or {}).get("n") or 0
            cur.execute("SELECT report_month FROM t_htma_labor_cost ORDER BY report_month DESC LIMIT 1")
            latest_row = cur.fetchone()
            latest_report_month = (latest_row or {}).get("report_month") or None
            cur.execute("SELECT report_month, leader_count, fulltime_count, leader_total_cost, fulltime_total_cost, total_labor_cost FROM t_htma_labor_cost_analysis ORDER BY report_month DESC LIMIT 24")
            analysis_months = cur.fetchall()
            cur.execute("SELECT DISTINCT report_month FROM t_htma_labor_cost ORDER BY report_month DESC LIMIT 24")
            detail_months = []
            for r in cur.fetchall():
                v = r.get("report_month") if isinstance(r, dict) else (r[0] if r else None)
                if v:
                    detail_months.append(str(v))
            for r in analysis_months:
                for k, v in list(r.items()):
                    if v is not None:
                        try:
                            f = float(v)
                            r[k] = int(f) if f == int(f) else round(f, 2)
                        except (TypeError, ValueError):
                            pass
            available = list(dict.fromkeys(detail_months + [str(r.get("report_month")) for r in analysis_months if r.get("report_month")]))
            available.sort(reverse=True)
            return jsonify({
                "success": True,
                "raw_count": raw_count,
                "latest_report_month": latest_report_month,
                "analysis_months": analysis_months,
                "available_months": available[:24],
            })
        finally:
            conn.close()

    return _labor_safe_response(_do, {"raw_count": 0, "latest_report_month": None, "analysis_months": [], "available_months": []})


def _api_labor_cost_impl():
    """人力成本分析逻辑（独立于主看板 KPI 周期，仅按报表月份）。"""
    month = (request.args.get("month") or request.form.get("month") or "").strip()
    if not month and request.get_json(silent=True):
        month = (request.get_json().get("month") or "").strip()
    report_month, leaders, fulltime, summary = _labor_cost_analysis_response(month)
    if report_month is None:
        return jsonify({"success": True, "report_month": None, "leaders": [], "fulltime": [], "summary": {}, "message": "暂无人力成本数据，请先导入"})
    return jsonify({"success": True, "report_month": report_month, "leaders": leaders, "fulltime": fulltime, "summary": summary})


@app.route("/api/labor_cost", methods=["GET", "POST", "HEAD", "OPTIONS"])
def api_labor_cost():
    """人力成本分析（短路径）。独立于主看板 KPI 周期，仅按报表月份；异常时返回 200+success:false。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力成本模块，请联系管理员"}), 403
    return _labor_safe_response(_api_labor_cost_impl, {"report_month": None, "leaders": [], "fulltime": [], "summary": {}, "message": "人力成本服务暂时异常"})


@app.route("/api/labor_cost_analysis", methods=["GET", "POST", "HEAD", "OPTIONS"])
def api_labor_cost_analysis():
    """人力成本分析（长路径，兼容旧地址）。独立于主看板，异常时返回 200+success:false。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力成本模块，请联系管理员"}), 403
    return _labor_safe_response(_api_labor_cost_impl, {"report_month": None, "leaders": [], "fulltime": [], "summary": {}, "message": "人力成本服务暂时异常"})


def _labor_months_overview(limit=24):
    """返回各月汇总列表，用于「汇总」表展示。按 report_month 升序。含正式职工(组长+组员)与其他人力(兼职+小时工+保洁+管理岗)人数，便于分开统计。"""
    try:
        _ty = (os.environ.get("TARGET_LABOR_COST_YUAN") or "530000").strip() or "530000"
        target = float(_ty)
    except Exception:
        target = 530000.0
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT report_month, position_type,
                   COUNT(*) AS position_count,
                   COALESCE(SUM(COALESCE(total_cost, company_cost)), 0) AS total_wage
            FROM t_htma_labor_cost
            GROUP BY report_month, position_type
            ORDER BY report_month ASC
        """)
        rows = cur.fetchall()
        by_month = {}
        for r in rows:
            m = (r.get("report_month") or "").strip()
            if not m:
                continue
            t = (r.get("position_type") or "").strip().lower()
            cnt = int(r.get("position_count") or 0)
            wage = round(float(r.get("total_wage") or 0), 2)
            if m not in by_month:
                by_month[m] = {"total_labor_cost": 0, "position_count": 0, "formal_count": 0, "other_count": 0}
            by_month[m]["total_labor_cost"] += wage
            by_month[m]["position_count"] += cnt
            if t in ("leader", "fulltime"):
                by_month[m]["formal_count"] += cnt
            else:
                by_month[m]["other_count"] += cnt
        months_asc = sorted(by_month.keys())[:limit]
        out = []
        for m in months_asc:
            d = by_month[m]
            d["total_labor_cost"] = round(d["total_labor_cost"], 2)
            out.append({
                "report_month": str(m),
                "total_labor_cost": d["total_labor_cost"],
                "position_count": d["position_count"],
                "formal_count": d["formal_count"],
                "other_count": d["other_count"],
                "target_labor_cost": target,
                "labor_cost_difference": round(target - d["total_labor_cost"], 2),
            })
        return out
    finally:
        conn.close()


def _labor_available_months(limit=24):
    """返回有人力数据的报表月份列表，用于分月展示选择。先查明细表，无则查汇总表；兼容 tuple 行。
    后续扩展：人力成本将支持按自定义起止日期（start_date/end_date）分解计算，与 KPI 自定义时间起点同一模式。"""
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT DISTINCT report_month FROM t_htma_labor_cost ORDER BY report_month DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        out = []
        for r in rows:
            v = r.get("report_month") if isinstance(r, dict) else (r[0] if r else None)
            if v:
                out.append(str(v))
        if not out:
            cur.execute("SELECT report_month FROM t_htma_labor_cost_analysis ORDER BY report_month DESC LIMIT %s", (limit,))
            for r in cur.fetchall():
                v = r.get("report_month") if isinstance(r, dict) else (r[0] if r else None)
                if v and str(v) not in out:
                    out.append(str(v))
        return out
    finally:
        conn.close()


@app.route("/labor")
def page_labor():
    """人力成本独立页：服务端直接取数并渲染，分月展示、每类目到人明细便于查看人员稳定。"""
    if _auth_enabled() and (not _is_logged_in() or not _has_module_access("labor")):
        return Response("您无权访问人力成本模块，请联系管理员。", status=403)
    month = (request.args.get("month") or "").strip()
    report_month, leaders, fulltime, summary = _labor_cost_analysis_response(month or None)
    available_months = _labor_available_months()
    if not available_months and report_month:
        available_months = [report_month]
    # 月份显示为 2025年12月
    def _month_label(ym):
        if not ym or len(ym) < 7:
            return str(ym)
        try:
            y, m = ym.split("-")[0], ym.split("-")[1].lstrip("0") or "0"
            return "%s年%s月" % (y, int(m))
        except Exception:
            return str(ym)
    base_css = (
        "body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:20px;}"
        ".box{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:16px;margin-bottom:12px;}"
        ".label{color:#94a3b8;font-size:0.9rem;}"
        ".value{font-size:1.2rem;font-weight:700;color:#38bdf8;}"
        "table{border-collapse:collapse;width:100%;margin-top:8px;} th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #334155;} th{color:#94a3b8;} .num{text-align:right;}"
        ".empty{color:#64748b;padding:16px;}"
        "a{color:#38bdf8;}"
        ".labor-list{list-style:none;padding:0;margin:0 0 12px 0;} .labor-list li{padding:6px 0;border-bottom:1px solid #334155;} .labor-list li:last-child{border-bottom:none;}"
        ".labor-overview-list li{padding:8px 0;} .labor-summary-list li .label{margin-right:8px;} .labor-summary-list li .value{font-size:1rem;}"
        ".labor-category-list li{padding:8px 0;} .labor-category-list li a{text-decoration:underline;}"
        ".labor-note-item{color:#94a3b8;font-size:0.9rem;padding:8px 0;}"
        "details.labor-parttime-group, details.labor-fulltime-group{margin:12px 0;border:1px solid #334155;border-radius:6px;} details.labor-parttime-group summary, details.labor-fulltime-group summary{padding:10px 12px;cursor:pointer;color:#38bdf8;} details.labor-parttime-group table, details.labor-fulltime-group table{margin:8px 12px 12px;}"
    )
    if report_month is None:
        month_links = ""
        if available_months:
            month_links = "<p class='label'>分月查看： " + " | ".join(
                '<a href="/labor?month=%s">%s</a>' % (m, m) for m in available_months
            ) + "</p>"
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'/><title>人力成本</title><style>%s</style></head><body>"
            "<div class='box'><h2>👥 人力成本 · 全口径与类目</h2>"
            "%s"
            "<p class='empty'><strong>该月暂无数据</strong><br/>请选择上方月份或到 <a href='/import'>数据导入</a> 上传 Excel；"
            "若已导入，留空将显示最近月份。</p></div>"
            "<p><a href='/'>返回看板</a> | <a href='/import'>去导入</a></p></body></html>"
        ) % (base_css, month_links)
        return Response(html, mimetype="text/html; charset=utf-8")
    s = summary or {}
    by_cat = s.get("by_category") or []
    cat_ids = {"全口径": "quankoujing", "组长+组员": "leader-fulltime", "组长": "leader", "组员": "fulltime", "兼职": "parttime", "小时工": "hourly", "保洁": "cleaner", "管理岗": "management"}
    month_label = _month_label(report_month)
    # 类目列表：按类目、按月份表格化展示（组长+组员合并），便于人效分析
    months_asc, by_cat_month = _labor_category_by_month()
    category_display_order = ("全口径",) + LABOR_CATEGORY_ORDER_DISPLAY
    n_cols = 2 + len(months_asc)
    header_cells = ["<th>类目</th>", "<th class='num'>合计(元)</th>"] + [
        "<th class='num'><a href='/labor?month=%s' style='color:#38bdf8;'>%s</a></th>" % (m, _month_label(m).replace("<", "&lt;")) for m in months_asc
    ]
    table_rows = []
    for cat_name in category_display_order:
        cat_data = by_cat_month.get(cat_name, {})
        cid = cat_ids.get(cat_name, "cat")
        safe_name = (cat_name or "").replace("<", "&lt;")
        subtotal = cat_data.get("小计", {})
        total_wage = float(subtotal.get("total_wage") or 0)
        cells = [
            "<td><a href='#detail-%s' style='color:#38bdf8;text-decoration:underline;'>%s</a></td>" % (cid, safe_name),
            "<td class='num'>%s</td>" % "{:,.2f}".format(total_wage),
        ]
        for m in months_asc:
            row_data = cat_data.get(m, {"position_count": 0, "total_wage": 0})
            wage = float(row_data.get("total_wage") or 0)
            cells.append("<td class='num'><a href='/labor?month=%s#detail-%s' style='color:#38bdf8;'>%s</a></td>" % (m, cid, "{:,.2f}".format(wage)))
        table_rows.append("<tr id='row-%s'>%s</tr>" % (cid, "\n".join(cells)))
    table_body = "\n".join(table_rows) if table_rows else "<tr><td colspan='%d' class='empty'>无汇总</td></tr>" % n_cols
    note = (s.get("note") or "").replace("<", "&lt;")
    total_val = float(s.get("total_labor_cost") or 0)
    total_display = "{:,.2f}".format(total_val)
    # 若全口径明显偏低（如仅组长+组员约 13 万、实际应为约 53 万），提示用完整 Excel 重新导入
    incomplete_tip = ""
    if total_val > 0 and total_val < 400000 and len(by_cat) <= 3:
        incomplete_tip = (
            "<p class='label' style='margin-top:12px;padding:10px;background:#334155;border-radius:6px;'>"
            "若全口径应与实际支付一致（如约 53 万），请使用<strong>完整薪资表 Excel</strong>（含所有 sheet：组长、组员、兼职、小时工、保洁、管理岗）在 "
            "<a href='/import'>数据导入</a> 重新上传该月份；或在服务器上执行：<code>python scripts/import_labor_excel_and_analyze.py \"Excel路径\" 报表月份</code> 做整体导入与刷新。</p>"
        )
    def _fmt(v):
        return "{:,.2f}".format(float(v)) if v is not None else "-"
    _person_display = _labor_person_display
    leaders_tbl = "<p class='empty'>共 %d 条</p>" % len(leaders) if not leaders else (
        "<p class='label'>共 %d 人</p>" % len(leaders)
        + "<table><thead><tr><th>#</th><th>岗位</th><th>姓名</th><th>供应商</th><th class='num'>税前应发</th><th class='num'>合计薪资</th><th class='num'>实际薪资</th><th class='num'>奢品奖金</th><th class='num'>实得收入</th><th class='num'>公司成本</th><th class='num'>开票/总成本(元)</th></tr></thead><tbody>"
        + "\n".join(
            "<tr><td class='num'>%d</td><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td></tr>"
            % (
                idx,
                str(row.get("position_name") or "").replace("<", "&lt;"),
                _person_display(row.get("person_name")),
                str(row.get("supplier_name") or "").replace("<", "&lt;") or "-",
                _fmt(row.get("pre_tax_pay")),
                _fmt(row.get("total_salary")),
                _fmt(row.get("actual_salary")),
                _fmt(row.get("luxury_bonus")),
                _fmt(row.get("actual_income")),
                _fmt(row.get("company_cost")),
                _fmt(row.get("total_cost")),
            )
            for idx, row in enumerate(leaders, start=1)
        )
        + "</tbody></table>"
    )
    fulltime_tbl = "<p class='empty'>共 %d 条</p>" % len(fulltime) if not fulltime else (
        "<p class='label'>共 %d 人</p>" % len(fulltime)
        + "<table><thead><tr><th>#</th><th>岗位</th><th>姓名</th><th>供应商</th><th class='num'>工时</th><th class='num'>基本工资</th><th class='num'>绩效</th><th class='num'>岗位补贴</th><th class='num'>合计薪资</th><th class='num'>税前应发</th><th class='num'>奢品</th><th class='num'>实得收入</th><th class='num'>公司成本</th><th class='num'>开票/总成本(元)</th></tr></thead><tbody>"
        + "\n".join(
            "<tr><td class='num'>%d</td><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td></tr>"
            % (
                idx,
                str(row.get("position_name") or "").replace("<", "&lt;"),
                _person_display(row.get("person_name")),
                str(row.get("supplier_name") or "").replace("<", "&lt;") or "-",
                str(row.get("work_hours")) if row.get("work_hours") is not None else "-",
                _fmt(row.get("base_salary")),
                _fmt(row.get("performance")),
                _fmt(row.get("position_allowance")),
                _fmt(row.get("total_salary")),
                _fmt(row.get("pre_tax_pay")),
                _fmt(row.get("luxury_amount")),
                _fmt(row.get("actual_income")),
                _fmt(row.get("company_cost")),
                _fmt(row.get("total_cost")),
            )
            for idx, row in enumerate(fulltime, start=1)
        )
        + "</tbody></table>"
    )
    def _simple_cost_table(items, with_person=True):
        if not items:
            return "<p class='empty'>暂无明细</p>"
        has_person = with_person and any(str(r.get("person_name") or "").strip() for r in items)
        has_supplier = any(str(r.get("supplier_name") or "").strip() for r in items)
        if has_person:
            if has_supplier:
                trs = []
                for idx, r in enumerate(items, start=1):
                    trs.append("<tr><td class='num'>%d</td><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s 元</td></tr>" % (
                        idx,
                        str(r.get("position_name") or "-").replace("<", "&lt;"),
                        _person_display(r.get("person_name")),
                        str(r.get("supplier_name") or "").replace("<", "&lt;") or "-",
                        "{:,.2f}".format(float(r.get("total_cost") or r.get("company_cost") or 0)),
                    ))
                return "<table><thead><tr><th>#</th><th>岗位</th><th>姓名</th><th>供应商</th><th class='num'>开票/总成本(元)</th></tr></thead><tbody>%s</tbody></table>" % "\n".join(trs)
            trs = []
            for idx, r in enumerate(items, start=1):
                trs.append("<tr><td class='num'>%d</td><td>%s</td><td>%s</td><td class='num'>%s 元</td></tr>" % (
                    idx,
                    str(r.get("position_name") or "-").replace("<", "&lt;"),
                    _labor_person_display(r.get("person_name")),
                    "{:,.2f}".format(float(r.get("total_cost") or r.get("company_cost") or 0)),
                ))
            return "<table><thead><tr><th>#</th><th>岗位</th><th>姓名</th><th class='num'>开票/总成本(元)</th></tr></thead><tbody>%s</tbody></table>" % "\n".join(trs)
        trs = []
        for idx, r in enumerate(items, start=1):
            trs.append("<tr><td class='num'>%d</td><td>%s</td><td class='num'>%s 元</td></tr>" % (
                idx,
                str(r.get("position_name") or "-").replace("<", "&lt;"),
                "{:,.2f}".format(float(r.get("total_cost") or r.get("company_cost") or 0)),
            ))
        return "<table><thead><tr><th>#</th><th>岗位/姓名</th><th class='num'>开票/总成本(元)</th></tr></thead><tbody>%s</tbody></table>" % "\n".join(trs)

    def _parttime_section_html():
        """兼职：按属性汇总，点击展开显示全量明细表（店铺名、姓名、城市、属性、入职/离职、工时、时薪、发薪、服务费、税费、费用合计）"""
        by_attr = s.get("parttime_by_attribute") or []
        if not by_attr:
            return _simple_cost_table(s.get("detail_parttime") or [])
        parts = []
        for g in by_attr:
            attr_name = (g.get("attribute") or "其他").replace("<", "&lt;")
            cnt = int(g.get("count") or 0)
            total = float(g.get("total_cost") or 0)
            persons = g.get("persons") or []
            summary_line = "<strong>%s</strong> %d 人 · 费用合计 %s 元" % (attr_name, cnt, "{:,.2f}".format(total))
            # 明细表：全列
            if not persons:
                parts.append("<details class='labor-parttime-group'><summary>%s</summary><p class='empty'>无明细</p></details>" % summary_line)
                continue
            th = "<thead><tr><th>#</th><th>成本计入</th><th>店铺名</th><th>姓名</th><th>城市</th><th>属性</th><th>用人部门</th><th>入职日期</th><th>离职日期</th><th class='num'>总工时</th><th class='num'>普通工时</th><th class='num'>三薪工时</th><th class='num'>时薪</th><th class='num'>发薪金额</th><th class='num'>服务费单价</th><th class='num'>服务费总计</th><th class='num'>税费</th><th class='num'>费用合计(元)</th></tr></thead>"
            rows = []
            for idx, r in enumerate(persons, start=1):
                cost_include = str(r.get("cost_include") or "").replace("<", "&lt;") or "-"
                store_name = str(r.get("store_name") or "").replace("<", "&lt;") or "-"
                person_name = _person_display(r.get("person_name"))
                city = str(r.get("city") or "").replace("<", "&lt;") or "-"
                position_name = str(r.get("position_name") or "").replace("<", "&lt;") or "-"
                dept = str(r.get("department") or "").replace("<", "&lt;") or "-"
                join_date = str(r.get("join_date") or "").replace("<", "&lt;") or "-"
                leave_date = str(r.get("leave_date") or "").replace("<", "&lt;") or "-"
                rows.append(
                    "<tr>"
                    f"<td class='num'>{idx}</td>"
                    f"<td>{cost_include}</td>"
                    f"<td>{store_name}</td>"
                    f"<td>{person_name}</td>"
                    f"<td>{city}</td>"
                    f"<td>{position_name}</td>"
                    f"<td>{dept}</td>"
                    f"<td>{join_date}</td>"
                    f"<td class='num'>{_fmt(r.get('work_hours'))}</td>"
                    f"<td class='num'>{_fmt(r.get('normal_hours'))}</td>"
                    f"<td class='num'>{_fmt(r.get('triple_pay_hours'))}</td>"
                    f"<td class='num'>{_fmt(r.get('hourly_rate'))}</td>"
                    f"<td class='num'>{_fmt(r.get('pay_amount'))}</td>"
                    f"<td class='num'>{_fmt(r.get('service_fee_unit'))}</td>"
                    f"<td class='num'>{_fmt(r.get('service_fee_total'))}</td>"
                    f"<td class='num'>{_fmt(r.get('tax'))}</td>"
                    f"<td class='num'>{_fmt(r.get('total_cost') or r.get('company_cost'))}</td>"
                    "</tr>"
                )
            parts.append("<details class='labor-parttime-group'><summary>%s</summary><table>%s<tbody>%s</tbody></table></details>" % (summary_line, th, "\n".join(rows)))
        return "\n".join(parts)

    def _fulltime_section_html():
        """组员/全职：按岗位汇总，点击展开显示全量明细（与兼职展示逻辑一致）"""
        by_pos = s.get("fulltime_by_position") or []
        if not by_pos:
            return "<p class='empty'>暂无组员明细</p>"
        parts = []
        for g in by_pos:
            pos_name = (g.get("position") or "其他").replace("<", "&lt;")
            cnt = int(g.get("count") or 0)
            total = float(g.get("total_cost") or 0)
            persons = g.get("persons") or []
            summary_line = "<strong>%s</strong> %d 人 · 费用合计 %s 元" % (pos_name, cnt, "{:,.2f}".format(total))
            if not persons:
                parts.append("<details class='labor-fulltime-group'><summary>%s</summary><p class='empty'>无明细</p></details>" % summary_line)
                continue
            th = "<thead><tr><th>#</th><th>岗位</th><th>姓名</th><th>供应商</th><th class='num'>工时</th><th class='num'>基本工资</th><th class='num'>绩效</th><th class='num'>岗位补贴</th><th class='num'>合计薪资</th><th class='num'>税前应发</th><th class='num'>奢品</th><th class='num'>实得收入</th><th class='num'>公司成本</th><th class='num'>开票/总成本(元)</th></tr></thead>"
            rows = ["<tr><td class='num'>%d</td><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td></tr>" % (
                idx,
                str(r.get("position_name") or "").replace("<", "&lt;"),
                _person_display(r.get("person_name")),
                str(r.get("supplier_name") or "").replace("<", "&lt;") or "-",
                str(r.get("work_hours")) if r.get("work_hours") is not None else "-",
                _fmt(r.get("base_salary")), _fmt(r.get("performance")), _fmt(r.get("position_allowance")),
                _fmt(r.get("total_salary")), _fmt(r.get("pre_tax_pay")), _fmt(r.get("luxury_amount")),
                _fmt(r.get("actual_income")), _fmt(r.get("company_cost")), _fmt(r.get("total_cost")),
            ) for idx, r in enumerate(persons, start=1)]
            parts.append("<details class='labor-fulltime-group'><summary>%s</summary><table>%s<tbody>%s</tbody></table></details>" % (summary_line, th, "\n".join(rows)))
        return "\n".join(parts)

    parttime_detail = s.get("detail_parttime") or []
    hourly_detail = s.get("detail_hourly") or []
    cleaner_detail = s.get("detail_cleaner") or []
    management_detail = s.get("detail_management") or []
    month_links_html = ""
    total_positions = sum(int(c.get("position_count") or 0) for c in by_cat if (c.get("name") or "") != "全口径")
    if by_cat and (by_cat[0].get("name") or "") == "全口径":
        total_positions = int(by_cat[0].get("position_count") or 0)
    formal_count = int(s.get("formal_employee_count") or 0)
    other_count = int(s.get("other_labor_count") or 0)
    avg_cost = (total_val / total_positions) if total_positions else 0
    overview_list = _labor_months_overview()
    # 各月人力成本一览：以列表方式展示（每行一月）
    merged_summary_items = []
    if overview_list:
        for row in overview_list:
            ym = row.get("report_month") or ""
            lab = _month_label(ym)
            total = float(row.get("total_labor_cost") or 0)
            target = float(row.get("target_labor_cost") or 0)
            diff = float(row.get("labor_cost_difference") or 0)
            cnt = int(row.get("position_count") or 0)
            merged_summary_items.append(
                "<li><a href='/labor?month=%s' style='color:#38bdf8;'>%s</a> — "
                "全口径(元) %s · 实际支付(元) %s · 统计缺口(元) %s · 人数 %s 人</li>"
                % (ym, lab, "{:,.2f}".format(total), "{:,.2f}".format(target), "{:,.2f}".format(diff), cnt))
    overview_list_html = ""
    if merged_summary_items:
        overview_list_html = "<ul class='labor-list labor-overview-list'>%s</ul>" % "\n".join(merged_summary_items)
    else:
        overview_list_html = "<p class='empty'>暂无各月汇总</p>"
    labor_note = (s.get("labor_cost_difference_note") or "").replace("<", "&lt;")
    # 附表合并：各月一览 + 人力汇总数据 + 当前月/全口径/实际支付/统计缺口 + 说明（仅一次）+ 类目列表（列表项）
    category_list_items = []
    for cat_name in category_display_order:
        cat_data = by_cat_month.get(cat_name, {})
        cid = cat_ids.get(cat_name, "cat")
        safe_name = (cat_name or "").replace("<", "&lt;")
        subtotal = cat_data.get("小计", {})
        total_wage = float(subtotal.get("total_wage") or 0)
        parts = ["合计 %s 元" % "{:,.2f}".format(total_wage)]
        for m in months_asc:
            row_data = cat_data.get(m, {"position_count": 0, "total_wage": 0})
            wage = float(row_data.get("total_wage") or 0)
            lab = _month_label(m).replace("<", "&lt;")
            parts.append("<a href='/labor?month=%s#detail-%s' style='color:#38bdf8;'>%s</a> %s 元" % (m, cid, lab, "{:,.2f}".format(wage)))
        category_list_items.append(
            "<li><a href='#detail-%s' style='color:#38bdf8;'>%s</a> — %s</li>" % (cid, safe_name, " · ".join(parts))
        )
    category_list_html = "<ul class='labor-list labor-category-list'>%s</ul>" % "\n".join(category_list_items) if category_list_items else "<p class='empty'>无类目汇总</p>"
    merged_section = (
        "<div class='box' id='detail-quankoujing' style='margin-bottom:12px;background:#0f172a;border-color:#475569;'>"
        "<h2 style='margin-top:0;color:#e2e8f0;'>📊 人力汇总 · 全口径与类目（列表）</h2>"
        "%s"
        "<p class='label' style='margin-bottom:8px;'>各月人力成本一览（点击月份可查看该类目明细）</p>"
        "%s"
        "<p class='label' style='margin:16px 0 6px;'>人力汇总数据（当前月）</p>"
        "<ul class='labor-list labor-summary-list'>"
        "<li><span class='label'>报表月份</span> <strong>%s</strong></li>"
        "<li><span class='label'>全口径合计</span> <span class='value'>%s 元</span></li>"
        "<li><span class='label'>正式职工（组长+组员）</span> %s 人 · <span class='label'>其他人力</span> %s 人 · <span class='label'>总人数</span> %s 人</li>"
        "<li><span class='label'>按类型人数</span> 组长 %s 人 · 组员 %s 人 · 兼职 %s 人 · 小时工 %s 人 · 保洁 %s 人 · 管理岗 %s 人</li>"
        "<li><span class='label'>人均成本</span> %s 元/人</li>"
        "<li><span class='label'>实际支付（如开票/总成本）</span> %s 元 · <span class='label'>统计缺口</span> <span class='value'>%s 元</span></li>"
        "</ul>"
        "<p class='label labor-note-item' style='margin-top:8px;'>%s</p>"
        "<p class='label' style='margin:16px 0 6px;'>类目列表（点击类目或月份可跳转下方到人明细）</p>"
        "%s"
        "</div>"
    ) % (
        month_links_html or "",
        overview_list_html,
        report_month.replace("<", "&lt;"),
        total_display,
        formal_count,
        other_count,
        total_positions,
        int(s.get("leader_position_count") or 0),
        int(s.get("fulltime_position_count") or 0),
        int(s.get("parttime_position_count") or 0),
        int(s.get("hourly_position_count") or 0),
        int(s.get("cleaner_position_count") or 0),
        int(s.get("management_position_count") or 0),
        "{:,.2f}".format(avg_cost),
        "{:,.2f}".format(float(s.get("target_labor_cost") or 0)),
        "{:,.2f}".format(float(s.get("labor_cost_difference") or 0)),
        labor_note,
        category_list_html,
    )
    month_nav_block = ""
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/><title>人力成本 · 全口径与类目 · %s</title><style>%s</style></head><body>"
        "%s"
        "%s"
        "<span id='detail-leader-fulltime'></span>"
        "<div class='box' id='detail-leader'><h3>组长/职能明细（%s）</h3>%s<p class='label' style='margin-top:8px;font-size:0.85rem;'>若姓名为「-」，请确保薪资表 Excel 含「姓名」列后重新导入。</p></div>"
        "<div class='box' id='detail-fulltime'><h3>组员/全职明细（%s）</h3><p class='label'>按岗位汇总，点击展开查看该岗位下人员及费用明细。</p>%s<p class='label' style='margin-top:8px;font-size:0.85rem;'>若姓名为「-」，请确保薪资表 Excel 含「姓名」列后重新导入。</p></div>"
        "<div class='box' id='detail-parttime'><h3>兼职明细（%s）</h3><p class='label'>按属性汇总，点击展开查看该属性下人员及费用明细。</p>%s</div>"
        "<div class='box' id='detail-hourly'><h3>小时工明细（%s）</h3>%s</div>"
        "<div class='box' id='detail-cleaner'><h3>保洁明细（%s）</h3>%s</div>"
        "<div class='box' id='detail-management'><h3>管理岗明细（%s）</h3>%s</div>"
        "<p class='label' style='margin-top:8px;'>人力成本基本固定，可作为经营分析的成本基准；全口径 = 组长+组员+兼职+小时工+保洁+管理岗。各类目下表均为<strong>到人明细</strong>，便于追踪人员变动与稳定情况。与「开票金额/总成本」汇总表口径一致（如沈阳 斗米全职+管理组+兼职、中锐/快聘小时工、保洁 合计约 53.25 万）。</p>"
        "<p><a href='/'>返回看板</a> | <a href='/import'>数据导入</a> | <a href='/labor_analysis'>人力分析</a> | <a href='/labor'>刷新</a> | <button type='button' id='btnLaborClear' style='margin-left:8px;padding:6px 12px;background:#64748b;color:#e2e8f0;border:1px solid #475569;border-radius:6px;cursor:pointer;font-size:0.9rem;'>清空人力数据</button></p>"
    "<script>"
    "document.getElementById('btnLaborClear') && document.getElementById('btnLaborClear').addEventListener('click', function(){"
    "  if(!confirm('确定清空全部人力明细与汇总数据？清空后需重新导入 Excel。')) return;"
    "  var f = new FormData(); f.append('confirm','yes');"
    "  fetch('/api/labor_cost_clear', { method:'POST', body: f, credentials:'include' })"
    "    .then(function(r){ return r.json(); })"
    "    .then(function(d){ alert(d.success ? d.message : (d.message||'失败')); if(d.success) location.reload(); })"
    "    .catch(function(){ alert('请求失败'); });"
    "});"
    "</script></body></html>"
    ) % (
        report_month.replace("<", "&lt;"),
        base_css,
        merged_section,
        month_nav_block,
        month_label.replace("<", "&lt;"), (leaders_tbl or "").replace("%", "%%"),
        month_label.replace("<", "&lt;"), (_fulltime_section_html() or "").replace("%", "%%"),
        month_label.replace("<", "&lt;"), (_parttime_section_html() or "").replace("%", "%%"),
        month_label.replace("<", "&lt;"), (_simple_cost_table(hourly_detail) or "").replace("%", "%%"),
        month_label.replace("<", "&lt;"), (_simple_cost_table(cleaner_detail) or "").replace("%", "%%"),
        month_label.replace("<", "&lt;"), (_simple_cost_table(management_detail) or "").replace("%", "%%"),
    )
    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/api/labor_cost_refresh_analysis", methods=["POST", "OPTIONS"])
def api_labor_cost_refresh_analysis():
    """从 t_htma_labor_cost 汇总刷新 t_htma_labor_cost_analysis，供 OpenClaw 或定时任务调用。"""
    if request.method == "OPTIONS":
        return "", 204
    try:
        conn = get_conn()
        n = refresh_labor_cost_analysis(conn)
        conn.close()
        return jsonify({"success": True, "months_refreshed": n})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/labor_cost_clear", methods=["POST", "OPTIONS"])
def api_labor_cost_clear():
    """清空人力明细与汇总表（仅当用户明确确认时执行）。部署脚本不会清空数据，需在此手工触发。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权操作人力模块"}), 403
    confirm = (request.form.get("confirm") or request.args.get("confirm") or "").strip()
    try:
        j = request.get_json(silent=True) or {}
        if not confirm:
            confirm = (j.get("confirm") or "").strip()
    except Exception:
        pass
    if confirm != "yes":
        return jsonify({"success": False, "message": "请传 confirm=yes 确认清空（将删除 t_htma_labor_cost 与 t_htma_labor_cost_analysis 全部数据）"}), 400
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE t_htma_labor_cost")
        cur.execute("TRUNCATE TABLE t_htma_labor_cost_analysis")
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "已清空人力明细与汇总表，可重新导入 Excel"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ---------- 人力分析 Tab：时间段拆解、经营/管理、人效 ----------
def _labor_analysis_month_weights(start_date, end_date):
    """给定日期区间，返回涉及的月份及每个月的权重（该月在区间内天数/该月总天数）。"""
    if not start_date or not end_date:
        return []
    try:
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
    except Exception:
        return []
    if start_date > end_date:
        return []
    out = []
    from calendar import monthrange
    cur = start_date
    while cur <= end_date:
        ym = cur.strftime("%Y-%m")
        month_start = cur.replace(day=1)
        _, last_day = monthrange(cur.year, cur.month)
        month_end = cur.replace(day=last_day)
        days_in_month = last_day
        range_start = max(month_start, start_date)
        range_end = min(month_end, end_date)
        days_in_range = (range_end - range_start).days + 1
        weight = days_in_range / days_in_month if days_in_month else 0
        if weight > 0:
            out.append((ym, round(weight, 6)))
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1, day=1)
        else:
            cur = cur.replace(month=cur.month + 1, day=1)
    return out


def _labor_analysis_mapping_effective_for_month(conn, report_month):
    """返回在 report_month 当月生效的映射行。report_month='YYYY-MM'。"""
    try:
        y, m = report_month.split("-")[0], report_month.split("-")[1]
        month_start = "%s-%s-01" % (y, m)
        from calendar import monthrange
        last = monthrange(int(y), int(m))[1]
        month_end = "%s-%s-%02d" % (y, m, last)
    except Exception:
        return []
    cur = conn.cursor()
    try:
        try:
            cur.execute("""
                SELECT id, sales_category, sales_category_mid, sales_category_large_code, sales_category_mid_code,
                       cost_type, labor_position_name, match_type, sort_order
                FROM t_htma_labor_category_mapping
                WHERE (effective_from IS NULL OR effective_from <= %s)
                  AND (effective_to IS NULL OR effective_to >= %s)
                ORDER BY cost_type, sort_order, id
            """, (month_end, month_start))
        except Exception:
            try:
                cur.execute("""
                    SELECT id, sales_category, sales_category_mid, cost_type, labor_position_name, match_type, sort_order
                    FROM t_htma_labor_category_mapping
                    WHERE (effective_from IS NULL OR effective_from <= %s)
                      AND (effective_to IS NULL OR effective_to >= %s)
                    ORDER BY cost_type, sort_order, id
                """, (month_end, month_start))
            except Exception:
                cur.execute("""
                    SELECT id, sales_category, cost_type, labor_position_name, match_type, sort_order
                    FROM t_htma_labor_category_mapping
                    WHERE (effective_from IS NULL OR effective_from <= %s)
                      AND (effective_to IS NULL OR effective_to >= %s)
                    ORDER BY cost_type, sort_order, id
                """, (month_end, month_start))
        rows = cur.fetchall()
        for r in rows:
            if r is None:
                continue
            if "sales_category_mid" not in r:
                r["sales_category_mid"] = ""
            if "sales_category_large_code" not in r:
                r["sales_category_large_code"] = ""
            if "sales_category_mid_code" not in r:
                r["sales_category_mid_code"] = ""
        return rows
    except Exception:
        return []
    finally:
        cur.close()


def _labor_analysis_position_matches_mapping(position_name, labor_position_name, match_type):
    """判断 t_htma_labor_cost.position_name 是否匹配映射行的 labor_position_name。"""
    if not position_name:
        return False
    pos = (position_name or "").strip()
    lab = (labor_position_name or "").strip()
    if not lab:
        return False
    if (match_type or "").strip().lower() == "exact":
        return pos == lab
    return pos == lab or pos.startswith(lab) or lab in pos


def _labor_analysis_get_cost(row):
    """单条人力记录的成本金额。"""
    return float(row.get("total_cost") or row.get("company_cost") or 0)


@app.route("/api/labor_analysis/categories", methods=["GET", "OPTIONS"])
def api_labor_analysis_categories():
    """返回销售日报中的大类+中类（供配置映射，与 t_htma_sale 一致）。结构：categories 平铺大类；categories_tree 为大类下挂中类列表。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    try:
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT DISTINCT
                    COALESCE(TRIM(category_large_code), '') AS category_large_code,
                    COALESCE(TRIM(category_large), '') AS category_large,
                    COALESCE(TRIM(category_mid_code), '') AS category_mid_code,
                    COALESCE(TRIM(category_mid), '') AS category_mid
                FROM t_htma_sale
                WHERE (COALESCE(TRIM(category_large), '') != '' OR COALESCE(TRIM(category_large_code), '') != '')
                ORDER BY category_large_code, category_large, category_mid_code, category_mid
            """)
            rows = cur.fetchall()
        except Exception:
            try:
                cur.execute("""
                    SELECT DISTINCT
                        COALESCE(TRIM(category_large), '') AS category_large_code,
                        COALESCE(TRIM(category_large), '') AS category_large,
                        '' AS category_mid_code, '' AS category_mid
                    FROM t_htma_sale
                    WHERE (category_large IS NOT NULL AND TRIM(category_large) != '')
                    ORDER BY category_large
                """)
                rows = cur.fetchall()
            except Exception:
                try:
                    cur.execute("""
                        SELECT DISTINCT COALESCE(TRIM(category), '') AS category_large_code,
                               COALESCE(TRIM(category), '') AS category_large,
                               '' AS category_mid_code, '' AS category_mid
                        FROM t_htma_sale
                        WHERE (category IS NOT NULL AND TRIM(category) != '')
                        ORDER BY 1
                    """)
                    rows = cur.fetchall()
                except Exception:
                    rows = []
        conn.close()
        # 大类去重 + 每个大类下中类列表
        large_seen = set()
        categories = []
        categories_tree = []
        for r in rows:
            lcode = (r.get("category_large_code") or "").strip()
            lname = (r.get("category_large") or "").strip()
            if not lname and lcode:
                lname = lcode
            if not lname:
                continue
            mcode = (r.get("category_mid_code") or "").strip()
            mname = (r.get("category_mid") or "").strip()
            if not mname and mcode:
                mname = mcode
            key = (lcode, lname)
            if key not in large_seen:
                large_seen.add(key)
                categories.append({"category_large_code": lcode, "category_large": lname})
                categories_tree.append({
                    "category_large_code": lcode,
                    "category_large": lname,
                    "mids": []
                })
            # 找到对应大类节点并追加中类（去重）
            for node in categories_tree:
                if (node["category_large_code"], node["category_large"]) == (lcode, lname):
                    if (mcode or mname) and not any(x.get("category_mid") == mname and x.get("category_mid_code") == mcode for x in node["mids"]):
                        node["mids"].append({"category_mid_code": mcode, "category_mid": mname or "-"})
                    break
        return jsonify({"success": True, "categories": categories, "categories_tree": categories_tree})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/labor_analysis/labor_positions", methods=["GET", "POST", "HEAD", "OPTIONS"])
def api_labor_analysis_labor_positions():
    """拉取所有人力成本汇总岗位列表，以组长表为准（组长/leader 优先，与薪资表、组长表岗位一致）。GET/POST 均返回同一列表。"""
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "HEAD":
        return "", 200
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    try:
        conn = get_conn()
        cur = conn.cursor()
        # 组长(leader) 优先，再全职、兼职等；岗位名去重，与 t_htma_labor_cost.position_name 一致
        try:
            cur.execute("""
                SELECT DISTINCT COALESCE(TRIM(position_name), '') AS position_name,
                       COALESCE(TRIM(position_type), '') AS position_type
                FROM t_htma_labor_cost
                WHERE (position_name IS NOT NULL AND TRIM(position_name) != '')
                ORDER BY FIELD(position_type, 'leader', 'fulltime', 'parttime', 'hourly', 'cleaner', 'management'),
                         position_name
            """)
            rows = cur.fetchall()
        except Exception:
            try:
                cur.execute("""
                    SELECT DISTINCT COALESCE(TRIM(position_name), '') AS position_name,
                           COALESCE(TRIM(position_type), '') AS position_type
                    FROM t_htma_labor_cost
                    WHERE (position_name IS NOT NULL AND TRIM(position_name) != '')
                    ORDER BY position_type, position_name
                """)
                rows = cur.fetchall()
            except Exception:
                rows = []
        conn.close()
        type_label = {"leader": "组长", "fulltime": "全职", "parttime": "兼职", "hourly": "小时工", "cleaner": "保洁", "management": "管理岗"}
        positions = []
        seen = set()
        for r in rows:
            name = (r.get("position_name") or "").strip()
            if not name:
                continue
            if name in seen:
                continue
            seen.add(name)
            ptype = (r.get("position_type") or "").strip().lower()
            positions.append({
                "position_name": name,
                "position_type": ptype,
                "position_type_label": type_label.get(ptype, ptype or "其他"),
            })
        return jsonify({"success": True, "positions": positions})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/labor_analysis/mapping", methods=["GET", "POST", "OPTIONS"])
def api_labor_analysis_mapping():
    """获取或保存 销售类目–人力岗位 映射（含生效日期）。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    try:
        conn = get_conn()
        cur = conn.cursor()
        if request.method == "GET":
            try:
                cur.execute("""
                    SELECT id, sales_category, sales_category_mid, sales_category_large_code, sales_category_mid_code,
                           cost_type, labor_position_name, match_type,
                           effective_from, effective_to, sort_order, created_at, updated_at
                    FROM t_htma_labor_category_mapping
                    ORDER BY cost_type, sort_order, id
                """)
                rows = cur.fetchall()
            except Exception:
                try:
                    cur.execute("""
                        SELECT id, sales_category, sales_category_mid, cost_type, labor_position_name, match_type,
                               effective_from, effective_to, sort_order, created_at, updated_at
                        FROM t_htma_labor_category_mapping
                        ORDER BY cost_type, sort_order, id
                    """)
                    rows = cur.fetchall()
                except Exception:
                    try:
                        cur.execute("""
                            SELECT id, sales_category, cost_type, labor_position_name, match_type,
                                   effective_from, effective_to, sort_order, created_at, updated_at
                            FROM t_htma_labor_category_mapping
                            ORDER BY cost_type, sort_order, id
                        """)
                        rows = cur.fetchall()
                    except Exception:
                        rows = []
            conn.close()
            items = []
            for r in rows:
                r = r or {}
                items.append({
                    "id": r.get("id"),
                    "sales_category": r.get("sales_category") or "",
                    "sales_category_mid": r.get("sales_category_mid") or "",
                    "sales_category_large_code": r.get("sales_category_large_code") or "",
                    "sales_category_mid_code": r.get("sales_category_mid_code") or "",
                    "cost_type": r.get("cost_type") or "",
                    "labor_position_name": r.get("labor_position_name") or "",
                    "match_type": r.get("match_type") or "prefix",
                    "effective_from": r.get("effective_from").strftime("%Y-%m-%d") if r.get("effective_from") else None,
                    "effective_to": r.get("effective_to").strftime("%Y-%m-%d") if r.get("effective_to") else None,
                    "sort_order": r.get("sort_order", 0),
                })
            return jsonify({"success": True, "items": items})
        # POST: save one or list
        data = request.get_json(silent=True) or {}
        items = data.get("items")
        if not items:
            items = [data] if data.get("labor_position_name") or data.get("sales_category") or data.get("sales_category_large_code") else []
        for it in items:
            sid = it.get("id")
            sales_category = (it.get("sales_category") or "").strip() or ""
            sales_category_mid = (it.get("sales_category_mid") or "").strip() or ""
            sales_category_large_code = (it.get("sales_category_large_code") or "").strip() or ""
            sales_category_mid_code = (it.get("sales_category_mid_code") or "").strip() or ""
            cost_type = (it.get("cost_type") or "operational").strip().lower()
            if cost_type not in ("operational", "management"):
                cost_type = "operational"
            labor_position_name = (it.get("labor_position_name") or "").strip()
            match_type = (it.get("match_type") or "prefix").strip().lower() or "prefix"
            if match_type not in ("exact", "prefix"):
                match_type = "prefix"
            effective_from = (it.get("effective_from") or "").strip() or None
            effective_to = (it.get("effective_to") or "").strip() or None
            sort_order = int(it.get("sort_order", 0))
            if not labor_position_name and not sales_category and not sales_category_large_code:
                continue
            try:
                if sid:
                    cur.execute("""
                        UPDATE t_htma_labor_category_mapping
                        SET sales_category=%s, sales_category_mid=%s, sales_category_large_code=%s, sales_category_mid_code=%s,
                            cost_type=%s, labor_position_name=%s, match_type=%s,
                            effective_from=%s, effective_to=%s, sort_order=%s, updated_at=NOW()
                        WHERE id=%s
                    """, (sales_category, sales_category_mid, sales_category_large_code, sales_category_mid_code,
                          cost_type, labor_position_name, match_type,
                          effective_from or None, effective_to or None, sort_order, sid))
                else:
                    cur.execute("""
                        INSERT INTO t_htma_labor_category_mapping
                        (sales_category, sales_category_mid, sales_category_large_code, sales_category_mid_code,
                         cost_type, labor_position_name, match_type, effective_from, effective_to, sort_order)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (sales_category, sales_category_mid, sales_category_large_code, sales_category_mid_code,
                          cost_type, labor_position_name, match_type, effective_from or None, effective_to or None, sort_order))
            except Exception:
                if sid:
                    cur.execute("""
                        UPDATE t_htma_labor_category_mapping
                        SET sales_category=%s, sales_category_mid=%s, cost_type=%s, labor_position_name=%s, match_type=%s,
                            effective_from=%s, effective_to=%s, sort_order=%s, updated_at=NOW()
                        WHERE id=%s
                    """, (sales_category, sales_category_mid, cost_type, labor_position_name, match_type,
                          effective_from or None, effective_to or None, sort_order, sid))
                else:
                    cur.execute("""
                        INSERT INTO t_htma_labor_category_mapping
                        (sales_category, sales_category_mid, cost_type, labor_position_name, match_type, effective_from, effective_to, sort_order)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (sales_category, sales_category_mid, cost_type, labor_position_name, match_type, effective_from or None, effective_to or None, sort_order))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "已保存"})
    except Exception as e:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return jsonify({"success": False, "message": str(e)}), 500


def _labor_analysis_overview(conn, start_date, end_date):
    """经营/管理总成本、总人数（全量不去重）、销售、毛利、人效。"""
    weights = _labor_analysis_month_weights(start_date, end_date)
    if not weights:
        return {"operational_cost": 0, "management_cost": 0, "total_cost": 0, "total_headcount": 0,
                "total_sale": 0, "total_profit": 0, "sales_per_cost": 0, "profit_per_cost": 0,
                "sales_per_capita": 0, "profit_per_capita": 0, "profit_cost_ratio": 0}
    cur = conn.cursor()
    # 销售
    try:
        cur.execute("""
            SELECT COALESCE(SUM(sale_amount),0) AS total_sale, COALESCE(SUM(gross_profit),0) AS total_profit
            FROM t_htma_sale WHERE data_date BETWEEN %s AND %s
        """, (start_date, end_date))
        row = cur.fetchone()
        total_sale = float(row.get("total_sale") or 0)
        total_profit = float(row.get("total_profit") or 0)
    except Exception:
        total_sale = total_profit = 0
    operational_cost = 0.0
    management_cost = 0.0
    operational_head = 0.0
    management_head = 0.0
    for ym, weight in weights:
        mapping = _labor_analysis_mapping_effective_for_month(conn, ym)
        op_positions = set()
        mgr_positions = set()
        for m in mapping:
            cost_type = (m.get("cost_type") or "").strip().lower()
            lab = (m.get("labor_position_name") or "").strip()
            if cost_type == "management":
                mgr_positions.add((lab, m.get("match_type") or "prefix"))
            else:
                op_positions.add((lab, m.get("match_type") or "prefix"))
        try:
            cur.execute("""
                SELECT position_name, position_type, person_name,
                       COALESCE(total_cost, company_cost) AS cost
                FROM t_htma_labor_cost WHERE report_month = %s
            """, (ym,))
            labor_rows = cur.fetchall()
        except Exception:
            labor_rows = []
        # 无任何映射时，全部人力计入经营（与销售匹配），确保「所有销售都对应经营人力成本」
        no_mapping = not op_positions and not mgr_positions
        for r in labor_rows:
            pos = (r.get("position_name") or "").strip()
            cost = float(r.get("cost") or 0) * weight
            matched_mgr = any(_labor_analysis_position_matches_mapping(pos, lab, mt) for lab, mt in mgr_positions)
            matched_op = any(_labor_analysis_position_matches_mapping(pos, lab, mt) for lab, mt in op_positions)
            if matched_mgr:
                management_cost += cost
                management_head += weight
            elif matched_op or no_mapping:
                operational_cost += cost
                operational_head += weight
            else:
                management_cost += cost
                management_head += weight
    total_cost = operational_cost + management_cost
    total_headcount = operational_head + management_head
    total_sale = total_sale
    total_profit = total_profit
    sales_per_cost = total_sale / total_cost if total_cost else 0
    profit_per_cost = total_profit / total_cost if total_cost else 0
    sales_per_capita = total_sale / total_headcount if total_headcount else 0
    profit_per_capita = total_profit / total_headcount if total_headcount else 0
    profit_cost_ratio = total_profit / total_cost if total_cost else 0
    return {
        "operational_cost": round(operational_cost, 2),
        "management_cost": round(management_cost, 2),
        "total_cost": round(total_cost, 2),
        "total_headcount": round(total_headcount, 2),
        "total_sale": round(total_sale, 2),
        "total_profit": round(total_profit, 2),
        "sales_per_cost": round(sales_per_cost, 4),
        "profit_per_cost": round(profit_per_cost, 4),
        "sales_per_capita": round(sales_per_capita, 2),
        "profit_per_capita": round(profit_per_capita, 2),
        "profit_cost_ratio": round(profit_cost_ratio, 4),
    }


@app.route("/api/labor_analysis/overview", methods=["GET", "OPTIONS"])
def api_labor_analysis_overview():
    """人力分析总览：经营/管理成本、人数（全量）、销售、毛利、人效。参数 start_date, end_date。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    start_date = (request.args.get("start_date") or "").strip()[:10]
    end_date = (request.args.get("end_date") or "").strip()[:10]
    if not start_date or not end_date:
        return jsonify({"success": False, "message": "请提供 start_date 与 end_date"}), 400
    try:
        conn = get_conn()
        data = _labor_analysis_overview(conn, start_date, end_date)
        conn.close()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


def _labor_analysis_by_category(conn, start_date, end_date):
    """按经营类目：人力成本、人数、销售、毛利、人效。以销售日报大类为准（按大类代码匹配），全部展示；未配置映射的类目人力为0。"""
    weights = _labor_analysis_month_weights(start_date, end_date)
    cur = conn.cursor()
    # 销售日报中所有大类：按大类代码分组（与看板一致），无代码时用名称
    try:
        cur.execute("""
            SELECT COALESCE(NULLIF(TRIM(category_large_code), ''), TRIM(category_large)) AS code,
                   COALESCE(MAX(TRIM(category_large)), '') AS cat,
                   COALESCE(SUM(sale_amount),0) AS s, COALESCE(SUM(gross_profit),0) AS p
            FROM t_htma_sale
            WHERE data_date BETWEEN %s AND %s AND (COALESCE(TRIM(category_large_code), '') != '' OR (category_large IS NOT NULL AND TRIM(category_large) != ''))
            GROUP BY COALESCE(NULLIF(TRIM(category_large_code), ''), TRIM(category_large))
            ORDER BY code
        """, (start_date, end_date))
        sales_rows = cur.fetchall()
        sales_by_code = {r.get("code") or "": (float(r.get("s") or 0), float(r.get("p") or 0)) for r in sales_rows}
        code_to_name = {r.get("code") or "": (r.get("cat") or "") for r in sales_rows}
    except Exception:
        sales_by_code = {}
        code_to_name = {}
    # 经营类目及其对应岗位：按大类代码匹配（优先），无代码时按名称兼容旧数据
    cat_positions = {}
    for ym, _ in weights:
        for m in _labor_analysis_mapping_effective_for_month(conn, ym):
            if (m.get("cost_type") or "").strip().lower() != "operational":
                continue
            large_code = (m.get("sales_category_large_code") or "").strip()
            cat_name = (m.get("sales_category") or "").strip()
            key = large_code if large_code else cat_name
            if not key:
                continue
            if key not in cat_positions:
                cat_positions[key] = set()
            cat_positions[key].add(((m.get("labor_position_name") or "").strip(), m.get("match_type") or "prefix"))
    # 以销售大类为全集，无映射的类目人力为 0
    out = []
    for code in sorted(sales_by_code.keys()):
        positions = cat_positions.get(code, set()) or cat_positions.get(code_to_name.get(code, ""), set())
        cost_total = 0.0
        headcount = 0.0
        by_type = {"leader": {"cost": 0, "count": 0}, "fulltime": {"cost": 0, "count": 0}, "parttime": {"cost": 0, "count": 0}, "other": {"cost": 0, "count": 0}}
        for ym, weight in weights:
            mapping = _labor_analysis_mapping_effective_for_month(conn, ym)
            op_set = set()
            for m in mapping:
                if (m.get("cost_type") or "").strip().lower() != "operational":
                    continue
                large_code_m = (m.get("sales_category_large_code") or "").strip()
                cat_name_m = (m.get("sales_category") or "").strip()
                if large_code_m and large_code_m != code:
                    continue
                if not large_code_m and cat_name_m != (code_to_name.get(code) or ""):
                    continue
                op_set.add(((m.get("labor_position_name") or "").strip(), m.get("match_type") or "prefix"))
            try:
                cur.execute("""
                    SELECT position_name, position_type, COALESCE(total_cost, company_cost) AS cost
                    FROM t_htma_labor_cost WHERE report_month = %s
                """, (ym,))
                rows = cur.fetchall()
            except Exception:
                rows = []
            for r in rows:
                pos = (r.get("position_name") or "").strip()
                if not any(_labor_analysis_position_matches_mapping(pos, lab, mt) for lab, mt in op_set):
                    continue
                c = float(r.get("cost") or 0) * weight
                cost_total += c
                headcount += weight
                pt = (r.get("position_type") or "").strip().lower()
                if pt in by_type:
                    by_type[pt]["cost"] += c
                    by_type[pt]["count"] += weight
                else:
                    by_type["other"]["cost"] += c
                    by_type["other"]["count"] += weight
        s, p = sales_by_code.get(code, (0, 0))
        out.append({
            "category_large_code": code,
            "category": code_to_name.get(code, "") or code,
            "labor_cost": round(cost_total, 2),
            "headcount": round(headcount, 2),
            "sale": round(s, 2),
            "profit": round(p, 2),
            "sales_per_cost": round(s / cost_total, 4) if cost_total else 0,
            "profit_per_cost": round(p / cost_total, 4) if cost_total else 0,
            "sales_per_capita": round(s / headcount, 2) if headcount else 0,
            "profit_cost_ratio": round(p / cost_total, 4) if cost_total else 0,
            "by_position_type": {k: {"cost": round(v["cost"], 2), "count": round(v["count"], 2)} for k, v in by_type.items()},
        })
    return out


@app.route("/api/labor_analysis/by_category", methods=["GET", "OPTIONS"])
def api_labor_analysis_by_category():
    """按经营类目返回人力成本、人数、销售、毛利、人效及组长/全职/兼职分项。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    start_date = (request.args.get("start_date") or "").strip()[:10]
    end_date = (request.args.get("end_date") or "").strip()[:10]
    if not start_date or not end_date:
        return jsonify({"success": False, "message": "请提供 start_date 与 end_date"}), 400
    try:
        conn = get_conn()
        data = _labor_analysis_by_category(conn, start_date, end_date)
        conn.close()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


def _labor_analysis_management(conn, start_date, end_date):
    """管理人力：按岗位拆开展示，每岗位可下沉到具体人名及分摊成本。"""
    weights = _labor_analysis_month_weights(start_date, end_date)
    cur = conn.cursor()
    # 管理岗位列表（映射中 cost_type=management）
    mgr_positions = set()
    for ym, _ in weights:
        for m in _labor_analysis_mapping_effective_for_month(conn, ym):
            if (m.get("cost_type") or "").strip().lower() != "management":
                continue
            mgr_positions.add(((m.get("labor_position_name") or "").strip(), m.get("match_type") or "prefix"))
    if not mgr_positions:
        return {"total_cost": 0, "total_headcount": 0, "by_position": [], "persons": []}
    by_position = {}
    persons = []
    for ym, weight in weights:
        try:
            cur.execute("""
                SELECT position_name, person_name, COALESCE(total_cost, company_cost) AS cost
                FROM t_htma_labor_cost WHERE report_month = %s
            """, (ym,))
            rows = cur.fetchall()
        except Exception:
            rows = []
        for r in rows:
            pos = (r.get("position_name") or "").strip()
            if not any(_labor_analysis_position_matches_mapping(pos, lab, mt) for lab, mt in mgr_positions):
                continue
            cost = float(r.get("cost") or 0) * weight
            pname = _labor_person_display(r.get("person_name") or "")
            if pos not in by_position:
                by_position[pos] = {"position_name": pos, "cost": 0.0, "headcount": 0.0, "persons": []}
            by_position[pos]["cost"] += cost
            by_position[pos]["headcount"] += weight
            by_position[pos]["persons"].append({"person_name": pname, "prorated_cost": round(cost, 2)})
            persons.append({"position_name": pos, "person_name": pname, "prorated_cost": round(cost, 2)})
    total_cost = sum(p["cost"] for p in by_position.values())
    total_headcount = sum(p["headcount"] for p in by_position.values())
    by_position_list = []
    for pos_name, p in by_position.items():
        by_position_list.append({
            "position_name": pos_name,
            "cost": round(p["cost"], 2),
            "headcount": round(p["headcount"], 2),
            "persons": p["persons"],
        })
    return {
        "total_cost": round(total_cost, 2),
        "total_headcount": round(total_headcount, 2),
        "by_position": by_position_list,
        "persons": persons,
    }


@app.route("/api/labor_analysis/management", methods=["GET", "OPTIONS"])
def api_labor_analysis_management():
    """管理人力：按岗位拆分，可下沉到具体人名。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    start_date = (request.args.get("start_date") or "").strip()[:10]
    end_date = (request.args.get("end_date") or "").strip()[:10]
    if not start_date or not end_date:
        return jsonify({"success": False, "message": "请提供 start_date 与 end_date"}), 400
    try:
        conn = get_conn()
        data = _labor_analysis_management(conn, start_date, end_date)
        conn.close()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/labor_analysis")
def page_labor_analysis():
    """人力分析 Tab 页：时间段选择、经营/管理总览、类目明细、管理按岗位与人名。"""
    if _auth_enabled() and (not _is_logged_in() or not _has_module_access("labor")):
        return Response("您无权访问人力分析，请联系管理员。", status=403)
    return send_from_directory(app.static_folder, "labor_analysis.html")


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


@app.route("/api/import_from_downloads", methods=["POST", "OPTIONS"])
def api_import_from_downloads():
    """从配置的下载目录（IMPORT_DOWNLOADS_DIR 或 项目/downloads）自动导入 Excel，并执行去重与刷新，确保数据完整可靠"""
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
            "hint": "请将 Excel 放入该目录后重试，或使用「数据导入」页面上传",
        }), 400

    conn = None
    result = {"sale_daily": 0, "sale_summary": 0, "stock": 0, "product_master": 0, "profit_refreshed": 0, "errors": [], "from_downloads": True, "directory": directory}
    try:
        conn = get_conn()
        cur = conn.cursor()
        has_sale_daily = "sale_daily" in files
        has_sale_summary = "sale_summary" in files
        if has_sale_daily:
            cnt, diag = import_sale_daily(files["sale_daily"], conn)
            result["sale_daily"] = cnt
            if diag:
                result.setdefault("diagnostics", []).append(diag)
        if has_sale_summary:
            cnt, diag = import_sale_summary(files["sale_summary"], conn, overwrite_on_duplicate=has_sale_daily)
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
    """导出：商品从 t_htma_products，品类从 t_htma_category_profit。支持 period、start_date、end_date、category、sku_code、export_type=category|product"""
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
                # 品类：优先从 t_htma_category_profit，无则从 t_htma_profit 汇总
                try:
                    cur.execute("""
                        SELECT category, category_large, category_mid, category_small,
                               total_sale, total_profit, profit_rate, sale_count, period_start, period_end
                        FROM t_htma_category_profit
                        WHERE store_id = %s
                        ORDER BY total_sale DESC
                    """, (STORE_ID,))
                    rows = cur.fetchall()
                    headers = ["品类", "大类", "中类", "小类", "总销售额", "总毛利", "毛利率", "销售笔数", "周期起", "周期止"]
                    data_rows = []
                    for r in rows:
                        rate = float(r["profit_rate"] or 0) * 100 if r["profit_rate"] else 0
                        data_rows.append([
                            r["category"] or "未分类",
                            r["category_large"] or "",
                            r["category_mid"] or "",
                            r["category_small"] or "",
                            str(round(float(r["total_sale"] or 0), 2)),
                            str(round(float(r["total_profit"] or 0), 2)),
                            f"{rate:.2f}%",
                            str(r["sale_count"] or 0),
                            str(r["period_start"]) if r.get("period_start") else "",
                            str(r["period_end"]) if r.get("period_end") else "",
                        ])
                except Exception:
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
                # 商品：优先从 t_htma_products（含条码），无则从 t_htma_sale 汇总
                try:
                    cat_cond = ""
                    cat_params = [STORE_ID]
                    if params and len(params) > 2:
                        for i, p in enumerate(params[2:], 2):
                            if "category" in str(request.args):
                                break
                        # 简化：仅 store_id 筛选
                    cur.execute("""
                        SELECT sku_code, product_name, raw_name, spec, barcode, brand_name,
                               category, category_large, category_mid, category_small,
                               unit_price, sale_qty, sale_amount, gross_profit
                        FROM t_htma_products
                        WHERE store_id = %s
                        ORDER BY sale_amount DESC
                    """, (STORE_ID,))
                    rows = cur.fetchall()
                    headers = ["商品编码", "品名", "规格", "条码", "品牌", "品类", "大类", "中类", "小类", "售价", "销量", "销售额", "毛利"]
                    data_rows = []
                    for r in rows:
                        data_rows.append([
                            r["sku_code"] or "",
                            (r["product_name"] or r["raw_name"] or "")[:64],
                            r["spec"] or "",
                            r["barcode"] or "",
                            r["brand_name"] or "",
                            r["category"] or "未分类",
                            r["category_large"] or "",
                            r["category_mid"] or "",
                            r["category_small"] or "",
                            str(round(float(r["unit_price"] or 0), 2)),
                            str(float(r["sale_qty"] or 0)),
                            str(round(float(r["sale_amount"] or 0), 2)),
                            str(round(float(r["gross_profit"] or 0), 2)),
                        ])
                except Exception:
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
        fname = "htma_category.csv" if export_type == "category" else "htma_products.csv"
        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    finally:
        conn.close()


@app.route("/api/date_range")
def api_date_range():
    """返回自定义日期选择器的可选范围；起止默认值为库中有数据的最早/最晚日期（销售表）。"""
    out = {"min_date": "2010-01-01", "max_date": "2030-12-31", "data_min_date": None, "data_max_date": None}
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MIN(data_date) AS min_d, MAX(data_date) AS max_d FROM t_htma_sale WHERE store_id = %s",
                (STORE_ID,),
            )
            row = cur.fetchone()
        conn.close()
        if row and row.get("min_d") and row.get("max_d"):
            out["data_min_date"] = row["min_d"].strftime("%Y-%m-%d") if hasattr(row["min_d"], "strftime") else str(row["min_d"])[:10]
            out["data_max_date"] = row["max_d"].strftime("%Y-%m-%d") if hasattr(row["max_d"], "strftime") else str(row["max_d"])[:10]
    except Exception:
        pass
    return jsonify(out)


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
            "start_date": start_d or None,
            "end_date": end_d or None,
        })
    finally:
        conn.close()


def _date_condition(period, start_date=None, end_date=None):
    """返回 (date_cond, params) 用于 SQL。若 start_date/end_date 均提供则用自定义区间；period=custom 时仅用起止日期，忽略本周/本月等。"""
    if start_date and end_date:
        try:
            s = datetime.strptime(start_date, "%Y-%m-%d").date() if isinstance(start_date, str) else start_date
            e = datetime.strptime(end_date, "%Y-%m-%d").date() if isinstance(end_date, str) else end_date
            if s > e:
                start_date, end_date = end_date, start_date
            return "data_date BETWEEN %s AND %s", (start_date, end_date)
        except (ValueError, TypeError):
            pass
        return "data_date BETWEEN %s AND %s", (start_date, end_date)
    if period == "custom":
        days = int(os.environ.get("HTMA_DAYS", DEFAULT_DAYS))
        return "data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL %s DAY) AND CURDATE()", (days,)
    if period == "day":
        return "data_date = CURDATE()", ()
    if period == "week":
        # 本周 = 过去7天（含今天），避免「周一至今」在周初或时区差异下区间过小或为空
        return "data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND CURDATE()", ()
    if period == "month":
        return "data_date >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01') AND data_date <= CURDATE()", ()
    days = int(os.environ.get("HTMA_DAYS", DEFAULT_DAYS))
    return "data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL %s DAY) AND CURDATE()", (days,)


def _period_over_period_ranges(period, start_date_str=None, end_date_str=None):
    """根据 KPI 周期返回本期与上期的日期范围及标签，用于环比分析。
    返回 (curr_start, curr_end, prev_start, prev_end, curr_label, prev_label)，均为 date 或 None。"""
    today = date.today()
    if start_date_str and end_date_str:
        try:
            curr_end = datetime.strptime(end_date_str, "%Y-%m-%d").date() if isinstance(end_date_str, str) else end_date_str
            curr_start = datetime.strptime(start_date_str, "%Y-%m-%d").date() if isinstance(start_date_str, str) else start_date_str
        except Exception:
            curr_start = curr_end = today
        length = (curr_end - curr_start).days + 1
        prev_end = curr_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=length - 1)
        return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"
    if period == "day":
        return today, today, today - timedelta(days=1), today - timedelta(days=1), str(today), str(today - timedelta(days=1))
    if period == "week":
        # 本周 = 过去7天；上期 = 再前7天（与 _date_condition 一致）
        curr_end = today
        curr_start = today - timedelta(days=6)
        prev_end = curr_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=6)
        return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"
    if period == "month":
        curr_start = today.replace(day=1)
        curr_end = today
        prev_end = curr_start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"
    # recent30 或默认
    days = int(os.environ.get("HTMA_DAYS", DEFAULT_DAYS))
    curr_end = today
    curr_start = today - timedelta(days=days - 1)
    prev_end = curr_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"


def _query_filters(include_sku=False):
    """从 request 解析筛选条件。返回 (date_cond, params, category_cond, sku_cond)。
    支持 category_large/category_mid/category_small/category 级联筛选。
    KPI 周期：以用户选择为准，不写死。period/start_date/end_date 仅来自 request.args；
    当 start_date 与 end_date 同时传入时，一律按自定义区间筛选，忽略 period。"""
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
    """走势分析：环比（与 KPI 周期联动）、同比、趋势描述。支持 period、start_date、end_date、category"""
    granularity = request.args.get("granularity", "day")
    period = request.args.get("period", "recent30")
    date_cond, date_params, _, _, _ = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    params_ta = (STORE_ID,) + date_params + profit_cat_params
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 环比：与 KPI 周期联动，本期 vs 上期（等长）
            curr_start, curr_end, prev_start, prev_end, curr_label, prev_label = _period_over_period_ranges(
                period, start_date or None, end_date or None
            )
            cur.execute(
                """SELECT COALESCE(SUM(total_sale), 0) AS sale_amount, COALESCE(SUM(total_profit), 0) AS profit_amount
                   FROM t_htma_profit WHERE store_id = %s AND data_date BETWEEN %s AND %s """ + profit_cat_cond,
                (STORE_ID, curr_start, curr_end) + profit_cat_params,
            )
            curr_row = cur.fetchone()
            cur.execute(
                """SELECT COALESCE(SUM(total_sale), 0) AS sale_amount, COALESCE(SUM(total_profit), 0) AS profit_amount
                   FROM t_htma_profit WHERE store_id = %s AND data_date BETWEEN %s AND %s """ + profit_cat_cond,
                (STORE_ID, prev_start, prev_end) + profit_cat_params,
            )
            prev_row = cur.fetchone()
            _curr_sale = float(curr_row["sale_amount"] or 0)
            _curr_profit = float(curr_row["profit_amount"] or 0)
            _prev_sale = float(prev_row["sale_amount"] or 0)
            _prev_profit = float(prev_row["profit_amount"] or 0)
            _sale_chg = ((_curr_sale - _prev_sale) / _prev_sale * 100) if _prev_sale > 0 else 0
            _profit_chg = ((_curr_profit - _prev_profit) / _prev_profit * 100) if _prev_profit > 0 else 0
            pop = {
                "current_period": curr_label,
                "prev_period": prev_label,
                "current_sale": round(_curr_sale, 2),
                "prev_sale": round(_prev_sale, 2),
                "current_profit": round(_curr_profit, 2),
                "prev_profit": round(_prev_profit, 2),
                "sale_change_pct": round(_sale_chg, 2),
                "profit_change_pct": round(_profit_chg, 2),
            }

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
                return jsonify({"message": "数据不足", "period_over_period": pop, "year_over_year": None, "trend": "neutral", "trend_summary": None})

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

            # 走势数据摘要：供「走势与同比」卡片展示近期销售额/毛利；自定义区间时 latest_date 不超出请求的 end_date
            trend_summary = None
            if data_list:
                take = min(5, len(data_list))
                recent_list = data_list[-take:]
                recent_sale = sum(x["sale_amount"] for x in recent_list)
                recent_profit = sum(x["profit_amount"] for x in recent_list)
                last = data_list[-1]
                latest_date_val = last["key"]
                req_end = request.args.get("end_date", "").strip()
                if req_end and latest_date_val and latest_date_val > req_end:
                    latest_date_val = req_end  # 仅限制展示日期不超出所选区间，金额仍用结果集最后一条
                trend_summary = {
                    "recent_days": take,
                    "recent_sale": round(recent_sale, 2),
                    "recent_profit": round(recent_profit, 2),
                    "latest_date": latest_date_val,
                    "latest_sale": round(last["sale_amount"], 2),
                    "latest_profit": round(last["profit_amount"], 2),
                }

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
            "trend_summary": trend_summary,
            "yoy_reason": yoy_reason,
        })
    finally:
        conn.close()


DOW_NAMES = {1: "周日", 2: "周一", 3: "周二", 4: "周三", 5: "周四", 6: "周五", 7: "周六"}


@app.route("/api/dow_sales")
def api_dow_sales():
    """周几对比：在所选 KPI 周期内，按「星期几」汇总销售额与毛利，固定返回周日~周六 7 天（无数据填 0）"""
    date_cond, date_params, _, sale_cat_cond, sale_cat_params = _query_filters()
    profit_cat_cond, profit_cat_params = _profit_category_cond_and_params(date_cond, date_params)
    params_profit = (STORE_ID,) + date_params + profit_cat_params
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
            """, params_profit)
            rows = cur.fetchall()
        total_sale_from_profit = sum(float(r["sale_amount"] or 0) for r in rows)
        if total_sale_from_profit == 0 and (not sale_cat_cond or not sale_cat_cond.strip()):
            cur2 = conn.cursor()
            cur2.execute(f"""
                SELECT DAYOFWEEK(data_date) AS dow,
                       MAX(CASE DAYOFWEEK(data_date)
                         WHEN 1 THEN '周日' WHEN 2 THEN '周一' WHEN 3 THEN '周二' WHEN 4 THEN '周三'
                         WHEN 5 THEN '周四' WHEN 6 THEN '周五' WHEN 7 THEN '周六' ELSE '周日' END) AS dow_name,
                       SUM(sale_amount) AS sale_amount, SUM(gross_profit) AS profit_amount,
                       COUNT(DISTINCT data_date) AS day_count
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}
                GROUP BY DAYOFWEEK(data_date)
                ORDER BY dow
            """, (STORE_ID,) + date_params)
            rows = cur2.fetchall()
            cur2.close()
        by_dow = {int(r["dow"]): r for r in rows}
        out = []
        for dow in range(1, 8):
            r = by_dow.get(dow, {})
            out.append({
                "dow": dow,
                "dow_name": r.get("dow_name") or DOW_NAMES.get(dow, "周?"),
                "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                "profit_amount": round(float(r.get("profit_amount") or 0), 2),
                "day_count": int(r.get("day_count") or 0),
            })
        return jsonify(out)
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


# ---------- 经营性分析 API（见 docs/现有数据还能做哪些经营性分析.md） ----------

@app.route("/api/return_gift_summary")
def api_return_gift_summary():
    """退货与赠送汇总：退货/赠送金额与件数占比，支持 period/start_date/end_date"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(SUM(sale_amount), 0) AS total_sale, COALESCE(SUM(sale_qty), 0) AS total_qty,
                       COALESCE(SUM(return_amount), 0) AS return_amt, COALESCE(SUM(return_qty), 0) AS return_qty,
                       COALESCE(SUM(gift_amount), 0) AS gift_amt, COALESCE(SUM(gift_qty), 0) AS gift_qty
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond}
            """, params)
            row = cur.fetchone()
        total_sale = float(row["total_sale"] or 0)
        total_qty = float(row["total_qty"] or 0)
        return_amt = float(row["return_amt"] or 0)
        return_qty = float(row["return_qty"] or 0)
        gift_amt = float(row["gift_amt"] or 0)
        gift_qty = float(row["gift_qty"] or 0)
        return_ratio_amt = (return_amt / total_sale * 100) if total_sale > 0 else 0
        return_ratio_qty = (return_qty / total_qty * 100) if total_qty > 0 else 0
        gift_ratio_amt = (gift_amt / total_sale * 100) if total_sale > 0 else 0
        gift_ratio_qty = (gift_qty / total_qty * 100) if total_qty > 0 else 0
        return jsonify({
            "total_sale_amount": round(total_sale, 2),
            "total_sale_qty": round(total_qty, 2),
            "return_amount": round(return_amt, 2),
            "return_qty": round(return_qty, 2),
            "gift_amount": round(gift_amt, 2),
            "gift_qty": round(gift_qty, 2),
            "return_ratio_amt_pct": round(return_ratio_amt, 2),
            "return_ratio_qty_pct": round(return_ratio_qty, 2),
            "gift_ratio_amt_pct": round(gift_ratio_amt, 2),
            "gift_ratio_qty_pct": round(gift_ratio_qty, 2),
            "data_hint": "无数据时请检查：1) 是否已导入销售日报/销售汇总 Excel；2) 所选周期是否覆盖数据日期。可用 /api/data_status 查看库内数据范围。" if total_sale == 0 else None,
        })
    finally:
        conn.close()


@app.route("/api/brand_summary")
def api_brand_summary():
    """品牌贡献：按品牌汇总销售额、毛利、销量、毛利率、贡献占比。支持 period/start_date/end_date"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(NULLIF(TRIM(brand_name), ''), '未填') AS brand_name,
                       SUM(sale_amount) AS sale_amount, SUM(gross_profit) AS profit, SUM(sale_qty) AS qty
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond}
                GROUP BY brand_name
                HAVING SUM(sale_amount) > 0
                ORDER BY SUM(sale_amount) DESC
                LIMIT 50
            """, params)
            rows = cur.fetchall()
            cur.execute(f"""
                SELECT COALESCE(SUM(sale_amount), 0) AS total_sale, COALESCE(SUM(gross_profit), 0) AS total_profit
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond}
            """, params)
            tot = cur.fetchone()
        total_sale = float(tot["total_sale"] or 0)
        total_profit = float(tot["total_profit"] or 0)
        out = []
        for r in rows:
            sale = float(r["sale_amount"] or 0)
            profit = float(r["profit"] or 0)
            contrib = (sale / total_sale * 100) if total_sale > 0 else 0
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "brand_name": r["brand_name"] or "未填",
                "sale_amount": round(sale, 2),
                "profit": round(profit, 2),
                "qty": round(float(r["qty"] or 0), 2),
                "margin_pct": round(margin, 2),
                "contrib_pct": round(contrib, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


@app.route("/api/supplier_summary")
def api_supplier_summary():
    """供应商贡献：按供应商汇总销售额、毛利、销量、毛利率、贡献占比"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COALESCE(NULLIF(TRIM(supplier_name), ''), '未填') AS supplier_name,
                       SUM(sale_amount) AS sale_amount, SUM(gross_profit) AS profit, SUM(sale_qty) AS qty
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond}
                GROUP BY supplier_name
                HAVING SUM(sale_amount) > 0
                ORDER BY SUM(sale_amount) DESC
                LIMIT 50
            """, params)
            rows = cur.fetchall()
            cur.execute(f"""
                SELECT COALESCE(SUM(sale_amount), 0) AS total_sale, COALESCE(SUM(gross_profit), 0) AS total_profit
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond}
            """, params)
            tot = cur.fetchone()
        total_sale = float(tot["total_sale"] or 0)
        total_profit = float(tot["total_profit"] or 0)
        out = []
        for r in rows:
            sale = float(r["sale_amount"] or 0)
            profit = float(r["profit"] or 0)
            contrib = (sale / total_sale * 100) if total_sale > 0 else 0
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "supplier_name": r["supplier_name"] or "未填",
                "sale_amount": round(sale, 2),
                "profit": round(profit, 2),
                "qty": round(float(r["qty"] or 0), 2),
                "margin_pct": round(margin, 2),
                "contrib_pct": round(contrib, 2),
            })
        return jsonify(out)
    finally:
        conn.close()


@app.route("/api/price_band_summary")
def api_price_band_summary():
    """价格带分布：按件单价分段（0-10/10-30/30-50/50-100/100+）的销售额、销量、消费笔数及占比"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT
                    CASE
                        WHEN COALESCE(sale_qty, 0) <= 0 THEN '0'
                        WHEN (sale_amount / sale_qty) < 10 THEN '0-10'
                        WHEN (sale_amount / sale_qty) < 30 THEN '10-30'
                        WHEN (sale_amount / sale_qty) < 50 THEN '30-50'
                        WHEN (sale_amount / sale_qty) < 100 THEN '50-100'
                        ELSE '100+'
                    END AS band,
                    SUM(sale_amount) AS sale_amount,
                    SUM(sale_qty) AS qty,
                    COUNT(*) AS record_count
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond} AND sale_qty > 0 AND sale_amount > 0
                GROUP BY band
            """, params)
            rows = cur.fetchall()
            cur.execute(f"""
                SELECT COALESCE(SUM(sale_amount), 0) AS total_sale,
                       COALESCE(SUM(sale_qty), 0) AS total_qty,
                       COUNT(*) AS total_records
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond} AND sale_qty > 0 AND sale_amount > 0
            """, params)
            tot = cur.fetchone()
        total_sale = float(tot["total_sale"] or 0)
        total_qty = float(tot["total_qty"] or 0)
        total_records = int(tot["total_records"] or 0)
        band_order = ["0", "0-10", "10-30", "30-50", "50-100", "100+"]
        out = []
        for r in rows:
            band = r["band"] or "0"
            sale = float(r["sale_amount"] or 0)
            qty = float(r["qty"] or 0)
            record_count = int(r["record_count"] or 0)
            out.append({
                "band": band,
                "sale_amount": round(sale, 2),
                "qty": round(qty, 2),
                "record_count": record_count,
                "sale_contrib_pct": round((sale / total_sale * 100), 2) if total_sale > 0 else 0,
                "qty_contrib_pct": round((qty / total_qty * 100), 2) if total_qty > 0 else 0,
                "record_contrib_pct": round((record_count / total_records * 100), 2) if total_records > 0 else 0,
            })
        out.sort(key=lambda x: (band_order.index(x["band"]) if x["band"] in band_order else 99, x["band"]))
        return jsonify(out)
    finally:
        conn.close()


@app.route("/api/sku_turnover")
def api_sku_turnover():
    """SKU 周转：近 N 天销量、最新库存、周转天数（库存/日均销量）。limit 默认 100"""
    date_cond, _, params, category_cond, _ = _query_filters()
    limit = min(int(request.args.get("limit", 100)), 500)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT s.sku_code,
                       COALESCE(st.product_name, s.product_name, s.sku_code) AS product_name,
                       s.category,
                       SUM(s.sale_qty) AS sale_qty,
                       SUM(s.sale_amount) AS sale_amount,
                       COALESCE(st.stock_qty, 0) AS stock_qty
                FROM t_htma_sale s
                LEFT JOIN (
                    SELECT sku_code, stock_qty, product_name
                    FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
                ) st ON st.sku_code = s.sku_code
                WHERE s.store_id = %s AND {date_cond}{category_cond}
                GROUP BY s.sku_code, st.product_name, s.product_name, s.category, st.stock_qty
                HAVING SUM(s.sale_qty) > 0
                ORDER BY SUM(s.sale_qty) DESC
                LIMIT %s
            """, (STORE_ID, STORE_ID) + tuple(params) + (limit,))
            rows = cur.fetchall()
        days = 30
        if request.args.get("start_date") and request.args.get("end_date"):
            try:
                from datetime import datetime
                e = datetime.strptime(request.args.get("end_date"), "%Y-%m-%d").date()
                s = datetime.strptime(request.args.get("start_date"), "%Y-%m-%d").date()
                days = max(1, (e - s).days + 1)
            except Exception:
                pass
        elif request.args.get("period") == "week":
            days = 7
        elif request.args.get("period") == "month":
            days = 31
        out = []
        for r in rows:
            sale_qty = float(r["sale_qty"] or 0)
            stock_qty = float(r["stock_qty"] or 0)
            daily_sale = sale_qty / days if days > 0 else 0
            turnover_days = (stock_qty / daily_sale) if daily_sale > 0 else (9999 if stock_qty > 0 else 0)
            out.append({
                "sku_code": r["sku_code"],
                "product_name": (r["product_name"] or r["sku_code"])[:64],
                "category": (r["category"] or "")[:32],
                "sale_qty": round(sale_qty, 2),
                "sale_amount": round(float(r["sale_amount"] or 0), 2),
                "stock_qty": round(stock_qty, 2),
                "turnover_days": round(turnover_days, 1) if turnover_days < 9999 else None,
            })
        return jsonify(out)
    finally:
        conn.close()


@app.route("/api/sku_abc")
def api_sku_abc():
    """SKU ABC 分类：按销售额累计占比 A(前80%)/B(80-95%)/C(其余)。返回每类数量及明细（可 limit）"""
    date_cond, _, params, category_cond, _ = _query_filters()
    limit = min(int(request.args.get("limit", 200)), 500)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT s.sku_code,
                       COALESCE(st.product_name, s.product_name, s.sku_code) AS product_name,
                       s.category,
                       SUM(s.sale_amount) AS sale_amount,
                       SUM(s.gross_profit) AS profit
                FROM t_htma_sale s
                LEFT JOIN (
                    SELECT sku_code, product_name FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
                ) st ON st.sku_code = s.sku_code
                WHERE s.store_id = %s AND {date_cond}{category_cond}
                GROUP BY s.sku_code, st.product_name, s.product_name, s.category
                HAVING SUM(s.sale_amount) > 0
                ORDER BY SUM(s.sale_amount) DESC
            """, (STORE_ID, STORE_ID) + tuple(params))
            rows = cur.fetchall()
        total_sale = sum(float(r["sale_amount"] or 0) for r in rows)
        cum = 0
        out = []
        a_cnt, b_cnt, c_cnt = 0, 0, 0
        for i, r in enumerate(rows):
            sale = float(r["sale_amount"] or 0)
            cum += sale
            pct = (cum / total_sale * 100) if total_sale > 0 else 0
            if pct <= 80:
                cls = "A"
                a_cnt += 1
            elif pct <= 95:
                cls = "B"
                b_cnt += 1
            else:
                cls = "C"
                c_cnt += 1
            if len(out) < limit:
                out.append({
                    "sku_code": r["sku_code"],
                    "product_name": (r["product_name"] or r["sku_code"])[:64],
                    "category": (r["category"] or "")[:32],
                    "sale_amount": round(sale, 2),
                    "profit": round(float(r["profit"] or 0), 2),
                    "cum_contrib_pct": round(pct, 2),
                    "abc_class": cls,
                })
        return jsonify({
            "summary": {"A_count": a_cnt, "B_count": b_cnt, "C_count": c_cnt, "total_sale": round(total_sale, 2)},
            "items": out,
        })
    finally:
        conn.close()


@app.route("/api/negative_margin_detail")
def api_negative_margin_detail():
    """负毛利明细：销售额>0 且毛利<0 的 SKU 列表。format=csv 时返回 CSV 下载"""
    date_cond, _, params, category_cond, _ = _query_filters()
    limit = min(int(request.args.get("limit", 200)), 1000)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT s.sku_code,
                       COALESCE(st.product_name, s.product_name, s.sku_code) AS product_name,
                       s.category,
                       SUM(s.sale_qty) AS qty,
                       SUM(s.sale_amount) AS sale_amount,
                       SUM(s.sale_cost) AS cost,
                       SUM(s.gross_profit) AS profit
                FROM t_htma_sale s
                LEFT JOIN (
                    SELECT sku_code, product_name FROM t_htma_stock
                    WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
                ) st ON st.sku_code = s.sku_code
                WHERE s.store_id = %s AND {date_cond}{category_cond}
                GROUP BY s.sku_code, st.product_name, s.product_name, s.category
                HAVING SUM(s.sale_amount) > 0 AND SUM(s.gross_profit) < 0
                ORDER BY SUM(s.gross_profit) ASC
                LIMIT %s
            """, (STORE_ID, STORE_ID) + tuple(params) + (limit,))
            rows = cur.fetchall()
        out = []
        for r in rows:
            sale = float(r["sale_amount"] or 0)
            profit = float(r["profit"] or 0)
            margin = (profit / sale * 100) if sale > 0 else 0
            out.append({
                "sku_code": r["sku_code"],
                "product_name": (r["product_name"] or r["sku_code"])[:64],
                "category": (r["category"] or "")[:32],
                "qty": round(float(r["qty"] or 0), 2),
                "sale_amount": round(sale, 2),
                "cost": round(float(r["cost"] or 0), 2),
                "profit": round(profit, 2),
                "margin_pct": round(margin, 2),
            })
        if request.args.get("format") == "csv":
            import io
            import csv
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["商品编码", "品名", "品类", "销量", "销售额", "成本", "毛利", "毛利率%"])
            for row in out:
                writer.writerow([
                    row["sku_code"], row["product_name"], row["category"],
                    row["qty"], row["sale_amount"], row["cost"], row["profit"], row["margin_pct"],
                ])
            return Response(buf.getvalue(), mimetype="text/csv; charset=utf-8-sig",
                           headers={"Content-Disposition": "attachment; filename=negative_margin_detail.csv"})
        return jsonify(out)
    finally:
        conn.close()


@app.route("/api/category_structure_trend")
def api_category_structure_trend():
    """品类结构趋势：按周或月汇总各品类销售额占比。granularity=week|month，默认 week"""
    granularity = request.args.get("granularity", "week")
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if granularity == "month":
                cur.execute(f"""
                    SELECT DATE_FORMAT(data_date, '%%Y-%%m') AS period,
                           COALESCE(category, '未分类') AS category,
                           SUM(sale_amount) AS sale_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}
                    GROUP BY DATE_FORMAT(data_date, '%%Y-%%m'), COALESCE(category, '未分类')
                    ORDER BY period, sale_amount DESC
                """, params)
            else:
                cur.execute(f"""
                    SELECT CONCAT(YEAR(data_date), '-W', LPAD(WEEK(data_date, 3), 2, '0')) AS period,
                           COALESCE(category, '未分类') AS category,
                           SUM(sale_amount) AS sale_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}
                    GROUP BY CONCAT(YEAR(data_date), '-W', LPAD(WEEK(data_date, 3), 2, '0')), COALESCE(category, '未分类')
                    ORDER BY period, sale_amount DESC
                """, params)
            rows = cur.fetchall()
        from collections import defaultdict
        period_totals = defaultdict(float)
        period_cats = defaultdict(list)
        for r in rows:
            period = r["period"] or ""
            cat = r["category"] or "未分类"
            amt = float(r["sale_amount"] or 0)
            period_totals[period] += amt
            period_cats[period].append({"category": cat, "sale_amount": round(amt, 2)})
        out = []
        for period in sorted(period_totals.keys()):
            total = period_totals[period]
            cats = period_cats[period]
            for c in cats:
                pct = (c["sale_amount"] / total * 100) if total > 0 else 0
                c["share_pct"] = round(pct, 2)
            out.append({"period": period, "total_sale": round(total, 2), "by_category": cats})
        return jsonify(out)
    finally:
        conn.close()


@app.route("/api/inventory_turnover_summary")
def api_inventory_turnover_summary():
    """库存周转汇总：期末库存金额、周期内销售成本（或销售额）、周转天数"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(SUM(stock_amount), 0) AS total_stock
                FROM t_htma_stock
                WHERE store_id = %s AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
            """, (STORE_ID, STORE_ID))
            stock_row = cur.fetchone()
            cur.execute(f"""
                SELECT COALESCE(SUM(sale_amount), 0) AS sale_amount, COALESCE(SUM(sale_cost), 0) AS cost_amount
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond}
            """, params)
            sale_row = cur.fetchone()
        total_stock = float(stock_row["total_stock"] or 0)
        total_sale = float(sale_row["sale_amount"] or 0)
        total_cost = float(sale_row["cost_amount"] or 0)
        days = 30
        if request.args.get("start_date") and request.args.get("end_date"):
            try:
                e = datetime.strptime(request.args.get("end_date"), "%Y-%m-%d").date()
                s = datetime.strptime(request.args.get("start_date"), "%Y-%m-%d").date()
                days = max(1, (e - s).days + 1)
            except Exception:
                pass
        daily_cost = total_cost / days if days > 0 else 0
        turnover_days = (total_stock / daily_cost) if daily_cost > 0 else None
        return jsonify({
            "total_stock_amount": round(total_stock, 2),
            "period_sale_amount": round(total_sale, 2),
            "period_cost_amount": round(total_cost, 2),
            "turnover_days": round(turnover_days, 1) if turnover_days is not None else None,
            "days": days,
        })
    finally:
        conn.close()


@app.route("/api/data_quality")
def api_data_quality():
    """数据质量：成本/售价缺失条数、同 SKU 多品类异常数（与 data_status 互补）"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM t_htma_sale
                WHERE store_id = %s AND (sale_cost IS NULL OR sale_cost = 0) AND sale_amount > 0
            """, (STORE_ID,))
            missing_cost = cur.fetchone()["cnt"] or 0
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM t_htma_sale
                WHERE store_id = %s AND (sale_price IS NULL OR sale_price = 0) AND sale_qty > 0
            """, (STORE_ID,))
            missing_price = cur.fetchone()["cnt"] or 0
            cur.execute("""
                SELECT sku_code, COUNT(DISTINCT COALESCE(category, '')) AS cat_cnt
                FROM t_htma_sale WHERE store_id = %s
                GROUP BY sku_code HAVING cat_cnt > 1
            """, (STORE_ID,))
            inconsistent = cur.fetchall()
        inconsistent_sku_count = len(inconsistent)
        return jsonify({
            "missing_cost_rows": missing_cost,
            "missing_price_rows": missing_price,
            "inconsistent_category_sku_count": inconsistent_sku_count,
            "inconsistent_sku_sample": [r["sku_code"] for r in inconsistent[:20]],
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
    """品类排行明细：按大类下的中类/小类（扁平列表，兼容旧用）。需传 category_large_code 或 category_large"""
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
    if _auth_enabled() and not _has_module_access("profit"):
        return jsonify({"success": False, "message": "无权访问盈利分析模块，请联系管理员"}), 403
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
    """进销存营销分析报告。mode=internal 为明细版（Top10 列清品名/利润/利润率+专家建议），market_expansion 为市场拓展版。send=1 时推送飞书"""
    send_feishu_flag = request.args.get("send", "").strip() in ("1", "true", "yes")
    mode = request.args.get("mode", "internal").strip() or "internal"
    if _auth_enabled() and not _has_module_access("profit"):
        return jsonify({"success": False, "message": "无权访问盈利分析模块，请联系管理员"}), 403
    try:
        from analytics import build_marketing_report
        conn = get_conn()
        try:
            report = build_marketing_report(conn, STORE_ID, mode=mode)
            send_ok = False
            send_err = None
            wecom_ok = dingtalk_ok = False
            if send_feishu_flag:
                try:
                    from notify_util import notify_all
                    results, _ = notify_all(report, title="好特卖进销存营销分析",
                        feishu_at_user_id="ou_8db735f2", feishu_at_user_name="余为军")
                    send_ok = results.get("feishu", (False,))[0]
                    wecom_ok = results.get("wecom", (False,))[0]
                    dingtalk_ok = results.get("dingtalk", (False,))[0]
                    send_err = None if send_ok else (results.get("feishu", (False, ""))[1])
                except Exception as e:
                    from feishu_util import send_feishu
                    send_ok, send_err = send_feishu(report, at_user_id="ou_8db735f2", at_user_name="余为军")
            _save_report_log(conn, report, send_ok, send_err)
            return jsonify({
                "success": True, "report": report,
                "feishu_sent": send_feishu_flag, "feishu_ok": send_ok,
                "wecom_ok": wecom_ok, "dingtalk_ok": dingtalk_ok,
            })
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
    if _auth_enabled() and not _has_module_access("profit"):
        return jsonify({"success": False, "message": "无权访问盈利分析模块，请联系管理员"}), 403
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


@app.route("/api/platform_products_sync", methods=["POST", "OPTIONS"])
def api_platform_products_sync():
    """同步平台商品到 t_htma_platform_products 表（按大类/中类/小类、规格、条码）"""
    if request.method == "OPTIONS":
        return "", 204
    try:
        from price_compare import sync_platform_products
        days = int((request.get_json(silent=True) or {}).get("days", 30))
        limit = int((request.get_json(silent=True) or {}).get("limit", 500))
        conn = get_conn()
        try:
            cnt = sync_platform_products(conn, store_id=STORE_ID, days=days, limit=limit)
            return jsonify({"success": True, "synced": cnt})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "synced": 0, "error": str(e)}), 500


@app.route("/api/sync_products_category", methods=["POST", "GET", "OPTIONS"])
def api_sync_products_category():
    """同步商品表、品类表（供导出与比价）。数据导入后自动调用，也可手动触发"""
    if request.method == "OPTIONS":
        return "", 204
    try:
        conn = get_conn()
        try:
            products_cnt = sync_products_table(conn, store_id=STORE_ID)
            category_cnt = sync_category_table(conn, store_id=STORE_ID)
            return jsonify({"success": True, "products_synced": products_cnt, "category_synced": category_cnt})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/price_compare_products", methods=["GET", "OPTIONS"])
def api_price_compare_products():
    """比价商品列表：从 t_htma_platform_products 读取，按大类、中类、小类分组。若表为空则先同步。"""
    if request.method == "OPTIONS":
        return "", 204
    try:
        from price_compare import load_platform_products_from_db, sync_platform_products, stage1_standardize
        days = int(request.args.get("days", 30))
        limit = int(request.args.get("limit", 300))
        sync_first = request.args.get("sync", "1") == "1"
        conn = get_conn()
        try:
            try:
                items = load_platform_products_from_db(conn, store_id=STORE_ID, limit=limit)
            except Exception:
                items = []
            if not items and sync_first:
                sync_platform_products(conn, store_id=STORE_ID, days=days, limit=limit)
                items = load_platform_products_from_db(conn, store_id=STORE_ID, limit=limit)
            if not items:
                items_raw = stage1_standardize(conn, store_id=STORE_ID, days=days, limit=limit)
                items = [{"sku_code": it.get("sku_code"), "raw_name": it.get("raw_name"), "spec": it.get("spec") or "", "barcode": it.get("barcode") or "", "brand_name": it.get("brand_name") or "", "category_large": it.get("category_large") or "未分类", "category_mid": it.get("category_mid") or "未分类", "category_small": it.get("category_small") or "未分类", "unit_price": round(float(it.get("unit_price") or 0), 2), "sale_qty": float(it.get("sale_qty") or 0), "sale_amount": round(float(it.get("sale_amount") or 0), 2)} for it in items_raw]
            groups = {}
            for it in items:
                large = (it.get("category_large") or "未分类").strip() or "未分类"
                mid = (it.get("category_mid") or "未分类").strip() or "未分类"
                small = (it.get("category_small") or "未分类").strip() or "未分类"
                if large not in groups:
                    groups[large] = {}
                if mid not in groups[large]:
                    groups[large][mid] = {}
                if small not in groups[large][mid]:
                    groups[large][mid][small] = []
                groups[large][mid][small].append({
                    "sku_code": it.get("sku_code", ""),
                    "raw_name": it.get("raw_name", ""),
                    "spec": it.get("spec", ""),
                    "barcode": it.get("barcode", ""),
                    "brand_name": it.get("brand_name", ""),
                    "unit_price": round(float(it.get("unit_price") or 0), 2),
                    "sale_qty": float(it.get("sale_qty") or 0),
                    "sale_amount": round(float(it.get("sale_amount") or 0), 2),
                })
            return jsonify({"success": True, "groups": groups, "total": len(items)})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "groups": {}, "total": 0, "error": str(e)}), 500


@app.route("/api/price_compare", methods=["GET", "POST", "OPTIONS"])
def api_price_compare():
    """货盘价格对比分析 - 4 阶段闭环，返回完整报告。POST 时使用真实 API"""
    if request.method == "OPTIONS":
        return "", 204
    try:
        from price_compare import run_full_pipeline, format_report
        if request.method == "GET":
            days = int(request.args.get("days", 30))
            fetch_limit = request.args.get("fetch_limit", type=int)
        else:
            data = (request.get_json(silent=True) or {}) if request.is_json else {}
            days = int(data.get("days", 30))
            fetch_limit = data.get("fetch_limit")
        if fetch_limit is None:
            try:
                v = os.environ.get("PRICE_COMPARE_FETCH_LIMIT", "")
                fetch_limit = int(v) if v else None
            except (TypeError, ValueError):
                fetch_limit = None
        use_mock = request.method == "GET"  # POST 时用真实 API
        conn = get_conn()
        try:
            result = run_full_pipeline(conn, store_id=STORE_ID, days=days, use_mock_fetcher=use_mock, fetch_limit=fetch_limit)
            report = format_report(result)
            items = result.get("items", [])
            # 构建表格数据，确保 items 字段始终存在（即使为空数组）
            table_rows = []
            if items and isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        table_rows.append({
                            "raw_name": str(it.get("raw_name") or it.get("std_name") or ""),
                            "spec": str(it.get("spec") or "-"),
                            "unit_price": it.get("unit_price"),
                            "jd_min_price": it.get("jd_min_price"),
                            "taobao_min_price": it.get("taobao_min_price"),
                            "competitor_min": it.get("competitor_min"),
                            "platform": str(it.get("platform") or "-"),
                            "advantage_pct": it.get("advantage_pct"),
                            "tier": str(it.get("tier") or "独家款"),
                        })
            # 确保 items 字段始终存在；返回竞品接口状态便于前端提示
            summary = result.get("portfolio", {}).get("summary", {}) if isinstance(result.get("portfolio"), dict) else {}
            exclusive = summary.get("exclusive", 0)
            total = summary.get("total", 0)
            response_data = {
                "success": True,
                "report": str(report) if report else "",
                "summary": summary,
                "items": table_rows,
                "use_real_fetcher": result.get("use_real_fetcher", False),
                "fetcher_error": result.get("fetcher_error"),
                "fetcher_platform": result.get("fetcher_platform", ""),
                "all_exclusive_hint": bool(total > 0 and exclusive == total and result.get("use_real_fetcher")),
            }
            return jsonify(response_data)
        finally:
            conn.close()
    except Exception as e:
        error_msg = str(e)
        return jsonify({"success": False, "report": "", "items": [], "error": error_msg}), 500


@app.route("/api/price_compare_daily", methods=["POST", "OPTIONS"])
def api_price_compare_daily():
    """
    每日自动比价：按当日（或昨日）销售 TOP 商品比价，可选推送飞书。
    供用户主动触发或 OpenClaw/cron 调用。body: limit, fetch_limit, send_feishu, feishu_at_user_id
    """
    if request.method == "OPTIONS":
        return "", 204
    try:
        from price_compare import run_daily_top_compare, format_report
        from feishu_util import send_feishu
        data = (request.get_json(silent=True) or {}) if request.is_json else {}
        limit = int(data.get("limit", 50))
        fetch_limit = data.get("fetch_limit")
        if fetch_limit is not None:
            fetch_limit = int(fetch_limit)
        send_feishu_flag = data.get("send_feishu", False)
        at_user_id = data.get("feishu_at_user_id") or os.environ.get("FEISHU_AT_USER_ID", "ou_8db735f2")
        at_user_name = data.get("feishu_at_user_name") or os.environ.get("FEISHU_AT_USER_NAME", "余为军")
        conn = get_conn()
        try:
            result = run_daily_top_compare(
                conn, store_id=STORE_ID, data_date=None, limit=limit,
                use_mock_fetcher=False, save_to_db=True, fetch_limit=fetch_limit or limit,
            )
            report = format_report(result)
            items = result.get("items", [])
            feishu_sent = False
            feishu_ok = wecom_ok = dingtalk_ok = False
            if send_feishu_flag and items:
                try:
                    from notify_util import notify_all
                    results, _ = notify_all(report, title="好特卖商品比价报告",
                        feishu_at_user_id=at_user_id, feishu_at_user_name=at_user_name)
                    feishu_ok = results.get("feishu", (False,))[0]
                    wecom_ok = results.get("wecom", (False,))[0]
                    dingtalk_ok = results.get("dingtalk", (False,))[0]
                except Exception:
                    from feishu_util import send_feishu
                    feishu_ok, _ = send_feishu(
                        report, at_user_id=at_user_id, at_user_name=at_user_name, title="好特卖商品比价报告"
                    )
                feishu_sent = True
            table_rows = []
            for it in items:
                if isinstance(it, dict):
                    table_rows.append({
                        "raw_name": str(it.get("raw_name") or it.get("std_name") or ""),
                        "spec": str(it.get("spec") or "-"),
                        "unit_price": it.get("unit_price"),
                        "jd_min_price": it.get("jd_min_price"),
                        "taobao_min_price": it.get("taobao_min_price"),
                        "competitor_min": it.get("competitor_min"),
                        "platform": str(it.get("platform") or "-"),
                        "advantage_pct": it.get("advantage_pct"),
                        "tier": str(it.get("tier") or "独家款"),
                    })
            return jsonify({
                "success": True,
                "report": report,
                "data_date": result.get("data_date"),
                "items": table_rows,
                "summary": result.get("portfolio", {}).get("summary", {}),
                "feishu_sent": feishu_sent,
                "feishu_ok": feishu_ok,
                "wecom_ok": wecom_ok,
                "dingtalk_ok": dingtalk_ok,
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "report": "", "items": [], "error": str(e)}), 500


@app.route("/api/price_compare_results", methods=["GET", "OPTIONS"])
def api_price_compare_results():
    """查询已保存的比价结果（实体化数据），支持按 run_at、tier 筛选"""
    if request.method == "OPTIONS":
        return "", 204
    run_at = request.args.get("run_at", "").strip()  # 如 2026-02-18
    tier = request.args.get("tier", "").strip()  # 高优势款/独家款/价格劣势款 等
    limit = min(int(request.args.get("limit", 200)), 500)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            conds, params = [], [STORE_ID]
            if run_at:
                conds.append("DATE(run_at) = %s")
                params.append(run_at)
            if tier:
                conds.append("tier = %s")
                params.append(tier)
            where = " AND " + " AND ".join(conds) if conds else ""
            params.append(limit)
            try:
                cur.execute(f"""
                    SELECT run_at, sku_code, std_name, raw_name, spec, barcode, category,
                           unit_price, jd_min_price, jd_platform, taobao_min_price, taobao_platform,
                           competitor_min, advantage_pct, tier, platform
                    FROM t_htma_price_compare
                    WHERE store_id = %s {where}
                    ORDER BY run_at DESC, advantage_pct DESC
                    LIMIT %s
                """, params)
            except Exception:
                cur.execute(f"""
                    SELECT run_at, sku_code, std_name, category, unit_price,
                           competitor_min, advantage_pct, tier, platform
                    FROM t_htma_price_compare
                    WHERE store_id = %s {where}
                    ORDER BY run_at DESC, advantage_pct DESC
                    LIMIT %s
                """, params)
            rows = cur.fetchall()
        items = []
        for r in rows:
            run_at_val = r.get("run_at")
            run_at_str = run_at_val.isoformat() if run_at_val and hasattr(run_at_val, "isoformat") else str(run_at_val or "")
            items.append({
                "run_at": run_at_str,
                "sku_code": r.get("sku_code"),
                "std_name": r.get("std_name"),
                "raw_name": r.get("raw_name"),
                "spec": r.get("spec"),
                "barcode": r.get("barcode"),
                "category": r.get("category"),
                "unit_price": float(r["unit_price"]) if r.get("unit_price") is not None else None,
                "jd_min_price": float(r["jd_min_price"]) if r.get("jd_min_price") is not None else None,
                "jd_platform": r.get("jd_platform"),
                "taobao_min_price": float(r["taobao_min_price"]) if r.get("taobao_min_price") is not None else None,
                "taobao_platform": r.get("taobao_platform"),
                "competitor_min": float(r["competitor_min"]) if r.get("competitor_min") is not None else None,
                "advantage_pct": float(r["advantage_pct"]) if r.get("advantage_pct") is not None else None,
                "tier": r.get("tier"),
                "platform": r.get("platform"),
            })
        return jsonify({"success": True, "items": items, "total": len(items)})
    except Exception as e:
        return jsonify({"success": False, "items": [], "error": str(e)}), 500
    finally:
        conn.close()


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
