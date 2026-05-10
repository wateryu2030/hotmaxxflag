# -*- coding: utf-8 -*-
"""页面权限工具函数 — 从 app.py 抽出，供页面蓝图与鉴权逻辑共用。"""

import os

from flask import session, current_app


def _auth_enabled():
    """是否启用登录（配置了飞书应用则启用）。"""
    try:
        from auth import is_feishu_configured
        return is_feishu_configured(
            app_id=current_app.config.get("FEISHU_APP_ID"),
            app_secret=current_app.config.get("FEISHU_APP_SECRET"),
        )
    except Exception:
        return False


def _parse_id_list(env_name):
    """从环境变量解析以逗号/分号分隔的 open_id / user_id 列表。"""
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
    """基于环境变量控制模块访问权限。"""
    uid = (user_id or session.get("open_id") or session.get("user_id") or "").strip()
    if not uid:
        return False
    # 超级管理员
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
    if not allowed:
        return True
    return uid in allowed


def _is_logged_in():
    """当前 session 是否有已登录用户。"""
    return bool(session.get("user_id") or session.get("open_id"))
