# -*- coding: utf-8 -*-
"""公共与登录相关页面（根路径、登录、审批、占位路径）。"""

import urllib.parse

from flask import Blueprint, current_app, redirect, request, send_from_directory

from page_auth import _auth_enabled, _is_logged_in, _is_super_admin

pages_core_bp = Blueprint("pages_core", __name__)


@pages_core_bp.route("/")
def index():
    """根路径：未登录展示登录页，已登录展示运营看板（登录前置，必须登录后才能看详细数据）"""
    if not _is_logged_in():
        return send_from_directory(current_app.static_folder, "login.html")
    resp = send_from_directory(current_app.static_folder, "index.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@pages_core_bp.route("/login")
def login_page():
    """登录页：已登录则跳转到看板首页；未登录则展示飞书/企微扫码"""
    if _is_logged_in():
        next_url = request.args.get("next", "").strip()
        return redirect(next_url if next_url.startswith("/") and not next_url.startswith("//") else "/")
    return send_from_directory(current_app.static_folder, "login.html")


@pages_core_bp.route("/pending")
def pending_page():
    """企业外用户提交申请后的等待页"""
    return send_from_directory(current_app.static_folder, "pending.html")


@pages_core_bp.route("/approval")
def approval_page():
    """访问审批页（仅超级管理员余为军可见）"""
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + urllib.parse.quote(request.url or "/approval"))
    if not _is_super_admin():
        return redirect("/login?error=" + urllib.parse.quote("仅超级管理员可访问审批页"))
    return send_from_directory(current_app.static_folder, "approval.html")


@pages_core_bp.route("/admin")
def admin_reminder_page():
    """超级管理员专用提醒页：待审批数量与快捷入口"""
    if _auth_enabled() and not _is_logged_in():
        return redirect("/login?next=" + urllib.parse.quote(request.url or "/admin"))
    if not _is_super_admin():
        return redirect("/login?error=" + urllib.parse.quote("仅超级管理员可访问"))
    return send_from_directory(current_app.static_folder, "admin.html")


@pages_core_bp.route("/undefined")
def catch_undefined():
    """拦截 href=undefined 等错误请求"""
    return "", 204


@pages_core_bp.route("/.well-known/<path:_>")
def catch_well_known(_):
    """拦截 Chrome 扩展等对 .well-known 的请求"""
    return "", 204
