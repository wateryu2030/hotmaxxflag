#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
好特卖沈阳超级仓运营看板 - 独立版（不依赖 JimuReport）
直接读取 MySQL htma_dashboard，提供 API 与看板页面。
"""
import os
import sys
import urllib.parse
from datetime import date, timedelta, datetime

# 加载 .env（货盘比价、飞书登录等）；多路径、先 dotenv 再逐键解析，确保飞书登录能读到
_env_dir = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
_project_root = os.path.abspath(os.path.join(_env_dir, ".."))
_env_path = os.path.join(_project_root, ".env")
_ENV_KEYS = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "HTMA_PUBLIC_URL",
    "FLASK_SECRET_KEY",
    "FEISHU_WEBHOOK_URL",
    "FEISHU_AT_USER_ID",
    "FEISHU_AT_USER_NAME",
    "FEISHU_VERIFICATION_TOKEN",
    "FEISHU_ENCRYPT_KEY",
    "FEISHU_BOT_REPLY_MODE",
    "FEISHU_BOT_REPLY_PREFIX",
    "FEISHU_BOT_OPEN_ID",
    "FEISHU_BOT_DB_ALLOWED_OPEN_IDS",
    "FEISHU_BOT_MYSQL_USER",
    "FEISHU_BOT_MYSQL_PASSWORD",
    "FEISHU_BOT_DB_REQUIRE_ALLOWLIST",
)


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
_load_env_from_file(
    _env_path,
    force_keys=(
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_WEBHOOK_URL",
        "FEISHU_VERIFICATION_TOKEN",
        "FEISHU_ENCRYPT_KEY",
        "FEISHU_BOT_REPLY_MODE",
        "FEISHU_BOT_REPLY_PREFIX",
        "FEISHU_BOT_OPEN_ID",
        "FEISHU_BOT_DB_ALLOWED_OPEN_IDS",
        "FEISHU_BOT_MYSQL_USER",
        "FEISHU_BOT_MYSQL_PASSWORD",
        "FEISHU_BOT_DB_REQUIRE_ALLOWLIST",
    ),
)
for _p in (_env_path, os.path.join(os.getcwd(), ".env"), os.path.abspath(os.path.join(os.getcwd(), "..", ".env"))):
    _load_env_from_file(_p)
import csv
import io
import subprocess
import tempfile
import threading
import time
import pymysql
from db_config import DB_CONFIG, get_conn
from flask import Flask, Response, jsonify, send_from_directory, request, session, redirect
from werkzeug.utils import secure_filename

from import_logic import import_sale_daily, import_sale_summary, import_stock, import_category, import_profit, import_tax_burden, refresh_profit, refresh_category_from_sale, sync_products_table, sync_category_table, preview_sale_excel, import_labor_cost, import_labor_cost_from_image, refresh_labor_cost_analysis, import_product_master, _ensure_product_master_distribution_mode, _read_excel_safe
from analytics import build_insights, build_enhanced_insights, build_structured_report, build_marketing_report, category_rank_data, advanced_search_consumer_insight
from channel_hongbeilou import (
    query_catalog_rows,
    EXPORT_SIMPLE_COLUMNS,
    table_exists,
    build_selection_logic_meta,
    rows_to_simple_export,
)
from query_layer import date_condition as _ql_date_condition, query_filters_from_request as _ql_query_filters, query_filters_from_params as _ql_query_filters_from_params

# 简单内存缓存：key -> (value, expire_at)，用于 date_range / kpi 等只读接口
_api_cache = {}
_CACHE_TTL = 60  # 秒

def _cache_get(key):
    if key not in _api_cache:
        return None
    val, expire = _api_cache[key]
    if time.time() > expire:
        del _api_cache[key]
        return None
    return val

def _cache_set(key, value, ttl=None):
    _api_cache[key] = (value, time.time() + (ttl or _CACHE_TTL))

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
    - module: 'import' | 'labor' | 'profit' | 'product_master' | 'profit_share'"""
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
        "profit_share": "HTMA_PROFIT_SHARE_ALLOWED_FEISHU_OPEN_IDS",
        "tax_analysis": "HTMA_TAX_ANALYSIS_ALLOWED_FEISHU_OPEN_IDS",
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
    # 测试模式直接放行
    if (os.environ.get("HTMA_UNITTEST_DISABLE_AUTH") or "").strip().lower() in ("1", "true"):
        return None
    # CORS 预检：对 /api/* 的 OPTIONS 直接 204，避免 catch-all 路由导致 GET 等返回 405
    if request.method == "OPTIONS" and request.path.startswith("/api/"):
        return Response("", status=204)
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
    if path == "/api/feishu/bot/event" or path == "/feishu/callback":
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
    if path in ("/import", "/product_master", "/profit_share", "/tax_analysis", "/hongbeilou") or path.startswith("/api/"):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "请先登录", "login_required": True}), 401
        return redirect("/login?next=" + (urllib.parse.quote(request.url) if request.url else "/"))
    return None


