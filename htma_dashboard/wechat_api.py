# -*- coding: utf-8 -*-
"""微信小程序登录与绑定 API（独立于飞书 auth.py）。"""
import os
import sys

from flask import Blueprint, jsonify, request

from wechat_config import wechat_jwt_secret, wechat_mini_enabled
from wechat_jwt import decode_token, issue_token
from wechat_phone_decrypt import decrypt_phone
from wechat_user_repo import get_by_id, get_by_phone, list_users, update_feishu_open_id, update_phone, upsert_user_after_login
from wechat_wxa import get_phone_number_from_code, jscode2session


def _bearer_token():
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _require_wechat_jwt():
    tok = _bearer_token()
    if not tok:
        return None, (jsonify({"success": False, "message": "缺少 Authorization: Bearer token"}), 401)
    pl = decode_token(tok)
    if not pl:
        return None, (jsonify({"success": False, "message": "token 无效或已过期"}), 401)
    uid = int(pl.get("sub") or 0)
    row = get_by_id(uid)
    if not row:
        return None, (jsonify({"success": False, "message": "用户不存在"}), 401)
    return row, None


wechat_mini_bp = Blueprint("wechat_mini", __name__, url_prefix="/api/wechat")


def _subscribe_template_ids_list():
    """与 wechat_scheduler 共用：WECHAT_SUBSCRIBE_TEMPLATE_ID 可一个或逗号分隔多个。"""
    raw = (os.environ.get("WECHAT_SUBSCRIBE_TEMPLATE_ID") or "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def register_wechat_mini_routes(app):
    app.register_blueprint(wechat_mini_bp)


@wechat_mini_bp.route("/login", methods=["POST", "OPTIONS"])
def api_wechat_login():
    """body: { \"code\": \"wx.login\" } → token + user"""
    if request.method == "OPTIONS":
        return "", 204
    if not wechat_jwt_secret():
        return jsonify({"success": False, "message": "服务端未配置 WECHAT_JWT_SECRET，无法签发 token"}), 503
    body = request.get_json(silent=True) or {}
    code = (body.get("code") or "").strip()
    if not code:
        return jsonify({"success": False, "message": "缺少 code"}), 400
    data, err = jscode2session(code)
    if err:
        return jsonify({"success": False, "message": err}), 400
    openid = data["openid"]
    sk = (data.get("session_key") or "").strip() or None
    unionid = data.get("unionid")
    user = upsert_user_after_login(openid, unionid, sk)
    try:
        token = issue_token(
            int(user["id"]),
            openid,
            str(user.get("role") or "operator"),
            user.get("store_id"),
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    return jsonify({
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "openid": openid,
            "role": user.get("role"),
            "store_id": user.get("store_id"),
            "phone": user.get("phone"),
            "feishu_open_id": user.get("feishu_open_id"),
        },
    })


@wechat_mini_bp.route("/bind_phone", methods=["POST", "OPTIONS"])
def api_wechat_bind_phone():
    """
    需 Bearer token。
    body 二选一：
    - 新版：{ \"code\": \"getPhoneNumber 返回的 code\" }
    - 旧版：{ \"encryptedData\": \"...\", \"iv\": \"...\" }（使用登录时存的 session_key）
    """
    if request.method == "OPTIONS":
        return "", 204
    user, err_resp = _require_wechat_jwt()
    if err_resp:
        return err_resp
    body = request.get_json(silent=True) or {}
    phone = None
    perr = None
    phone_code = (body.get("code") or body.get("phoneCode") or "").strip()
    if phone_code:
        phone, perr = get_phone_number_from_code(phone_code)
    else:
        enc = (body.get("encryptedData") or "").strip()
        iv = (body.get("iv") or "").strip()
        sk_b64 = user.get("session_key")
        if enc and iv and sk_b64:
            phone, perr = decrypt_phone(enc, iv, sk_b64)
        else:
            return jsonify({"success": False, "message": "请传 code（新版）或 encryptedData+iv（旧版）"}), 400
    if perr or not phone:
        return jsonify({"success": False, "message": perr or "获取手机号失败"}), 400
    other = get_by_phone(phone)
    if other and int(other["id"]) != int(user["id"]):
        return jsonify({"success": False, "message": "该手机号已被其他微信账号绑定"}), 409
    update_phone(int(user["id"]), phone)
    feishu_map = (os.environ.get("HTMA_PHONE_FEISHU_OPEN_ID_MAP") or "").strip()
    if feishu_map:
        try:
            for pair in feishu_map.split(","):
                parts = pair.split("=", 1)
                if len(parts) == 2 and parts[0].strip() == phone:
                    update_feishu_open_id(int(user["id"]), parts[1].strip())
                    break
        except Exception:
            pass
    u2 = get_by_id(int(user["id"]))
    return jsonify({"success": True, "phone": phone, "user": {"id": u2["id"], "feishu_open_id": u2.get("feishu_open_id")}})


@wechat_mini_bp.route("/bind_feishu", methods=["POST", "OPTIONS"])
def api_wechat_bind_feishu():
    """body: { \"feishu_open_id\": \"ou_xxx\" }，需已登录；可选由运营在库中维护，勿随意开放给前端。"""
    if request.method == "OPTIONS":
        return "", 204
    user, err_resp = _require_wechat_jwt()
    if err_resp:
        return err_resp
    body = request.get_json(silent=True) or {}
    oid = (body.get("feishu_open_id") or "").strip()
    if not oid:
        return jsonify({"success": False, "message": "缺少 feishu_open_id"}), 400
    update_feishu_open_id(int(user["id"]), oid)
    return jsonify({"success": True})


@wechat_mini_bp.route("/subscribe_config", methods=["GET", "OPTIONS"])
def api_wechat_subscribe_config():
    """返回订阅消息模板 ID 列表，供小程序 wx.requestSubscribeMessage。无需登录（模板 ID 本就在客户端可公开）。"""
    if request.method == "OPTIONS":
        return "", 204
    return jsonify({"success": True, "template_ids": _subscribe_template_ids_list()})


@wechat_mini_bp.route("/me", methods=["GET", "OPTIONS"])
def api_wechat_me():
    if request.method == "OPTIONS":
        return "", 204
    user, err_resp = _require_wechat_jwt()
    if err_resp:
        return err_resp
    return jsonify({
        "success": True,
        "user": {
            "id": user["id"],
            "openid": user.get("openid"),
            "phone": user.get("phone"),
            "role": user.get("role"),
            "store_id": user.get("store_id"),
            "feishu_open_id": user.get("feishu_open_id"),
        },
    })


@wechat_mini_bp.route("/token_refresh", methods=["POST", "OPTIONS"])
def api_wechat_token_refresh():
    """Bearer 有效时签发新 token（续期）。"""
    if request.method == "OPTIONS":
        return "", 204
    user, err_resp = _require_wechat_jwt()
    if err_resp:
        return err_resp
    try:
        token = issue_token(
            int(user["id"]),
            (user.get("openid") or "").strip(),
            str(user.get("role") or "operator"),
            user.get("store_id"),
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    return jsonify({"success": True, "token": token})


def _is_super_cli():
    tok = (request.headers.get("X-Wechat-Admin-Token") or "").strip()
    expect = (os.environ.get("HTMA_WECHAT_ADMIN_TOKEN") or "").strip()
    return bool(expect) and tok == expect


@wechat_mini_bp.route("/admin/users", methods=["GET"])
def api_wechat_admin_users():
    """简单列表：需请求头 X-Wechat-Admin-Token 与 HTMA_WECHAT_ADMIN_TOKEN 一致。"""
    if not _is_super_cli():
        return jsonify({"success": False, "message": "无权访问"}), 403
    items = list_users(500)
    return jsonify({"success": True, "items": items})


@wechat_mini_bp.route("/admin/set_role", methods=["POST"])
def api_wechat_admin_set_role():
    """body: { \"user_id\": 1, \"role\": \"store_manager\", \"store_id\": \"沈阳超级仓\" }"""
    if not _is_super_cli():
        return jsonify({"success": False, "message": "无权访问"}), 403
    from wechat_user_repo import update_role_store

    body = request.get_json(silent=True) or {}
    uid = int(body.get("user_id") or 0)
    role = (body.get("role") or "").strip() or "operator"
    if role not in ("store_manager", "region_manager", "operator"):
        return jsonify({"success": False, "message": "role 非法"}), 400
    sid = body.get("store_id")
    sid = sid.strip() if isinstance(sid, str) and sid.strip() else None
    if not uid:
        return jsonify({"success": False, "message": "缺少 user_id"}), 400
    update_role_store(uid, role, sid)
    return jsonify({"success": True})


@wechat_mini_bp.route("/subscribe", methods=["POST", "OPTIONS"])
def api_wechat_subscribe():
    """保存订阅消息授权：body { template_id, is_active? }。需 JWT。"""
    if request.method == "OPTIONS":
        return "", 204
    user, err_resp = _require_wechat_jwt()
    if err_resp:
        return err_resp
    body = request.get_json(silent=True) or {}
    template_id = (body.get("template_id") or "").strip()
    is_active = bool(body.get("is_active", True))
    if not template_id:
        return jsonify({"code": 1, "data": None, "msg": "template_id 必填"}), 400
    from wechat_subscribe_repo import upsert_subscription

    try:
        upsert_subscription(
            int(user["id"]),
            template_id,
            (user.get("openid") or "").strip(),
            is_active,
        )
    except Exception as e:
        return jsonify({"code": 2, "data": None, "msg": str(e)}), 500
    return jsonify({"code": 0, "data": {"ok": True, "template_id": template_id}, "msg": ""})


@wechat_mini_bp.route("/mini/analysis/attribution", methods=["GET", "OPTIONS"])
@wechat_mini_bp.route("/mini/attribution", methods=["GET", "OPTIONS"])
def api_wechat_mini_attribution_mirror():
    """
    与 GET /api/mobile/analysis/attribution 相同数据与 {code,data} 结构。
    当 CDN/网关未将 /api/mobile/* 转到本服务时，小程序可自动回退到此路径（仍须 Bearer JWT）。
    """
    if request.method == "OPTIONS":
        return "", 204
    from wechat_mobile_guard import resolve_mobile_context

    rv = resolve_mobile_context()
    if rv is not None:
        return rv
    from mobile_bi import mobile_attribution_response

    return mobile_attribution_response(audit_channel="wechat_mini")
