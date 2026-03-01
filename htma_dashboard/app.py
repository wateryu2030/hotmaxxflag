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
import pymysql
from flask import Flask, Response, jsonify, send_from_directory, request, session, redirect
from werkzeug.utils import secure_filename

from import_logic import import_sale_daily, import_sale_summary, import_stock, import_category, import_profit, import_tax_burden, refresh_profit, refresh_category_from_sale, sync_products_table, sync_category_table, preview_sale_excel
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
    if path.startswith("/static/") or (path != "/" and not path.startswith("/api/") and "." in path.split("/")[-1]):
        return None
    if _is_logged_in():
        return None
    # 未登录：页面请求重定向到登录页，API 返回 401
    if path in ("/import") or path.startswith("/api/"):
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
    """根路径：未登录展示登录页，已登录展示运营看板（登录前置，必须登录后才能看详细数据）"""
    if not _is_logged_in():
        return send_from_directory("static", "login.html")
    return send_from_directory("static", "index.html")


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
    return jsonify({
        "success": True,
        "user_id": session.get("open_id") or session.get("user_id"),
        "name": session.get("user_name", ""),
        "avatar_url": session.get("avatar_url"),
    })


def _feishu_callback_base_url():
    """飞书回调 redirect_uri 的站点根 URL。代理/Cloudflare 后请设置 HTMA_PUBLIC_URL 与飞书控制台一致（如 https://htma.greatagain.com.cn）"""
    base = (os.environ.get("HTMA_PUBLIC_URL") or os.environ.get("PUBLIC_URL") or "").strip()
    if base:
        return base.rstrip("/")
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
    """飞书授权回调：code 换用户信息并写 session，再重定向到首页或 next"""
    from auth import feishu_exchange_code_and_user
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
    session["open_id"] = user["open_id"]
    session["user_id"] = user["open_id"]
    session["user_name"] = user.get("name", "")
    session["avatar_url"] = user.get("avatar_url") or ""
    session.permanent = True
    next_url = (request.args.get("next", "").strip() or request.args.get("state", "").strip() or "/")
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"
    if next_url.startswith("http"):
        allow_base = base
        if not next_url.startswith(allow_base):
            next_url = "/"
    return redirect(next_url or "/")


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

        # 销售类：仅当本请求中同时包含「销售日报」和「销售汇总」时才清空，避免分步上传时后一次请求把前一次数据清掉
        has_sale_daily = _has_valid_file(["sale_daily"])
        has_sale_summary = _has_valid_file(["sale_summary"])
        if has_sale_daily and has_sale_summary:
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


def _import_downloads_directory():
    """服务端「从下载目录导入」使用的目录：环境变量 IMPORT_DOWNLOADS_DIR 或 项目/downloads"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.environ.get("IMPORT_DOWNLOADS_DIR") or os.path.join(root, "downloads")


def _find_excel_files_in_dir(directory):
    """在指定目录查找销售日报、销售汇总、实时库存/库存查询（取最新），返回 {sale_daily?, sale_summary?, stock?} 路径"""
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
            "message": "未在下载目录找到销售日报/销售汇总/实时库存 Excel",
            "directory": directory,
            "hint": "请将 Excel 放入该目录后重试，或使用「数据导入」页面上传",
        }), 400

    conn = None
    result = {"sale_daily": 0, "sale_summary": 0, "stock": 0, "profit_refreshed": 0, "errors": [], "from_downloads": True, "directory": directory}
    try:
        conn = get_conn()
        cur = conn.cursor()
        has_sale_daily = "sale_daily" in files
        has_sale_summary = "sale_summary" in files
        if has_sale_daily and has_sale_summary:
            cur.execute("TRUNCATE TABLE t_htma_sale")
            cur.execute("TRUNCATE TABLE t_htma_profit")
            conn.commit()
        if "stock" in files:
            cur.execute("TRUNCATE TABLE t_htma_stock")
            conn.commit()

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
        conn2.close()

        result["success"] = True
        result["data_import_target"] = "server"
        if result.get("sale_total", 0) > 0 or result.get("stock_total", 0) > 0:
            msg = f"好特卖数据导入完成（下载目录）\n销售表: {result.get('sale_total', 0)} 条\n库存表: {result.get('stock_total', 0)} 条\n毛利表: {result.get('profit_total', 0)} 条\n日期范围: {result.get('date_range', '-')}"
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
        # 周一为第一天：weekday() 0=Mon, 6=Sun
        weekday = today.weekday()
        curr_start = today - timedelta(days=weekday)
        curr_end = curr_start + timedelta(days=6)
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

            # 走势数据摘要：供「走势与同比」卡片展示近期销售额/毛利，避免只显示“下降”无数值
            trend_summary = None
            if data_list:
                take = min(5, len(data_list))
                recent_list = data_list[-take:]
                recent_sale = sum(x["sale_amount"] for x in recent_list)
                recent_profit = sum(x["profit_amount"] for x in recent_list)
                last = data_list[-1]
                trend_summary = {
                    "recent_days": take,
                    "recent_sale": round(recent_sale, 2),
                    "recent_profit": round(recent_profit, 2),
                    "latest_date": last["key"],
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
    """价格带分布：按件单价分段（0-10/10-30/30-50/50-100/100+）的销售额与销量占比"""
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
                    SUM(sale_qty) AS qty
                FROM t_htma_sale
                WHERE store_id = %s AND {date_cond}{category_cond} AND sale_qty > 0 AND sale_amount > 0
                GROUP BY band
            """, params)
            rows = cur.fetchall()
            cur.execute(f"""
                SELECT COALESCE(SUM(sale_amount), 0) AS total_sale, COALESCE(SUM(sale_qty), 0) AS total_qty
                FROM t_htma_sale WHERE store_id = %s AND {date_cond}{category_cond} AND sale_qty > 0 AND sale_amount > 0
            """, params)
            tot = cur.fetchone()
        total_sale = float(tot["total_sale"] or 0)
        total_qty = float(tot["total_qty"] or 0)
        band_order = ["0", "0-10", "10-30", "30-50", "50-100", "100+"]
        out = []
        for r in rows:
            band = r["band"] or "0"
            sale = float(r["sale_amount"] or 0)
            qty = float(r["qty"] or 0)
            out.append({
                "band": band,
                "sale_amount": round(sale, 2),
                "qty": round(qty, 2),
                "sale_contrib_pct": round((sale / total_sale * 100), 2) if total_sale > 0 else 0,
                "qty_contrib_pct": round((qty / total_qty * 100), 2) if total_qty > 0 else 0,
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
    """进销存营销分析报告。mode=internal 为明细版（Top10 列清品名/利润/利润率+专家建议），market_expansion 为市场拓展版。send=1 时推送飞书"""
    send_feishu_flag = request.args.get("send", "").strip() in ("1", "true", "yes")
    mode = request.args.get("mode", "internal").strip() or "internal"
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
