# -*- coding: utf-8 -*-
"""serve_web/feishu_auth：飞书认证授权 API（web 端登录、回调、审批）"""

from flask import Response, Blueprint, jsonify, request, session, redirect, url_for
from datetime import datetime, timedelta
import os, pymysql, pymysql.cursors

from core.db import get_conn
from core.utils import safe_str, safe_int
from page_auth import _is_logged_in, _has_module_access, _is_super_admin
from auth import is_feishu_configured, get_feishu_authorize_url, feishu_exchange_code_and_user, _super_admin_open_id

feishu_web_bp = Blueprint("feishu_web", __name__)



def _feishu_callback_base_url():
    """飞书回调 redirect_uri 的站点根 URL。"""
    try:
        host = (request.host or "").split(":")[0]
        if host in ("127.0.0.1", "localhost") or host.startswith("127.0.0."):
            return request.url_root.rstrip("/")
    except Exception:
        pass
    base = (os.environ.get("HTMA_PUBLIC_URL") or os.environ.get("PUBLIC_URL") or "").strip()
    if base:
        return base.rstrip("/")
    try:
        proto = request.headers.get("X-Forwarded-Proto", request.scheme or "http")
        if (proto or "").lower() == "https":
            return ("https://" + (request.host or "")).rstrip("/")
    except Exception:
        pass
    return ""


def _ensure_env_loaded():
    """请求时若飞书未配置则再次从 .env 注入。"""
    from page_auth import _auth_enabled
    if not (current_app.config.get("FEISHU_APP_ID") or "").strip() and (os.environ.get("FEISHU_APP_ID") or "").strip():
        current_app.config["FEISHU_APP_ID"] = (os.environ.get("FEISHU_APP_ID") or "").strip()
        current_app.config["FEISHU_APP_SECRET"] = (os.environ.get("FEISHU_APP_SECRET") or "").strip()
    if not (current_app.config.get("FEISHU_APP_ID") or "").strip():
        direct_id, direct_secret = _read_feishu_from_project_env()
        if direct_id and direct_secret:
            current_app.config["FEISHU_APP_ID"] = direct_id
            current_app.config["FEISHU_APP_SECRET"] = direct_secret
    if _auth_enabled():
        return True

