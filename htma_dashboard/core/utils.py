# -*- coding: utf-8 -*-
"""
通用工具函数：安全类型转换、环境变量加载等。
"""
import os


def safe_int(val, default=0):
    """安全转换为 int，失败返回 default。"""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def safe_float(val, default=0.0):
    """安全转换为 float，失败返回 default。"""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_str(val, default=""):
    """安全转换为 str，失败返回 default。"""
    if val is None:
        return default
    try:
        return str(val)
    except Exception:
        return default


def _ensure_env_loaded():
    """请求时若飞书未配置则再次从 .env 注入，并写入 app.config 供后续请求使用。
    通过延迟导入避免与 app.py 循环依赖。"""
    # 延迟导入 app 模块（避免循环导入，此时 app 模块已加载完毕）
    from app import app as _app
    from app import _load_env_from_file, _read_feishu_from_project_env, _auth_enabled

    if not (_app.config.get("FEISHU_APP_ID") or "").strip() and (os.environ.get("FEISHU_APP_ID") or "").strip():
        _app.config["FEISHU_APP_ID"] = (os.environ.get("FEISHU_APP_ID") or "").strip()
        _app.config["FEISHU_APP_SECRET"] = (os.environ.get("FEISHU_APP_SECRET") or "").strip()
    if not (_app.config.get("FEISHU_APP_ID") or "").strip():
        direct_id, direct_secret = _read_feishu_from_project_env()
        if direct_id and direct_secret:
            _app.config["FEISHU_APP_ID"] = direct_id
            _app.config["FEISHU_APP_SECRET"] = direct_secret
    if _auth_enabled():
        return True
    root = _app.config.get("PROJECT_ROOT") or ""
    import os as _os
    candidates = [
        _app.config.get("ENV_PATH"),
        _os.path.join(root, ".env") if root else None,
        _os.path.join(_os.getcwd(), ".env"),
        _os.path.abspath(_os.path.join(_os.getcwd(), "..", ".env")),
    ]
    for path in candidates:
        if path:
            _load_env_from_file(
                path,
                force_keys=(
                    "FEISHU_APP_ID",
                    "FEISHU_APP_SECRET",
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
    if not (_app.config.get("FEISHU_APP_ID") or "").strip() and (os.environ.get("FEISHU_APP_ID") or "").strip():
        _app.config["FEISHU_APP_ID"] = (os.environ.get("FEISHU_APP_ID") or "").strip()
        _app.config["FEISHU_APP_SECRET"] = (os.environ.get("FEISHU_APP_SECRET") or "").strip()
    if _auth_enabled():
        return True
    return False
