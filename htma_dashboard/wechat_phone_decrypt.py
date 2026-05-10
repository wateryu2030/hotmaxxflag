# -*- coding: utf-8 -*-
"""旧版手机号解密：encryptedData + iv + session_key（AES-128-CBC）。"""
import base64
import json
from typing import Optional, Tuple

from Crypto.Cipher import AES


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    pad = data[-1]
    if pad > len(data) or pad < 1:
        return data
    return data[:-pad]


def decrypt_phone(encrypted_data_b64: str, iv_b64: str, session_key_b64: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        sk = base64.b64decode(session_key_b64)
        ed = base64.b64decode(encrypted_data_b64)
        iv = base64.b64decode(iv_b64)
        cipher = AES.new(sk, AES.MODE_CBC, iv)
        raw = _pkcs7_unpad(cipher.decrypt(ed))
        obj = json.loads(raw.decode("utf-8"))
        phone = (obj.get("purePhoneNumber") or obj.get("phoneNumber") or "").strip()
        if not phone:
            return None, "解密结果无手机号"
        return phone, None
    except Exception as e:
        return None, str(e)
