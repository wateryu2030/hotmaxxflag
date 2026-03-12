# -*- coding: utf-8 -*-
"""
通用数据查询层（重构用）。
统一日期/品类/品牌筛选解析，以及趋势类查询的 profit -> sale 降级逻辑。
使用方式：在 app.py 中 from query_layer import date_condition, query_filters_from_request 后逐步替换 _date_condition / _query_filters。
"""
import os
from datetime import date, datetime, timedelta
from typing import Tuple, Optional

DEFAULT_DAYS = 30


def date_condition(
    period: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Tuple[str, tuple]:
    """
    返回 (date_cond, params) 用于 SQL。
    若 start_date/end_date 均提供则用自定义区间；period=custom 时仅用起止日期。
    与 app.py 中 _date_condition 行为一致，便于 1:1 替换。
    """
    if start_date and end_date:
        try:
            s = (
                datetime.strptime(start_date, "%Y-%m-%d").date()
                if isinstance(start_date, str)
                else start_date
            )
            e = (
                datetime.strptime(end_date, "%Y-%m-%d").date()
                if isinstance(end_date, str)
                else end_date
            )
            if s > e:
                s, e = e, s
            return "data_date BETWEEN %s AND %s", (s, e)
        except (ValueError, TypeError):
            pass
        return "data_date BETWEEN %s AND %s", (start_date, end_date)
    if period == "custom":
        days = int(os.environ.get("HTMA_DAYS", DEFAULT_DAYS))
        return (
            "data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL %s DAY) AND CURDATE()",
            (days,),
        )
    if period == "day":
        return "data_date = CURDATE()", ()
    if period == "week":
        return "data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND CURDATE()", ()
    if period == "month":
        return (
            "data_date >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01') AND data_date <= CURDATE()",
            (),
        )
    days = int(os.environ.get("HTMA_DAYS", DEFAULT_DAYS))
    return (
        "data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL %s DAY) AND CURDATE()",
        (days,),
    )


def parse_period_from_request():
    """从 request 读取 period/start_date/end_date。需在 Flask 请求上下文中调用。"""
    from flask import request
    period = request.args.get("period", "recent30")
    start_date = (request.args.get("start_date") or "").strip() or None
    end_date = (request.args.get("end_date") or "").strip() or None
    return period, start_date, end_date


def query_filters_from_request(include_sku: bool = False):
    """
    从 Flask request.args 解析筛选条件。
    返回 (date_cond, date_params, params, sale_category_cond, sku_cond)。
    params 中 store_id 占位为 None，调用方需填入 STORE_ID 后使用。
    与 app.py _query_filters 返回格式兼容。
    """
    from flask import request

    period, start_date, end_date = parse_period_from_request()
    category_large_code = (request.args.get("category_large_code") or "").strip()
    category_mid_code = (request.args.get("category_mid_code") or "").strip()
    category_small_code = (request.args.get("category_small_code") or "").strip()
    category_name = (request.args.get("category") or "").strip()
    brand_name = (request.args.get("brand") or "").strip()
    sku_code = (request.args.get("sku_code") or "").strip() if include_sku else ""

    date_cond, date_params = date_condition(period, start_date, end_date)
    sale_conds = []
    sale_params = []
    if category_name:
        sale_conds.append(
            " AND (COALESCE(TRIM(category_large), '') = %s OR COALESCE(TRIM(category_mid), '') = %s OR COALESCE(TRIM(category), '') = %s)"
        )
        sale_params.extend([category_name, category_name, category_name])
    if brand_name:
        sale_conds.append(" AND COALESCE(TRIM(brand_name), '') = %s")
        sale_params.append(brand_name)
    if category_large_code:
        sale_conds.append(
            " AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)"
        )
        sale_params.extend([category_large_code, category_large_code])
    if category_mid_code:
        sale_conds.append(
            " AND (COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)"
        )
        sale_params.extend([category_mid_code, category_mid_code])
    if category_small_code:
        sale_conds.append(
            " AND (COALESCE(TRIM(category_small_code), '') = %s OR COALESCE(TRIM(category_small), '') = %s OR COALESCE(TRIM(category), '') = %s)"
        )
        sale_params.extend([category_small_code, category_small_code, category_small_code])
    sale_category_cond = "".join(sale_conds)
    sku_cond = ""
    if sku_code:
        sku_cond = " AND sku_code = %s"
        sale_params.append(sku_code)
    params = (None,) + tuple(date_params) + tuple(sale_params)
    return date_cond, tuple(date_params), params, sale_category_cond, sku_cond


def query_filters_from_params(
    period: str = "recent30",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    category_large_code: Optional[str] = None,
    category_mid_code: Optional[str] = None,
    category_small_code: Optional[str] = None,
) -> Tuple[str, tuple, tuple, str, str]:
    """
    从显式参数解析筛选条件（不依赖 request）。
    返回 (date_cond, date_params, params, sale_category_cond, sku_cond)。
    params 首项为 None，调用方需替换为 STORE_ID。用于结构化报告等需传参调用的场景。
    支持与 query_filters_from_request 一致的 category_large_code / category_mid_code / category_small_code。
    """
    period = (period or "recent30").strip() or "recent30"
    start_date = (start_date or "").strip() or None
    end_date = (end_date or "").strip() or None
    category_name = (category or "").strip() or None
    brand_name = (brand or "").strip() or None
    clc = (category_large_code or "").strip() or None
    cmc = (category_mid_code or "").strip() or None
    csc = (category_small_code or "").strip() or None

    date_cond, date_params = date_condition(period, start_date, end_date)
    sale_conds = []
    sale_params = []
    if category_name:
        sale_conds.append(
            " AND (COALESCE(TRIM(category_large), '') = %s OR COALESCE(TRIM(category_mid), '') = %s OR COALESCE(TRIM(category), '') = %s)"
        )
        sale_params.extend([category_name, category_name, category_name])
    if brand_name:
        sale_conds.append(" AND COALESCE(TRIM(brand_name), '') = %s")
        sale_params.append(brand_name)
    if clc:
        sale_conds.append(
            " AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)"
        )
        sale_params.extend([clc, clc])
    if cmc:
        sale_conds.append(
            " AND (COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)"
        )
        sale_params.extend([cmc, cmc])
    if csc:
        sale_conds.append(
            " AND (COALESCE(TRIM(category_small_code), '') = %s OR COALESCE(TRIM(category_small), '') = %s OR COALESCE(TRIM(category), '') = %s)"
        )
        sale_params.extend([csc, csc, csc])
    sale_category_cond = "".join(sale_conds)
    params = (None,) + tuple(date_params) + tuple(sale_params)
    return date_cond, tuple(date_params), params, sale_category_cond, ""
