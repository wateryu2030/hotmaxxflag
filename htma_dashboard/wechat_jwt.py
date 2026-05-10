# -*- coding: utf-8 -*-
import time
from typing import Any, Dict, Optional

import jwt

from wechat_config import wechat_jwt_secret


def issue_token(user_id: int, openid: str, role: str, store_id: Optional[str], ttl_seconds: int = 604800) -> str:
    """默认 7 天。"""
    secret = wechat_jwt_secret()
    if not secret:
        raise RuntimeError("WECHAT_JWT_SECRET 未配置")
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "openid": openid,
        "role": role or "operator",
        "store_id": store_id or "",
        "iat": now,
        "exp": now + int(ttl_seconds),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    secret = wechat_jwt_secret()
    if not secret or not token:
        return None
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except Exception:
        return None