# --- Blueprint registrations ---

# --- Initialize extensions ---
from extensions import cache, init_flask_caching
init_flask_caching(app)

from serve_web.overview import overview_bp
app.register_blueprint(overview_bp)

# Mobile routes (has its own before_request with JWT/auth check)
from routes_mobile import register_mobile_routes
register_mobile_routes(app)

# Biz enhanced routes
from routes_biz_enhanced import register_biz_routes
register_biz_routes(app)

# WeChat mini routes
from wechat_api import register_wechat_mini_routes
register_wechat_mini_routes(app)

# Labor routes
from labor_routes import register_labor_blueprints
register_labor_blueprints(app)
from serve_web.category_rank import cat_rank_bp
app.register_blueprint(cat_rank_bp)
from serve_web.profit import profit_bp
app.register_blueprint(profit_bp)
from serve_web.report import report_bp
app.register_blueprint(report_bp)
from serve_web.channel import channel_bp
app.register_blueprint(channel_bp)
from serve_web.sync import sync_bp
app.register_blueprint(sync_bp)
from serve_web.catalog import catalog_bp
app.register_blueprint(catalog_bp)
from serve_web.feishu_auth import feishu_web_bp
app.register_blueprint(feishu_web_bp)
from serve_web.import_api import import_api_bp
app.register_blueprint(import_api_bp)
from serve_web.content import content_bp
app.register_blueprint(content_bp)
from serve_web.tax import tax_bp
app.register_blueprint(tax_bp)
from serve_web.profit_share import profit_share_bp
app.register_blueprint(profit_share_bp)
from serve_web.product_master import product_bp
app.register_blueprint(product_bp)
from serve_web.price_compare import price_bp
app.register_blueprint(price_bp)

@app.after_request
def add_cors_headers(response):
    """允许跨域，便于 Cursor 预览、OpenClaw 等不同源访问"""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response












    return jsonify({"success": False, "error": "format 仅支持 csv 或 pdf"}), 400


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









@app.route("/pending")
def pending_page():
    """企业外用户提交申请后的等待页"""
    return send_from_directory("static", "pending.html")


@app.route("/approval")
def approval_page():
    """访问审批页（仅超级管理员余为军可见）"""
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + urllib.parse.quote(request.url or "/approval"))
    if not _is_super_admin():
        return redirect("/login?error=" + urllib.parse.quote("仅超级管理员可访问审批页"))
    return send_from_directory("static", "approval.html")


@app.route("/admin")
def admin_reminder_page():
    """超级管理员专用提醒页：待审批数量与快捷入口"""
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + urllib.parse.quote(request.url or "/admin"))
    if not _is_super_admin():
        return redirect("/login?error=" + urllib.parse.quote("仅超级管理员可访问"))
    return send_from_directory("static", "admin.html")










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


@app.route("/profit_share")
def profit_share_page():
    """收益评估（加盟商分账）页面，仅财务权限可访问"""
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + (urllib.parse.quote(request.url) if request.url else "/"))
    if _auth_enabled() and not _has_module_access("profit_share"):
        return Response("您无权访问收益评估模块，请联系管理员。", status=403)
    return send_from_directory("static", "profit_share.html")


@app.route("/tax_analysis")
def tax_analysis_page():
    """税务分析（发票比对、税负测算）页面，仅指定人员可访问"""
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + (urllib.parse.quote(request.url) if request.url else "/"))
    if _auth_enabled() and not _has_module_access("tax_analysis"):
        return Response("您无权访问税务分析模块，请联系管理员。", status=403)
    return send_from_directory("static", "tax_analysis.html")


