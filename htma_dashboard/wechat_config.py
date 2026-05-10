# -*- coding: utf-8 -*-
"""微信小程序配置：仅从环境变量读取，勿把密钥写入仓库。"""
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ENV = os.path.join(_ROOT, ".env")
try:
    from dotenv import load_dotenv
    load_dotenv(_ENV)
    load_dotenv()
except ImportError:
    pass


def wechat_appid():
    return (os.environ.get("WECHAT_APPID") or os.environ.get("WECHAT_MINI_APPID") or "").strip()


def wechat_secret():
    return (os.environ.get("WECHAT_APPSECRET") or os.environ.get("WECHAT_SECRET") or "").strip()


def wechat_jwt_secret():
    return (os.environ.get("WECHAT_JWT_SECRET") or "").strip()


def wechat_mini_enabled():
    """为 1/true 时，/api/mobile/* 必须携带有效 JWT（测试可设 HTMA_SKIP_MOBILE_JWT=1）。"""
    v = (os.environ.get("WECHAT_MINI_ENABLED") or "").strip().lower()
    return v in ("1", "true", "yes")


def skip_mobile_jwt():
    return (os.environ.get("HTMA_SKIP_MOBILE_JWT") or "").strip().lower() in ("1", "true", "yes")


def wx_trust_env():
    """仅当 HTMA_WX_TRUST_ENV=1 时，requests 才使用系统代理。默认 0=直连（避免抓包/代理致微信 API SSL EOF）。"""
    v = (os.environ.get("HTMA_WX_TRUST_ENV") or "0").strip().lower()
    return v in ("1", "true", "yes")


def wx_force_ipv4():
    """为 1（默认）时，解析 api.weixin.qq.com 仅走 IPv4，避免部分双栈网络 TLS 半连接。"""
    v = (os.environ.get("HTMA_WX_FORCE_IPV4") or "1").strip().lower()
    return v not in ("0", "false", "no")
