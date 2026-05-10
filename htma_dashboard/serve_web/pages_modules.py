# -*- coding: utf-8 -*-
"""带模块权限的静态 HTML 页面（导入、分账、税务、红背篓、商品主档）。"""

import urllib.parse

from flask import Blueprint, Response, current_app, redirect, request, send_from_directory

from page_auth import _auth_enabled, _has_module_access, _is_logged_in

pages_modules_bp = Blueprint("pages_modules", __name__)


@pages_modules_bp.route("/import")
def import_page():
    # 仅登录且拥有导入权限的用户可访问
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + (urllib.parse.quote(request.url) if request.url else "/"))
    if _auth_enabled() and not _has_module_access("import"):
        return Response("您无权访问数据导入模块，请联系管理员。", status=403)
    return send_from_directory(current_app.static_folder, "import.html")


@pages_modules_bp.route("/profit_share")
def profit_share_page():
    """收益评估（加盟商分账）页面，仅财务权限可访问"""
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + (urllib.parse.quote(request.url) if request.url else "/"))
    if _auth_enabled() and not _has_module_access("profit_share"):
        return Response("您无权访问收益评估模块，请联系管理员。", status=403)
    return send_from_directory(current_app.static_folder, "profit_share.html")


@pages_modules_bp.route("/tax_analysis")
def tax_analysis_page():
    """税务分析（发票比对、税负测算）页面，仅指定人员可访问"""
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + (urllib.parse.quote(request.url) if request.url else "/"))
    if _auth_enabled() and not _has_module_access("tax_analysis"):
        return Response("您无权访问税务分析模块，请联系管理员。", status=403)
    return send_from_directory(current_app.static_folder, "tax_analysis.html")


@pages_modules_bp.route("/hongbeilou")
def hongbeilou_page():
    """供销社「红背篓」选品：按品类筛选并导出 CSV（需 import 权限）"""
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + (urllib.parse.quote(request.url) if request.url else "/"))
    if _auth_enabled() and not _has_module_access("import"):
        return Response("您无权访问该模块，请联系管理员。", status=403)
    return send_from_directory(current_app.static_folder, "hongbeilou.html")


@pages_modules_bp.route("/product_master")
def page_product_master():
    """分店商品档案页：深度分析看板（KPI、状态/品类/品牌/价格带/经销/供应商/属性/数据质量），数据由 /api/product_master_analysis 提供。"""
    if _auth_enabled() and (not _is_logged_in() or not _has_module_access("product_master")):
        return Response("您无权访问分店商品档案模块，请联系管理员。", status=403)
    return send_from_directory(
        current_app.static_folder,
        "product_master.html",
        mimetype="text/html; charset=utf-8",
    )
