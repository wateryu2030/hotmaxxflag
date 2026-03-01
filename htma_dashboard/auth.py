# -*- coding: utf-8 -*-
"""
飞书 / 企微扫码授权登录：生成授权 URL、用 code 换 token、获取用户信息。
依赖环境变量：FEISHU_APP_ID、FEISHU_APP_SECRET；回调地址需在飞书开放平台配置 redirect_uri。
"""
import os
import urllib.parse
import requests


def _feishu_app_id():
    return (os.environ.get("FEISHU_APP_ID") or "").strip()


def _feishu_app_secret():
    return (os.environ.get("FEISHU_APP_SECRET") or "").strip()


def _allowed_open_ids():
    return [x.strip() for x in (os.environ.get("HTMA_ALLOWED_FEISHU_OPEN_IDS") or "").split(",") if x.strip()]

# 飞书 OAuth 文档: https://open.feishu.cn/document/common-capabilities/sso/web-application/scan-code-login
FEISHU_AUTH_BASE = "https://open.feishu.cn/open-apis"
# 自建应用获取 tenant_access_token（用于后端用 code 换 user_access_token）
TENANT_ACCESS_TOKEN_URL = f"{FEISHU_AUTH_BASE}/auth/v3/tenant_access_token/internal"
# 授权页（用户扫码或确认后跳回 redirect_uri?code=xxx）
AUTHORIZE_URL = f"{FEISHU_AUTH_BASE}/authen/v1/authorize"
# 用 code 换 user_access_token
ACCESS_TOKEN_URL = f"{FEISHU_AUTH_BASE}/authen/v1/access_token"
# 获取当前授权用户信息
USER_INFO_URL = f"{FEISHU_AUTH_BASE}/authen/v1/user_info"


def _tenant_access_token(app_id=None, app_secret=None):
    """获取飞书自建应用 tenant_access_token（后端用 code 换 user_access_token 时请求头需此 token）"""
    app_id = (app_id or _feishu_app_id() or "").strip()
    app_secret = (app_secret or _feishu_app_secret() or "").strip()
    if not app_id or not app_secret:
        return None, "未配置 FEISHU_APP_ID / FEISHU_APP_SECRET"
    r = requests.post(
        TENANT_ACCESS_TOKEN_URL,
        json={"app_id": app_id, "app_secret": app_secret},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    if r.status_code != 200:
        return None, f"tenant_token 请求失败: {r.status_code}"
    data = r.json()
    if data.get("code") != 0:
        return None, data.get("msg", "tenant_token 返回错误")
    return data.get("tenant_access_token"), None


def get_feishu_authorize_url(redirect_uri, state=None, app_id=None, app_secret=None):
    """
    生成飞书授权 URL，前端跳转后飞书展示二维码，用户扫码确认后跳回 redirect_uri?code=xxx&state=xxx。
    redirect_uri 需与飞书开放平台「安全设置」中配置的重定向 URL 完全一致。
    可选传入 app_id/app_secret，否则从环境变量读取。
    """
    app_id = (app_id or _feishu_app_id() or "").strip()
    if not app_id:
        return None, "未配置 FEISHU_APP_ID"
    params = {
        "app_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": "contact:user.base:readonly",  # 获取用户基础信息
        "state": state or "",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}", None


def feishu_exchange_code_and_user(code, redirect_uri, app_id=None, app_secret=None):
    """
    用授权码 code 换取 user_access_token，再拉取用户信息。
    返回 (user_dict, None) 或 (None, error_msg)。
    user_dict 至少含 open_id, name；可选 union_id, avatar_url 等。
    可选传入 app_id/app_secret，否则从环境变量读取。
    """
    if not code:
        return None, "缺少 code"
    tenant_token, err = _tenant_access_token(app_id=app_id, app_secret=app_secret)
    if err:
        return None, err

    # 用 code 换 user_access_token（请求头使用 tenant_access_token）
    r = requests.post(
        ACCESS_TOKEN_URL,
        json={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {tenant_token}"},
        timeout=10,
    )
    if r.status_code != 200:
        return None, f"access_token 请求失败: {r.status_code}"
    data = r.json()
    if data.get("code") != 0:
        return None, data.get("msg", "code 兑换失败")
    user_access_token = data.get("data", {}).get("access_token")
    if not user_access_token:
        return None, "未返回 access_token"

    # 获取用户信息
    r2 = requests.get(
        USER_INFO_URL,
        headers={"Authorization": f"Bearer {user_access_token}"},
        timeout=10,
    )
    if r2.status_code != 200:
        return None, f"user_info 请求失败: {r2.status_code}"
    info = r2.json()
    if info.get("code") != 0:
        return None, info.get("msg", "获取用户信息失败")
    ud = info.get("data", {})
    open_id = ud.get("open_id") or ud.get("union_id") or ""
    name = (ud.get("name") or ud.get("en_name") or open_id or "飞书用户").strip()
    if not open_id:
        return None, "用户信息中无 open_id"

    allowed = _allowed_open_ids()
    if allowed and open_id not in allowed:
        return None, "您不在允许登录的名单中，请联系管理员"

    return {
        "open_id": open_id,
        "name": name,
        "union_id": ud.get("union_id"),
        "avatar_url": ud.get("avatar_url"),
    }, None


def is_feishu_configured(app_id=None, app_secret=None):
    """是否已配置飞书：可传入 app_id/app_secret，否则从环境变量判断"""
    if app_id is not None and app_secret is not None:
        return bool((app_id or "").strip() and (app_secret or "").strip())
    return bool(_feishu_app_id() and _feishu_app_secret())
