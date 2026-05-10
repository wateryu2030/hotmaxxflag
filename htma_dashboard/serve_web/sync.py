# -*- coding: utf-8 -*-
"""同步 API — serve_web/sync：平台商品同步、商品品类同步"""

from flask import Blueprint, jsonify, request
from datetime import datetime

from core.db import get_conn
from core.context import _effective_store_id
from import_logic import sync_products_table, sync_category_table

sync_bp = Blueprint("sync", __name__)


@sync_bp.route("/api/platform_products_sync", methods=["POST", "OPTIONS"])
def api_platform_products_sync():
    """同步平台商品到 t_htma_platform_products 表（按大类/中类/小类、规格、条码）"""
    if request.method == "OPTIONS":
        return "", 204
    try:
        from price_compare import sync_platform_products
        days = int((request.get_json(silent=True) or {}).get("days", 30))
        limit = int((request.get_json(silent=True) or {}).get("limit", 500))
        conn = get_conn()
        try:
            cnt = sync_platform_products(conn, store_id=_effective_store_id(), days=days, limit=limit)
            return jsonify({"success": True, "synced": cnt})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "synced": 0, "error": str(e)}), 500


@sync_bp.route("/api/sync_products_category", methods=["POST", "GET", "OPTIONS"])
def api_sync_products_category():
    """同步商品表、品类表（供导出与比价）。数据导入后自动调用，也可手动触发"""
    if request.method == "OPTIONS":
        return "", 204
    try:
        conn = get_conn()
        try:
            products_cnt = sync_products_table(conn, store_id=_effective_store_id())
            category_cnt = sync_category_table(conn, store_id=_effective_store_id())
            return jsonify({"success": True, "products_synced": products_cnt, "category_synced": category_cnt})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
