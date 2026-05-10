# -*- coding: utf-8 -*-
"""小程序 API 统一 JSON：{ code, data, msg }，code=0 成功。"""
from flask import jsonify


def mobile_ok(data=None, msg=""):
    return jsonify({"code": 0, "data": data if data is not None else {}, "msg": msg or ""})


def mobile_err(msg, code=1, http=400):
    return jsonify({"code": code, "data": {}, "msg": msg or ""}), http
