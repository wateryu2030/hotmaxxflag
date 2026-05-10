# -*- coding: utf-8 -*-
"""微信服务端 API：jscode2session、access_token、手机号 code 换取。"""
import time
from contextlib import contextmanager, nullcontext
from typing import Any, Dict, Iterator, Optional, Tuple

import certifi
import requests

from wechat_config import wechat_appid, wechat_secret, wx_force_ipv4, wx_trust_env

_WX = "https://api.weixin.qq.com"

_WX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HTMA-WeChatBackend/1.0)",
    "Connection": "close",
}


def _ssl_verify_bundle():
    try:
        return certifi.where()
    except Exception:
        return True


@contextmanager
def _ipv4_only_addrinfo() -> Iterator[None]:
    """强制 getaddrinfo 仅返回 IPv4（部分环境 IPv6 路径会 TLS EOF）。"""
    try:
        import socket
        import urllib3.util.connection as uconn

        _old = uconn.allowed_gai_family
    except Exception:
        yield
        return
    try:
        uconn.allowed_gai_family = lambda: socket.AF_INET  # type: ignore[assignment]
        yield
    finally:
        uconn.allowed_gai_family = _old  # type: ignore[assignment]


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = wx_trust_env()
    s.headers.update(_WX_HEADERS)
    return s


def _wx_get(
    url: str,
    params: Dict[str, Any],
    attempts: int = 3,
    ipv4_only: bool = False,
) -> requests.Response:
    last: Optional[Exception] = None
    verify = _ssl_verify_bundle()
    stack = _ipv4_only_addrinfo() if ipv4_only else nullcontext()
    with stack:
        s = _session()
        for i in range(attempts):
            try:
                r = s.get(
                    url,
                    params=params,
                    timeout=(8, 30),
                    verify=verify,
                )
                s.close()
                return r
            except (
                requests.exceptions.SSLError,
                requests.exceptions.ConnectionError,
            ) as e:
                last = e
                s.close()
                time.sleep(0.5 * (i + 1))
    assert last is not None
    raise last


def _wx_request_get(url: str, params: Dict[str, Any]) -> requests.Response:
    """先直连（禁用代理）重试，再视配置强制 IPv4 重试。"""
    last: Optional[Exception] = None
    modes: list[tuple[str, bool]] = [("default", False)]
    if wx_force_ipv4():
        modes.append(("ipv4", True))
    for _name, ipv4 in modes:
        try:
            return _wx_get(url, params, attempts=4, ipv4_only=ipv4)
        except Exception as e:
            last = e
    assert last is not None
    raise last


def _wx_post_json(url: str, body: Dict[str, Any], attempts: int = 3, ipv4_only: bool = False) -> requests.Response:
    last: Optional[Exception] = None
    verify = _ssl_verify_bundle()
    stack = _ipv4_only_addrinfo() if ipv4_only else nullcontext()
    headers = dict(_WX_HEADERS)
    headers["Content-Type"] = "application/json"
    with stack:
        s = _session()
        s.headers.update(headers)
        for i in range(attempts):
            try:
                r = s.post(
                    url,
                    json=body,
                    timeout=(8, 30),
                    verify=verify,
                )
                s.close()
                return r
            except (
                requests.exceptions.SSLError,
                requests.exceptions.ConnectionError,
            ) as e:
                last = e
                s.close()
                time.sleep(0.5 * (i + 1))
    assert last is not None
    raise last


def _wx_request_post(url: str, body: Dict[str, Any]) -> requests.Response:
    last: Optional[Exception] = None
    modes: list[tuple[str, bool]] = [("default", False)]
    if wx_force_ipv4():
        modes.append(("ipv4", True))
    for _name, ipv4 in modes:
        try:
            return _wx_post_json(url, body, attempts=4, ipv4_only=ipv4)
        except Exception as e:
            last = e
    assert last is not None
    raise last


def jscode2session(js_code: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """返回 (data_dict, error_message)。data 含 openid, session_key, unionid(可选)。"""
    appid, secret = wechat_appid(), wechat_secret()
    if not appid or not secret:
        return None, "未配置 WECHAT_APPID / WECHAT_APPSECRET"
    url = f"{_WX}/sns/jscode2session"
    try:
        r = _wx_request_get(
            url,
            {
                "appid": appid,
                "secret": secret,
                "js_code": js_code,
                "grant_type": "authorization_code",
            },
        )
        data = r.json() if r.content else {}
    except Exception as e:
        hint = ""
        err_s = str(e).lower()
        if "ssl" in err_s or "eof" in err_s or "connection" in err_s:
            hint = (
                "（可设环境变量：HTMA_WX_TRUST_ENV=0 已默认禁用系统代理；"
                "HTMA_WX_FORCE_IPV4=1 已默认开启仅 IPv4；"
                "若仍失败请检查服务器到 api.weixin.qq.com:443 出口、公司防火墙/代理。）"
            )
        return None, str(e) + hint
    if data.get("errcode") not in (None, 0):
        return None, data.get("errmsg") or str(data.get("errcode"))
    if not data.get("openid"):
        return None, "微信未返回 openid"
    return data, None


_access_token: str = ""
_access_token_deadline: float = 0.0


def get_access_token() -> Tuple[Optional[str], Optional[str]]:
    global _access_token, _access_token_deadline
    appid, secret = wechat_appid(), wechat_secret()
    if not appid or not secret:
        return None, "未配置 WECHAT_APPID / WECHAT_APPSECRET"
    now = time.time()
    if _access_token and now < _access_token_deadline - 120:
        return _access_token, None
    url = f"{_WX}/cgi-bin/token"
    try:
        r = _wx_request_get(
            url,
            {"grant_type": "client_credential", "appid": appid, "secret": secret},
        )
        data = r.json() if r.content else {}
    except Exception as e:
        return None, str(e)
    if data.get("errcode") not in (None, 0):
        return None, data.get("errmsg") or str(data.get("errcode"))
    tok = (data.get("access_token") or "").strip()
    if not tok:
        return None, "无 access_token"
    expires = int(data.get("expires_in") or 7200)
    _access_token = tok
    _access_token_deadline = now + max(300, expires)
    return tok, None


def get_phone_number_from_code(phone_code: str) -> Tuple[Optional[str], Optional[str]]:
    """新版 getPhoneNumber 返回的 code → 明文手机号。"""
    tok, err = get_access_token()
    if err:
        return None, err
    url = f"{_WX}/wxa/business/getuserphonenumber?access_token={tok}"
    try:
        r = _wx_request_post(url, {"code": phone_code})
        data = r.json() if r.content else {}
    except Exception as e:
        return None, str(e)
    if data.get("errcode") not in (None, 0):
        return None, data.get("errmsg") or str(data.get("errcode"))
    info = data.get("phone_info") or {}
    phone = (info.get("purePhoneNumber") or info.get("phoneNumber") or "").strip()
    if not phone:
        return None, "未解析到手机号"
    return phone, None