@feishu_web_bp.route("/api/auth/me")
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
        "can_profit_share": _has_module_access("profit_share", user_id),
        "can_tax_analysis": _has_module_access("tax_analysis", user_id),
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
    from flask import current_app
    from app_factory import _get_app_module
    _app_mod = _get_app_module()
    if not (current_app.config.get("FEISHU_APP_ID") or "").strip() and (os.environ.get("FEISHU_APP_ID") or "").strip():
        current_app.config["FEISHU_APP_ID"] = (os.environ.get("FEISHU_APP_ID") or "").strip()
        current_app.config["FEISHU_APP_SECRET"] = (os.environ.get("FEISHU_APP_SECRET") or "").strip()
    if not (current_app.config.get("FEISHU_APP_ID") or "").strip():
        direct_id, direct_secret = _app_mod._read_feishu_from_project_env()
        if direct_id and direct_secret:
            current_app.config["FEISHU_APP_ID"] = direct_id
            current_app.config["FEISHU_APP_SECRET"] = direct_secret
    from page_auth import _auth_enabled
    if _auth_enabled():
        return True
    root = current_app.config.get("PROJECT_ROOT") or _app_mod._project_root
    candidates = [
        current_app.config.get("ENV_PATH"),
        os.path.join(root, ".env") if root else None,
        os.path.join(os.getcwd(), ".env"),
        os.path.abspath(os.path.join(os.getcwd(), "..", ".env")),
    ]
    for path in candidates:
        if path:
            _app_mod._load_env_from_file(
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
        if not (current_app.config.get("FEISHU_APP_ID") or "").strip() and (os.environ.get("FEISHU_APP_ID") or "").strip():
            current_app.config["FEISHU_APP_ID"] = (os.environ.get("FEISHU_APP_ID") or "").strip()
            current_app.config["FEISHU_APP_SECRET"] = (os.environ.get("FEISHU_APP_SECRET") or "").strip()
        if _auth_enabled():
            return True
    return False

@feishu_web_bp.route("/api/auth/feishu_url")
def api_auth_feishu_url():
    """获取飞书授权 URL，前端跳转后用户扫码授权"""
    from flask import current_app
    _ensure_env_loaded()
    env_path = current_app.config.get("ENV_PATH", "")
    if env_path:
        _mod = __import__('app_factory')._get_app_module()
        direct_id, direct_secret = _mod._read_feishu_from_env_file(env_path)
        if direct_id and direct_secret:
            current_app.config["FEISHU_APP_ID"] = direct_id
            current_app.config["FEISHU_APP_SECRET"] = direct_secret
    feishu_id = (current_app.config.get("FEISHU_APP_ID") or "").strip()
    feishu_secret = (current_app.config.get("FEISHU_APP_SECRET") or "").strip()
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
@feishu_web_bp.route("/api/auth/feishu_callback")
def api_auth_feishu_callback():
    """飞书授权回调：企业内直接登录；企业外需审批通过后才可访问。"""
    from flask import current_app
    from auth import feishu_exchange_code_and_user, _super_admin_open_id
    code = request.args.get("code")
    if not code:
        return redirect("/login?error=missing_code")
    base = _feishu_callback_base_url()
    redirect_uri = base + "/api/auth/feishu_callback"
    user, err = feishu_exchange_code_and_user(
        code,
        redirect_uri,
        app_id=current_app.config.get("FEISHU_APP_ID"),
        app_secret=current_app.config.get("FEISHU_APP_SECRET"),
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
    # 超级管理员若直接回首页且有待审批，先跳到管理员提醒页
    try:
        from auth import _super_admin_open_id
        admin_oid = (_super_admin_open_id() or "").strip()
        oid = (user.get("open_id") or "").strip()
        if admin_oid and oid and next_url == "/":
            if oid == admin_oid or oid.replace("ou_", "") == admin_oid.replace("ou_", ""):
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM t_htma_external_access WHERE status = 'pending'")
                n = (cur.fetchone() or (0,))[0]
                cur.close()
                conn.close()
                if n > 0:
                    next_url = "/admin"
    except Exception:
        pass
    return redirect(next_url or "/")


@feishu_web_bp.route("/api/auth/pending_count")
def api_auth_pending_count():
    """待审批数量（仅超级管理员可查，用于提醒页）"""
    if not _is_super_admin():
        return jsonify({"success": True, "is_super_admin": False, "pending_count": 0})
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM t_htma_external_access WHERE status = 'pending'")
        n = (cur.fetchone() or (0,))[0]
        cur.close()
        conn.close()
        return jsonify({"success": True, "is_super_admin": True, "pending_count": n})
    except Exception as e:
        return jsonify({"success": False, "message": str(e), "pending_count": 0}), 500
@feishu_web_bp.route("/api/auth/approvals")
def api_auth_approvals():
    """待审批列表（仅超级管理员）"""
    if not _is_super_admin():
        return jsonify({"success": False, "message": "仅超级管理员可查看"}), 403
    try:
        conn = get_conn()
        cur = conn.cursor(pymysql.cursors.DictCursor)
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
@feishu_web_bp.route("/api/auth/approve", methods=["POST"])
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
@feishu_web_bp.route("/api/auth/logout")
def api_auth_logout():
    """退出登录"""
    session.clear()
    return redirect("/login")


@feishu_web_bp.route("/api/feishu/bot/event", methods=["POST", "GET", "HEAD"])
@feishu_web_bp.route("/feishu/callback", methods=["POST", "GET", "HEAD"])
def api_feishu_bot_event():
    """飞书自建应用机器人事件订阅回调（群内 @ 机器人 / 私聊回复）。
    可用路径（二选一，与开放平台配置一致即可）：
    - /api/feishu/bot/event（推荐，与看板同端口 5002）
    - /feishu/callback（与常见教程路径一致，反代需指向本服务 5002）
    """
    if request.method == "GET":
        return jsonify({"ok": True, "service": "htma-feishu-bot", "method": "POST events here"}), 200
    if request.method == "HEAD":
        return Response("", status=200)
    _ensure_env_loaded()
    app_id = (current_app.config.get("FEISHU_APP_ID") or "").strip()
    app_secret = (current_app.config.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        return jsonify({"msg": "未配置 FEISHU_APP_ID / FEISHU_APP_SECRET"}), 503
    from feishu_bot import process_feishu_bot_http_request

    payload, code = process_feishu_bot_http_request(
        request.get_data(cache=False, as_text=False),
        request.headers,
        app_id,
        app_secret,
    )
    return jsonify(payload), code