@app.route("/hongbeilou")
def hongbeilou_page():
    """供销社「红背篓」选品：按品类筛选并导出 CSV（需 import 权限）"""
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + (urllib.parse.quote(request.url) if request.url else "/"))
    if _auth_enabled() and not _has_module_access("import"):
        return Response("您无权访问该模块，请联系管理员。", status=403)
    return send_from_directory("static", "hongbeilou.html")


# ---------- 税务分析（发票比对、税负测算）API ----------
def _tax_analysis_forbidden():
    return jsonify({"error": "无权限"}), 403


def _parse_invoice_excel(excel_path, store_id="沈阳超级仓"):
    """解析发票 Excel（兼容 12 月/1 月两种表头），返回 [(category_small_code, category_small_name, tax_class_code, tax_rate, sale_qty, invoice_amount), ...]。
    调用方传入 period_month。"""
    import pandas as pd
    xl = pd.ExcelFile(excel_path)
    sheets = [s for s in xl.sheet_names if s]
    if not sheets:
        raise ValueError("Excel 中无有效 Sheet")
    ext = os.path.splitext(excel_path)[1].lower()
    engine = "openpyxl" if ext == ".xlsx" else "xlrd"
    out = []
    for sheet in sheets:
        try:
            df = pd.read_excel(excel_path, sheet_name=sheet, header=None, engine=engine)
        except Exception:
            df = pd.read_excel(excel_path, sheet_name=sheet, header=None)
        if df.shape[0] < 2 or df.shape[1] < 4:
            continue
        # 找表头行：包含「三级类别名称」或「三级类别编码」
        header_row = None
        for i in range(min(6, len(df))):
            row = df.iloc[i]
            vals = [str(x).strip() if pd.notna(x) else "" for x in row]
            if "三级类别名称" in vals or "求和项:开票金额" in vals:
                header_row = i
                break
        if header_row is None:
            continue
        headers = [str(x).strip() if pd.notna(x) else "" for x in df.iloc[header_row]]
        col_name = None
        col_code = None
        col_tax_code = None
        col_rate = None
        col_qty = None
        col_amount = None
        for j, h in enumerate(headers):
            if h == "三级类别名称":
                col_name = j
            elif h == "三级类别编码":
                col_code = j
            elif "税收分类编码" in h or h == "税收分类编码":
                col_tax_code = j
            elif h == "税率":
                col_rate = j
            elif "求和项:销售数量" in h or h == "销售数量":
                col_qty = j
            elif "求和项:开票金额" in h or h == "开票金额":
                col_amount = j
        if col_name is None or col_amount is None:
            continue
        if col_rate is None:
            col_rate = col_tax_code  # 可能同一列
        skip_names = ("", "总计", "合计", "小计", "汇总", "价税合计", "共", "第", "第1页", "第2页")
        for i in range(header_row + 1, len(df)):
            row = df.iloc[i]
            name = (row.iloc[col_name] if col_name is not None else None)
            if pd.isna(name):
                continue
            name = str(name).strip()
            if not name:
                continue
            if name in skip_names or any(name.startswith(s) for s in ("共", "第")) or "价税合计" in name:
                continue
            code = None
            if col_code is not None and col_code < len(row):
                v = row.iloc[col_code]
                if pd.notna(v):
                    try:
                        code = str(int(float(v))) if isinstance(v, (int, float)) else str(v).strip()
                    except Exception:
                        code = str(v).strip()
            tax_code = None
            if col_tax_code is not None and col_tax_code < len(row):
                v = row.iloc[col_tax_code]
                if pd.notna(v):
                    try:
                        tax_code = str(int(float(v)))
                    except Exception:
                        tax_code = str(v).strip() if v else None
            try:
                rate = float(row.iloc[col_rate]) if col_rate is not None and pd.notna(row.iloc[col_rate]) else 0.13
            except Exception:
                rate = 0.13
            try:
                qty = float(row.iloc[col_qty]) if col_qty is not None and pd.notna(row.iloc[col_qty]) else 0
            except Exception:
                qty = 0
            try:
                amt = float(row.iloc[col_amount])
            except Exception:
                amt = 0
            if amt == 0 and qty == 0:
                continue
            out.append({
                "category_small_code": code,
                "category_small_name": name,
                "tax_class_code": tax_code,
                "tax_rate": rate,
                "sale_qty": round(qty, 2),
                "invoice_amount": round(amt, 2),
            })
        if out:
            break
    # 按三级类别名称去重：同名称多行合并为一行（数量、金额相加，税率/编码取第一条）
    seen = {}
    for r in out:
        key = (r["category_small_name"] or "").strip()
        if not key:
            continue
        if key not in seen:
            seen[key] = dict(r)
        else:
            seen[key]["sale_qty"] = round(seen[key]["sale_qty"] + r["sale_qty"], 2)
            seen[key]["invoice_amount"] = round(seen[key]["invoice_amount"] + r["invoice_amount"], 2)
    return list(seen.values())





















