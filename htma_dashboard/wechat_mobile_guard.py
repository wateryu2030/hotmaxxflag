# -*- coding: utf-8 -*-
"""小程序 /api/mobile/* 鉴权：优先 JWT；可选强制仅微信登录。"""
import sys

from flask import jsonify, request

from wechat_config import skip_mobile_jwt, wechat_mini_enabled
from wechat_jwt import decode_token


def _app():
    """python app.py 时主模块在 sys.modules['__main__']，无 'app' 键；须兼容。"""
    return sys.modules.get("app") or sys.modules.get("__main__")


def _bearer_token():
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def resolve_mobile_context():
    """
    设置 flask.g：
    - mobile_store_id: 单店过滤用；None 表示不按店过滤（全店汇总）
    - mobile_scope: 'single' | 'all'
    返回 None 表示放行；返回 (response, status) 表示拦截。
    """
    from flask import g

    M = _app()

    if skip_mobile_jwt():
        g.mobile_scope = "single"
        g.mobile_store_id = (M.STORE_ID if M else None) or "沈阳超级仓"
        g.wechat_jwt_payload = None
        return None

    tok = _bearer_token()
    if tok:
        pl = decode_token(tok)
        if pl:
            g.wechat_jwt_payload = pl
            sid = (pl.get("store_id") or "").strip()
            if sid:
                g.mobile_scope = "single"
                g.mobile_store_id = sid
            else:
                g.mobile_scope = "all"
                g.mobile_store_id = None
            return None

    if wechat_mini_enabled():
        return (
            jsonify({
                "success": False,
                "message": "请先使用微信登录",
                "wechat_login_required": True,
            }),
            401,
        )

    if M and M._auth_enabled() and not M._is_logged_in():
        return jsonify({"success": False, "login_required": True}), 401

    g.mobile_scope = "single"
    g.mobile_store_id = (M.STORE_ID if M else None) or "沈阳超级仓"
    g.wechat_jwt_payload = None
    return None


def mobile_store_sql_prefix():
    """返回 (' AND store_id = %s ', [id]) 或 ('', [])。"""
    from flask import g

    if getattr(g, "mobile_scope", "single") == "all":
        return "", []
    sid = getattr(g, "mobile_store_id", None)
    if not sid:
        return "", []
    return " AND store_id = %s ", [sid]
