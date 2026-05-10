# -*- coding: utf-8 -*-
"""
上下文工具：门店 ID 解析、查询过滤条件、品类条件等。
"""
import os
from flask import request, session


def _effective_store_id():
    """
    网页端经营数据使用的门店 ID。
    若飞书登录用户在 t_htma_wechat_user 中已绑定同一 feishu_open_id 且配置了 store_id，
    则与小程序 JWT 单店口径一致；否则为 HTMA_STORE_ID / 默认门店。
    """
    base = (os.environ.get("HTMA_STORE_ID") or "沈阳超级仓").strip() or "沈阳超级仓"
    # 延迟导入 app 模块中的函数（避免循环导入）
    from app import _auth_enabled, _is_logged_in

    if not _auth_enabled() or not _is_logged_in():
        return base
    oid = (session.get("open_id") or session.get("user_id") or "").strip()
    if not oid:
        return base
    if session.get("_feishu_bind_cache_oid") == oid and session.get("_feishu_bind_done"):
        sid = (session.get("web_bound_store_id") or "").strip()
        return sid if sid else base
    session["_feishu_bind_cache_oid"] = oid
    session["_feishu_bind_done"] = True
    try:
        from wechat_user_repo import get_by_feishu_open_id
        row = get_by_feishu_open_id(oid)
        if row:
            w = (row.get("store_id") or "").strip()
            if w:
                session["web_bound_store_id"] = w
                return w
    except Exception:
        pass
    session["web_bound_store_id"] = ""
    return base


def _store_filter_expr(store_id_field="store_id"):
    """返回 (SQL 条件, (store_id,)) 用于门店过滤。"""
    sid = _effective_store_id()
    return f"{store_id_field} = %s", (sid,)


def _query_filters(include_sku=False):
    """从 request 解析筛选条件。返回 (date_cond, date_params, params, sale_category_cond, sku_cond)。
    委托 query_layer 实现，保持兼容。"""
    from query_layer import date_condition as _ql_date_condition, query_filters_from_request as _ql_query_filters

    date_cond, date_params, params, sale_category_cond, sku_cond = _ql_query_filters(include_sku=include_sku)
    # query_layer 返回的 params 首项为占位 None，替换为当前用户有效门店（含小程序绑定店）
    if params and params[0] is None:
        params = (_effective_store_id(),) + tuple(params[1:])
    return date_cond, date_params, params, sale_category_cond, sku_cond


def _date_period_args():
    """从 request 解析日期范围参数，返回 (start_date, end_date, period_type)。"""
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    period = request.args.get("period", "").strip()
    return start_date, end_date, period


def _profit_category_cond_and_params(date_cond, date_params_tuple):
    """返回用于 t_htma_profit 的 category 条件与参数。支持编码或名称匹配（级联选择器可能传名称）"""
    category_large_code = request.args.get("category_large_code", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip()
    category_small_code = request.args.get("category_small_code", "").strip()
    if not (category_large_code or category_mid_code or category_small_code):
        return "", ()
    conds, params = [], []
    if category_large_code:
        conds.append("(COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)")
        params.extend([category_large_code, category_large_code])
    if category_mid_code:
        conds.append("(COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)")
        params.extend([category_mid_code, category_mid_code])
    if category_small_code:
        conds.append("(COALESCE(TRIM(category_small_code), '') = %s OR COALESCE(TRIM(category_small), '') = %s OR COALESCE(TRIM(category), '') = %s)")
        params.extend([category_small_code, category_small_code, category_small_code])
    return " AND " + " AND ".join(conds), tuple(params)


def _inv_category_cond_and_params():
    """低库存：通过 sku 关联 sale 表获取品类层级，支持 category_large/mid/small 筛选"""
    category_large_code = request.args.get("category_large_code", "").strip()
    category_mid_code = request.args.get("category_mid_code", "").strip()
    category_small_code = request.args.get("category_small_code", "").strip()
    if not (category_large_code or category_mid_code or category_small_code):
        return "", (), False
    conds, params = [], []
    if category_large_code:
        conds.append("(COALESCE(TRIM(s.category_large_code), '') = %s OR COALESCE(TRIM(s.category_large), '') = %s)")
        params.extend([category_large_code, category_large_code])
    if category_mid_code:
        conds.append("(COALESCE(TRIM(s.category_mid_code), '') = %s OR COALESCE(TRIM(s.category_mid), '') = %s)")
        params.extend([category_mid_code, category_mid_code])
    if category_small_code:
        conds.append("(COALESCE(TRIM(s.category_small_code), '') = %s OR COALESCE(TRIM(s.category_small), '') = %s OR COALESCE(TRIM(s.category), '') = %s)")
        params.extend([category_small_code, category_small_code, category_small_code])
    return " AND " + " AND ".join(conds), tuple(params), True


# ── Phase 5 前置：周期工具 ──
def date_period_condition(period, start_date=None, end_date=None):
    """返回 (date_cond, params) 用于 SQL。委托 query_layer 实现。"""
    try:
        from query_layer import date_condition as _ql_date_condition
        return _ql_date_condition(period, start_date, end_date)
    except Exception:
        return "1=1", []


def period_over_period_ranges(period, start_date_str=None, end_date_str=None):
    """根据 KPI 周期返回本期与上期的日期范围及标签，用于环比分析。
    返回 (curr_start, curr_end, prev_start, prev_end, curr_label, prev_label)，均为 date 或 None。"""
    from datetime import date, datetime, timedelta
    today = date.today()
    if start_date_str and end_date_str:
        try:
            curr_end = datetime.strptime(end_date_str, "%Y-%m-%d").date() if isinstance(end_date_str, str) else end_date_str
            curr_start = datetime.strptime(start_date_str, "%Y-%m-%d").date() if isinstance(start_date_str, str) else start_date_str
        except Exception:
            curr_start = curr_end = today
        length = (curr_end - curr_start).days + 1
        prev_end = curr_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=length - 1)
        return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"
    if period == "day":
        return today, today, today - timedelta(days=1), today - timedelta(days=1), str(today), str(today - timedelta(days=1))
    if period == "week":
        curr_end = today
        curr_start = today - timedelta(days=6)
        prev_end = curr_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=6)
        return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"
    if period == "month":
        curr_start = today.replace(day=1)
        curr_end = today
        prev_end = curr_start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"
    # recent30 或默认
    days = int(os.environ.get("HTMA_DAYS", "30"))
    curr_end = today
    curr_start = today - timedelta(days=days - 1)
    prev_end = curr_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"