# ---------- 收益评估（加盟商分账）API ----------




@app.route("/product_master")
def page_product_master():
    """分店商品档案页：深度分析看板（KPI、状态/品类/品牌/价格带/经销/供应商/属性/数据质量），数据由 /api/product_master_analysis 提供。"""
    if _auth_enabled() and (not _is_logged_in() or not _has_module_access("product_master")):
        return Response("您无权访问分店商品档案模块，请联系管理员。", status=403)
    return send_from_directory("static", "product_master.html", mimetype="text/html; charset=utf-8")


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
        ".box{background:#1e293b;border:1px solid #334155;border-radius:6px;padding:12px 10px;margin-bottom:12px;}"
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
    "  if(!confirm('【提醒】将永久删除全部人力成本明细与汇总数据，且无法恢复。仅清空人力相关表，不影响销售/库存/商品档案。\n\n确定清空？清空后需重新导入人力 Excel。')) return;"
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
        # 经营 vs 管理：仅按映射表拆分。无任何映射时全部计入经营；有映射时，仅命中「管理」的计入管理，其余（含未在映射表中的岗位）默认归经营（与设计文档一致）
        no_mapping = not op_positions and not mgr_positions
        for r in labor_rows:
            pos = (r.get("position_name") or "").strip()
            cost = float(r.get("cost") or 0) * weight
            matched_mgr = any(_labor_analysis_position_matches_mapping(pos, lab, mt) for lab, mt in mgr_positions)
            matched_op = any(_labor_analysis_position_matches_mapping(pos, lab, mt) for lab, mt in op_positions)
            if matched_mgr:
                management_cost += cost
                management_head += weight
            else:
                # 命中经营 或 无映射 或 未在映射表中：均计入经营
                operational_cost += cost
                operational_head += weight
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




@app.route("/labor_analysis")
def page_labor_analysis():
    """人力分析 Tab 页：时间段选择、经营/管理总览、类目明细、管理按岗位与人名。"""
    if _auth_enabled() and (not _is_logged_in() or not _has_module_access("labor")):
        return Response("您无权访问人力分析，请联系管理员。", status=403)
    return send_from_directory(app.static_folder, "labor_analysis.html")







def _date_condition(period, start_date=None, end_date=None):
    """返回 (date_cond, params) 用于 SQL。委托 query_layer 实现，保持兼容。"""
    return _ql_date_condition(period, start_date, end_date)


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
    """从 request 解析筛选条件。返回 (date_cond, date_params, params, sale_category_cond, sku_cond)。委托 query_layer 实现，保持兼容。"""
    date_cond, date_params, params, sale_category_cond, sku_cond = _ql_query_filters(include_sku=include_sku)
    # query_layer 返回的 params 首项为占位 None，替换为 STORE_ID
    if params and params[0] is None:
        params = (STORE_ID,) + tuple(params[1:])
    return date_cond, date_params, params, sale_category_cond, sku_cond


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


