# -*- coding: utf-8 -*-
"""Flask 应用工厂：集中创建 app、配置、钩子与蓝图注册（Phase 8B）。"""

from __future__ import annotations

import os
import urllib.parse

from flask import Flask, Response, jsonify, redirect, request, session


def _get_app_module():
    """返回 app 模块。在 python app.py（__main__）和 from app import app 两种模式下都能工作。"""
    import sys
    mod = sys.modules.get("app")
    if mod is not None:
        return mod
    # app.py 被当作 __main__ 执行时，sys.modules['app'] 不存在
    import __main__
    return __main__


def create_app(config_overrides=None, *, project_root=None, env_path=None):
    """创建并返回 Flask 应用实例。默认从已部分初始化的 app 模块读取路径与飞书辅助函数。"""
    app_mod = _get_app_module()

    if project_root is None:
        project_root = app_mod._project_root
    if env_path is None:
        env_path = app_mod._env_path

    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB，避免大 Excel 413
    app.config["PROJECT_ROOT"] = project_root
    app.config["ENV_PATH"] = env_path
    # 飞书登录：启动时从项目根 .env 直接读 + os.environ 写入 app.config（保证子进程未继承 env 时也能用）
    _direct_id, _direct_secret = app_mod._read_feishu_from_project_env()
    app.config["FEISHU_APP_ID"] = (_direct_id or (os.environ.get("FEISHU_APP_ID") or "").strip()).strip()
    app.config["FEISHU_APP_SECRET"] = (_direct_secret or (os.environ.get("FEISHU_APP_SECRET") or "").strip()).strip()
    if not app.config["FEISHU_APP_ID"]:
        for _p in (env_path, os.path.abspath(os.path.join(os.getcwd(), "..", ".env"))):
            app_mod._load_env_from_file(_p)
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

    if config_overrides:
        app.config.update(config_overrides)

    @app.before_request
    def _require_auth():
        """未配置登录时放行；已配置则未登录用户只能访问登录页与 auth 接口，必须登录后才能看运营看板"""
        if (os.environ.get("HTMA_UNITTEST_DISABLE_AUTH") or "").strip().lower() in ("1", "true"):
            return None
        if request.method == "OPTIONS" and request.path.startswith("/api/"):
            return Response("", status=204)
        for _k in ("FEISHU_APP_ID", "FEISHU_APP_SECRET"):
            _v = (app.config.get(_k) or "").strip()
            if _v and not (os.environ.get(_k) or "").strip():
                os.environ[_k] = _v
        if not app_mod._auth_enabled():
            return None
        path = request.path.rstrip("/") or "/"
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
        if path == "/api/labor_cost_status" or path == "/api/labor_cost" or path == "/api/labor_cost_analysis":
            return None
        if path.startswith("/api/labor_analysis/"):
            return None
        if path.startswith("/static/") or (path != "/" and not path.startswith("/api/") and "." in path.split("/")[-1]):
            return None
        if app_mod._is_logged_in():
            return None
        if path in ("/import", "/product_master", "/profit_share", "/tax_analysis", "/hongbeilou") or path.startswith("/api/"):
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "message": "请先登录", "login_required": True}), 401
            return redirect("/login?next=" + (urllib.parse.quote(request.url) if request.url else "/"))
        return None

    from extensions import init_flask_caching

    init_flask_caching(app)

    from serve_web.overview import overview_bp
    from serve_web.pages_core import pages_core_bp
    from serve_web.pages_modules import pages_modules_bp
    from routes_mobile import register_mobile_routes
    from routes_biz_enhanced import register_biz_routes
    from wechat_api import register_wechat_mini_routes
    from labor_routes import register_labor_blueprints
    from serve_web.pages_labor import pages_labor_bp
    from serve_web.category_rank import cat_rank_bp
    from serve_web.profit import profit_bp
    from serve_web.report import report_bp
    from serve_web.channel import channel_bp
    from serve_web.sync import sync_bp
    from serve_web.catalog import catalog_bp
    from serve_web.feishu_auth import feishu_web_bp
    from serve_web.import_api import import_api_bp
    from serve_web.content import content_bp
    from serve_web.tax import tax_bp
    from serve_web.profit_share import profit_share_bp
    from serve_web.product_master import product_bp
    from serve_web.price_compare import price_bp
    from routes_sales import register_sales_routes
    from routes_category import register_category_routes

    app.register_blueprint(overview_bp)
    app.register_blueprint(pages_core_bp)
    app.register_blueprint(pages_modules_bp)
    register_mobile_routes(app)
    register_biz_routes(app)
    register_wechat_mini_routes(app)
    register_labor_blueprints(app)
    app.register_blueprint(pages_labor_bp)
    app.register_blueprint(cat_rank_bp)
    app.register_blueprint(profit_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(channel_bp)
    app.register_blueprint(sync_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(feishu_web_bp)
    app.register_blueprint(import_api_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(tax_bp)
    app.register_blueprint(profit_share_bp)
    app.register_blueprint(product_bp)
    app.register_blueprint(price_bp)
    register_sales_routes(app)
    register_category_routes(app)

    @app.after_request
    def add_cors_headers(response):
        """允许跨域，便于 Cursor 预览、OpenClaw 等不同源访问"""
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

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

    return app