def api_sales_trend(granularity):
    """按日/周/月聚合销售额与毛利趋势。与 KPI 一致，均从 t_htma_sale 聚合。"""
    date_cond, date_params, params, category_cond, sku_cond = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if granularity == "day":
                cur.execute(f"""
                    SELECT data_date AS x_date,
                           COALESCE(SUM(sale_amount), 0) AS sale_amount,
                           COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                    GROUP BY data_date ORDER BY data_date
                """, params)
                rows = cur.fetchall()
                out = [_format_trend_row(r, "day") for r in rows]
            elif granularity == "week":
                cur.execute(f"""
                    SELECT MIN(data_date) AS week_start,
                           CONCAT(YEAR(MIN(data_date)), '-W', LPAD(WEEK(MIN(data_date), 3), 2, '0')) AS x_date,
                           COALESCE(SUM(sale_amount), 0) AS sale_amount,
                           COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                    GROUP BY YEAR(data_date), WEEK(data_date, 3)
                    ORDER BY MIN(data_date)
                """, params)
                rows = cur.fetchall()
                out = [_format_trend_row(r, "week") for r in rows]
            else:  # month
                cur.execute(f"""
                    SELECT DATE_FORMAT(MIN(data_date), '%%Y-%%m') AS x_date,
                           COALESCE(SUM(sale_amount), 0) AS sale_amount,
                           COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                    GROUP BY YEAR(data_date), MONTH(data_date)
                    ORDER BY MIN(data_date)
                """, params)
                rows = cur.fetchall()
                out = [_format_trend_row(r, "month") for r in rows]
            data_source = "sale"
        if not out:
            return jsonify({
                "data": [],
                "dates": [],
                "sales": [],
                "gross_profit": [],
                "data_source": None,
                "empty_hint": "所选条件下无销售数据，请调整周期或品类筛选后再试。",
            })
        dates = [r["x_date"] for r in out]
        sales = [r["sale_amount"] for r in out]
        gross_profit_list = [r["profit_amount"] for r in out]
        return jsonify({
            "data": out,
            "dates": dates,
            "sales": sales,
            "gross_profit": gross_profit_list,
            "data_source": data_source,
            "empty_hint": None,
        })
    except Exception as e:
        return jsonify({"error": str(e), "data": [], "data_source": None, "empty_hint": "请求异常，请稍后重试。"}), 500
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


def _price_band_unit_cond(band):
    """根据价格带返回 SQL 条件：件单价 (sale_amount/sale_qty) 落在该区间。返回 (cond_sql,)."""
    band = (band or "").strip()
    if band == "0":
        return (" AND COALESCE(sale_qty, 0) <= 0 ",)
    if band == "0-10":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) < 10 ",)
    if band == "10-30":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) >= 10 AND (sale_amount / sale_qty) < 30 ",)
    if band == "30-50":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) >= 30 AND (sale_amount / sale_qty) < 50 ",)
    if band == "50-100":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) >= 50 AND (sale_amount / sale_qty) < 100 ",)
    if band == "100+":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) >= 100 ",)
    return (" AND 1=0 ",)


def _advanced_search_range_days(period, start_date, end_date):
    """根据 period/start_date/end_date 计算查询区间天数，用于周转天数计算。"""
    if start_date and end_date:
        try:
            s = datetime.strptime(start_date, "%Y-%m-%d").date() if isinstance(start_date, str) else start_date
            e = datetime.strptime(end_date, "%Y-%m-%d").date() if isinstance(end_date, str) else end_date
            if s > e:
                s, e = e, s
            return max(1, (e - s).days + 1)
        except (ValueError, TypeError):
            pass
    if period == "day":
        return 1
    if period == "week":
        return 7
    if period == "month":
        today = date.today()
        try:
            from calendar import monthrange
            return monthrange(today.year, today.month)[1]
        except Exception:
            return 30
    return int(os.environ.get("HTMA_DAYS", DEFAULT_DAYS))


def _enrich_advanced_search_with_price_compare(conn, items):
    """为高级查询结果每项附加最新比价信息（从 t_price_compare 取各平台最新一条）。"""
    if not items:
        return items
    sku_list = list({x.get("sku_code") for x in items if x.get("sku_code")})
    if not sku_list:
        return items
    try:
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(sku_list))
        cur.execute(
            """
            SELECT sku_code, platform, price, original_price, promotion_info, good_rate, capture_date
            FROM t_price_compare
            WHERE sku_code IN (""" + placeholders + """)
            ORDER BY capture_date DESC
            """,
            sku_list,
        )
        rows = cur.fetchall()
        cur.close()
        by_sku = {}
        for r in rows:
            sku = r.get("sku_code")
            if sku not in by_sku:
                by_sku[sku] = {}
            platform = r.get("platform") or ""
            if platform and platform not in by_sku[sku]:
                cap = r.get("capture_date")
                by_sku[sku][platform] = {
                    "price": float(r["price"]) if r.get("price") is not None else None,
                    "original_price": float(r["original_price"]) if r.get("original_price") is not None else None,
                    "promotion": (r.get("promotion_info") or "")[:200],
                    "good_rate": float(r["good_rate"]) if r.get("good_rate") is not None else None,
                    "capture_date": cap.strftime("%Y-%m-%d %H:%M") if cap else None,
                }
        for x in items:
            x["price_compare"] = by_sku.get(x.get("sku_code")) or {}
        return items
    except Exception:
        for x in items:
            x["price_compare"] = {}
        return items


def _structured_report_to_html(report):
    """将结构化报告 dict 转为可读 HTML，用于导出下载。"""
    if not report:
        return "<!DOCTYPE html><html><head><meta charset=\"utf-8\"/><title>报告</title></head><body><p>无数据</p></body></html>"
    import html as html_module
    parts = ["<!DOCTYPE html><html><head><meta charset=\"utf-8\"/>", "<title>结构化分析报告</title>", "<style>body{font-family:sans-serif;margin:20px;background:#0f172a;color:#e2e8f0;} h2{margin-top:24px;color:#38bdf8;} table{border-collapse:collapse;} th,td{border:1px solid #334155;padding:6px 10px;text-align:left;} th{background:#1e293b;} .section{margin-bottom:20px;}</style>", "</head><body>"]
    summary = report.get("summary") or {}
    kpi = summary.get("kpi") or {}
    parts.append("<h2>1. 总览</h2><div class=\"section\">")
    parts.append("<p>销售额: %s | 毛利: %s | 毛利率: %s%% | 动销SKU: %s</p>" % (kpi.get("total_sale"), kpi.get("total_profit"), kpi.get("margin_pct"), kpi.get("sku_sold")))
    if summary.get("conclusion"):
        parts.append("<p>%s</p>" % html_module.escape(summary["conclusion"][:500]))
    parts.append("</div>")
    cat = report.get("category_structure") or {}
    if cat.get("top_sales") or cat.get("matrix"):
        parts.append("<h2>2. 品类结构</h2><div class=\"section\">")
        for row in (cat.get("top_sales") or cat.get("matrix") or [])[:15]:
            c = row.get("category") or row.get("cat") or "-"
            s = row.get("sale_amount") or row.get("sale") or 0
            p = row.get("profit") or 0
            parts.append("<p>%s — 销售: %s 毛利: %s</p>" % (html_module.escape(str(c)), s, p))
        parts.append("</div>")
    drill = report.get("drill_section") or {}
    if drill.get("brands") or drill.get("styles") or drill.get("skus"):
        parts.append("<h2>3. 下钻摘要</h2><div class=\"section\">")
        parts.append("<p>类型: %s</p>" % html_module.escape(drill.get("type", "")))
        for b in (drill.get("brands") or [])[:10]:
            parts.append("<p>品牌: %s 销售: %s</p>" % (html_module.escape(str(b.get("brand"))), b.get("sale_amount")))
        for s in (drill.get("styles") or [])[:10]:
            parts.append("<p>款式: %s 销售: %s</p>" % (html_module.escape(str(s.get("product_name"))), s.get("sale_amount")))
        for s in (drill.get("skus") or [])[:15]:
            parts.append("<p>货号: %s 销售: %s</p>" % (html_module.escape(str(s.get("sku_code"))), s.get("sale_amount")))
        parts.append("</div>")
    issues = report.get("issues") or {}
    rg = issues.get("return_gift") or {}
    if rg.get("return_rate") is not None or rg.get("return_by_cat"):
        parts.append("<h2>4. 问题与行动</h2><div class=\"section\">")
        parts.append("<p>退货率: %s%%</p>" % (rg.get("return_rate") or 0))
        parts.append("</div>")
    if report.get("market_expansion"):
        parts.append("<h2>5. 市场拓展</h2><div class=\"section\"><pre>%s</pre></div>" % html_module.escape((report["market_expansion"] or "")[:2000]))
    parts.append("</body></html>")
    return "".join(parts)


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


def _platforms_returned_from_items(items):
    """从比价结果 items 中汇总本次返回的平台名（用于前端展示）。"""
    seen = set()
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        plat = it.get("platform") or ""
        if not plat or plat == "模拟":
            continue
        for part in plat.replace("，", "、").split("、"):
            part = part.strip()
            if ":" in part:
                name = part.split(":", 1)[0].strip()
            else:
                name = part
            if name and len(name) < 20:
                seen.add(name)
        if it.get("jd_min_price") is not None:
            seen.add("京东")
        if it.get("taobao_min_price") is not None:
            seen.add("淘宝")
    return sorted(seen)


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
