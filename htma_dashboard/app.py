#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
好特卖沈阳超级仓运营看板 - 独立版（不依赖 JimuReport）
直接读取 MySQL htma_dashboard，提供 API 与看板页面。
"""
import os
import sys
import urllib.parse
from datetime import date, timedelta, datetime

# 加载 .env（货盘比价、飞书登录等）；多路径、先 dotenv 再逐键解析，确保飞书登录能读到
_env_dir = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
_project_root = os.path.abspath(os.path.join(_env_dir, ".."))
_env_path = os.path.join(_project_root, ".env")
_ENV_KEYS = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "HTMA_PUBLIC_URL",
    "FLASK_SECRET_KEY",
    "FEISHU_WEBHOOK_URL",
    "FEISHU_AT_USER_ID",
    "FEISHU_AT_USER_NAME",
    "FEISHU_VERIFICATION_TOKEN",
    "FEISHU_ENCRYPT_KEY",
    "FEISHU_BOT_REPLY_MODE",
    "FEISHU_BOT_REPLY_PREFIX",
    "FEISHU_BOT_OPEN_ID",
    "FEISHU_BOT_DB_ALLOWED_OPEN_IDS",
    "FEISHU_BOT_MYSQL_USER",
    "FEISHU_BOT_MYSQL_PASSWORD",
    "FEISHU_BOT_DB_REQUIRE_ALLOWLIST",
)


def _load_env_from_file(path, force_keys=None):
    """从 path 读 .env，将 _ENV_KEYS 注入 os.environ。force_keys 若给出则强制覆盖这些键。"""
    if not path or not os.path.isfile(path):
        return
    force_set = set(force_keys or [])
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip().strip("\r\n").strip("\r")
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip().lstrip("\ufeff")  # BOM
                key = key.strip()
                val = val.strip().strip("'\"").strip()
                if key not in _ENV_KEYS:
                    continue
                if not val:
                    continue
                if key in force_set or not (os.environ.get(key) or "").strip():
                    os.environ[key] = val
    except Exception:
        pass


def _read_feishu_from_env_file(path):
    """从指定路径的 .env 文件读取飞书配置，返回 (app_id, app_secret)。"""
    out_id, out_secret = "", ""
    if not path or not os.path.isfile(path):
        return out_id, out_secret
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip().strip("\r\n").strip("\r")
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip().lstrip("\ufeff").strip()
                val = val.strip().strip("'\"").strip()
                if key == "FEISHU_APP_ID" and val:
                    out_id = val
                elif key == "FEISHU_APP_SECRET" and val:
                    out_secret = val
    except Exception:
        pass
    return out_id, out_secret


def _read_feishu_from_project_env():
    """从项目根 .env 强制读取飞书配置；多路径尝试（__file__ 与 getcwd）。"""
    cwd = os.getcwd()
    candidates = [
        _env_path,
        os.path.join(cwd, ".env"),
        os.path.abspath(os.path.join(cwd, "..", ".env")),
    ]
    for p in candidates:
        if not p:
            continue
        a, b = _read_feishu_from_env_file(p)
        if a and b:
            return a, b
    return "", ""


try:
    from dotenv import load_dotenv
    load_dotenv(_env_path)
except ImportError:
    pass
# 先强制从项目根 .env 注入飞书相关（覆盖空值），再按原逻辑补其他
_load_env_from_file(
    _env_path,
    force_keys=(
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_WEBHOOK_URL",
        "FEISHU_VERIFICATION_TOKEN",
        "FEISHU_ENCRYPT_KEY",
        "FEISHU_BOT_REPLY_MODE",
        "FEISHU_BOT_REPLY_PREFIX",
        "FEISHU_BOT_OPEN_ID",
        "FEISHU_BOT_DB_ALLOWED_OPEN_IDS",
        "FEISHU_BOT_MYSQL_USER",
        "FEISHU_BOT_MYSQL_PASSWORD",
        "FEISHU_BOT_DB_REQUIRE_ALLOWLIST",
    ),
)
for _p in (_env_path, os.path.join(os.getcwd(), ".env"), os.path.abspath(os.path.join(os.getcwd(), "..", ".env"))):
    _load_env_from_file(_p)
import csv
import io
import subprocess
import tempfile
import threading
import time
import pymysql
from db_config import DB_CONFIG, get_conn
from flask import Flask, Response, jsonify, send_from_directory, request, session, redirect
from werkzeug.utils import secure_filename

from import_logic import import_sale_daily, import_sale_summary, import_stock, import_category, import_profit, import_tax_burden, refresh_profit, refresh_category_from_sale, sync_products_table, sync_category_table, preview_sale_excel, import_labor_cost, import_labor_cost_from_image, refresh_labor_cost_analysis, import_product_master, _ensure_product_master_distribution_mode, _read_excel_safe
from analytics import build_insights, build_enhanced_insights, build_structured_report, build_marketing_report, category_rank_data, advanced_search_consumer_insight
from channel_hongbeilou import (
    query_catalog_rows,
    EXPORT_SIMPLE_COLUMNS,
    table_exists,
    build_selection_logic_meta,
    rows_to_simple_export,
)
from query_layer import date_condition as _ql_date_condition, query_filters_from_request as _ql_query_filters, query_filters_from_params as _ql_query_filters_from_params

# 简单内存缓存：key -> (value, expire_at)，用于 date_range / kpi 等只读接口
_api_cache = {}
_CACHE_TTL = 60  # 秒

def _cache_get(key):
    if key not in _api_cache:
        return None
    val, expire = _api_cache[key]
    if time.time() > expire:
        del _api_cache[key]
        return None
    return val

def _cache_set(key, value, ttl=None):
    _api_cache[key] = (value, time.time() + (ttl or _CACHE_TTL))


def _auth_enabled():
    """是否启用登录（配置了飞书应用则启用）；优先以 app.config 为准，避免进程未继承 shell 变量"""
    from page_auth import _auth_enabled as _pa_auth_enabled
    return _pa_auth_enabled()


def _parse_id_list(env_name):
    """从环境变量解析以逗号/分号分隔的 open_id / user_id 列表"""
    from page_auth import _parse_id_list as _pa_parse_id_list
    return _pa_parse_id_list(env_name)


def _has_module_access(module, user_id=None):
    """基于环境变量控制模块访问权限。"""
    from page_auth import _has_module_access as _pa_has_module_access
    return _pa_has_module_access(module, user_id)


def _is_logged_in():
    """当前 session 是否有已登录用户"""
    from page_auth import _is_logged_in as _pa_is_logged_in
    return _pa_is_logged_in()


from app_factory import create_app

app = create_app()


# MySQL 配置由 db_config 统一从 .env 读取
STORE_ID = "沈阳超级仓"
DEFAULT_DAYS = 30
FEISHU_WEBHOOK = os.environ.get(
    "FEISHU_WEBHOOK_URL",
    "https://open.feishu.cn/open-apis/bot/v2/hook/1b21bad3-22cb-4d9d-8f38-32526bd69d49",
)


def _notify_feishu(text):
    """发送飞书通知（异步，不阻塞主流程）"""
    if not FEISHU_WEBHOOK or not text:
        return
    try:
        import urllib.request
        import json
        req = urllib.request.Request(
            FEISHU_WEBHOOK,
            data=json.dumps({"msg_type": "text", "content": {"text": text}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # 静默失败，不影响导入




# ---------- 税务分析（发票比对、税负测算）API ----------
def _tax_analysis_forbidden():
    return jsonify({"error": "无权限"}), 403


def _parse_invoice_excel(excel_path, store_id="沈阳超级仓"):
    """解析发票 Excel（兼容 12 月/1 月两种表头），返回 [(category_small_code, category_small_name, tax_class_code, tax_rate, sale_qty, invoice_amount), ...]。
    调用方传入 period_month。"""
    import pandas as pd
    xl = pd.ExcelFile(excel_path)
    sheets = [s for s in xl.sheet_names if s]
    if not sheets:
        raise ValueError("Excel 中无有效 Sheet")
    ext = os.path.splitext(excel_path)[1].lower()
    engine = "openpyxl" if ext == ".xlsx" else "xlrd"
    out = []
    for sheet in sheets:
        try:
            df = pd.read_excel(excel_path, sheet_name=sheet, header=None, engine=engine)
        except Exception:
            df = pd.read_excel(excel_path, sheet_name=sheet, header=None)
        if df.shape[0] < 2 or df.shape[1] < 4:
            continue
        # 找表头行：包含「三级类别名称」或「三级类别编码」
        header_row = None
        for i in range(min(6, len(df))):
            row = df.iloc[i]
            vals = [str(x).strip() if pd.notna(x) else "" for x in row]
            if "三级类别名称" in vals or "求和项:开票金额" in vals:
                header_row = i
                break
        if header_row is None:
            continue
        headers = [str(x).strip() if pd.notna(x) else "" for x in df.iloc[header_row]]
        col_name = None
        col_code = None
        col_tax_code = None
        col_rate = None
        col_qty = None
        col_amount = None
        for j, h in enumerate(headers):
            if h == "三级类别名称":
                col_name = j
            elif h == "三级类别编码":
                col_code = j
            elif "税收分类编码" in h or h == "税收分类编码":
                col_tax_code = j
            elif h == "税率":
                col_rate = j
            elif "求和项:销售数量" in h or h == "销售数量":
                col_qty = j
            elif "求和项:开票金额" in h or h == "开票金额":
                col_amount = j
        if col_name is None or col_amount is None:
            continue
        if col_rate is None:
            col_rate = col_tax_code  # 可能同一列
        skip_names = ("", "总计", "合计", "小计", "汇总", "价税合计", "共", "第", "第1页", "第2页")
        for i in range(header_row + 1, len(df)):
            row = df.iloc[i]
            name = (row.iloc[col_name] if col_name is not None else None)
            if pd.isna(name):
                continue
            name = str(name).strip()
            if not name:
                continue
            if name in skip_names or any(name.startswith(s) for s in ("共", "第")) or "价税合计" in name:
                continue
            code = None
            if col_code is not None and col_code < len(row):
                v = row.iloc[col_code]
                if pd.notna(v):
                    try:
                        code = str(int(float(v))) if isinstance(v, (int, float)) else str(v).strip()
                    except Exception:
                        code = str(v).strip()
            tax_code = None
            if col_tax_code is not None and col_tax_code < len(row):
                v = row.iloc[col_tax_code]
                if pd.notna(v):
                    try:
                        tax_code = str(int(float(v)))
                    except Exception:
                        tax_code = str(v).strip() if v else None
            try:
                rate = float(row.iloc[col_rate]) if col_rate is not None and pd.notna(row.iloc[col_rate]) else 0.13
            except Exception:
                rate = 0.13
            try:
                qty = float(row.iloc[col_qty]) if col_qty is not None and pd.notna(row.iloc[col_qty]) else 0
            except Exception:
                qty = 0
            try:
                amt = float(row.iloc[col_amount])
            except Exception:
                amt = 0
            if amt == 0 and qty == 0:
                continue
            out.append({
                "category_small_code": code,
                "category_small_name": name,
                "tax_class_code": tax_code,
                "tax_rate": rate,
                "sale_qty": round(qty, 2),
                "invoice_amount": round(amt, 2),
            })
        if out:
            break
    # 按三级类别名称去重：同名称多行合并为一行（数量、金额相加，税率/编码取第一条）
    seen = {}
    for r in out:
        key = (r["category_small_name"] or "").strip()
        if not key:
            continue
        if key not in seen:
            seen[key] = dict(r)
        else:
            seen[key]["sale_qty"] = round(seen[key]["sale_qty"] + r["sale_qty"], 2)
            seen[key]["invoice_amount"] = round(seen[key]["invoice_amount"] + r["invoice_amount"], 2)
    return list(seen.values())





















# ---------- 收益评估（加盟商分账）API ----------











def _date_condition(period, start_date=None, end_date=None):
    """返回 (date_cond, params) 用于 SQL。委托 query_layer 实现，保持兼容。"""
    return _ql_date_condition(period, start_date, end_date)


def _period_over_period_ranges(period, start_date_str=None, end_date_str=None):
    """根据 KPI 周期返回本期与上期的日期范围及标签，用于环比分析。
    返回 (curr_start, curr_end, prev_start, prev_end, curr_label, prev_label)，均为 date 或 None。"""
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
        # 本周 = 过去7天；上期 = 再前7天（与 _date_condition 一致）
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
    days = int(os.environ.get("HTMA_DAYS", DEFAULT_DAYS))
    curr_end = today
    curr_start = today - timedelta(days=days - 1)
    prev_end = curr_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return curr_start, curr_end, prev_start, prev_end, f"{curr_start}~{curr_end}", f"{prev_start}~{prev_end}"


def _query_filters(include_sku=False):
    """从 request 解析筛选条件。返回 (date_cond, date_params, params, sale_category_cond, sku_cond)。委托 query_layer 实现，保持兼容。"""
    date_cond, date_params, params, sale_category_cond, sku_cond = _ql_query_filters(include_sku=include_sku)
    # query_layer 返回的 params 首项为占位 None，替换为 STORE_ID
    if params and params[0] is None:
        params = (STORE_ID,) + tuple(params[1:])
    return date_cond, date_params, params, sale_category_cond, sku_cond


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


def api_sales_trend(granularity):
    """按日/周/月聚合销售额与毛利趋势。与 KPI 一致，均从 t_htma_sale 聚合。"""
    date_cond, date_params, params, category_cond, sku_cond = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if granularity == "day":
                cur.execute(f"""
                    SELECT data_date AS x_date,
                           COALESCE(SUM(sale_amount), 0) AS sale_amount,
                           COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                    GROUP BY data_date ORDER BY data_date
                """, params)
                rows = cur.fetchall()
                out = [_format_trend_row(r, "day") for r in rows]
            elif granularity == "week":
                cur.execute(f"""
                    SELECT MIN(data_date) AS week_start,
                           CONCAT(YEAR(MIN(data_date)), '-W', LPAD(WEEK(MIN(data_date), 3), 2, '0')) AS x_date,
                           COALESCE(SUM(sale_amount), 0) AS sale_amount,
                           COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                    GROUP BY YEAR(data_date), WEEK(data_date, 3)
                    ORDER BY MIN(data_date)
                """, params)
                rows = cur.fetchall()
                out = [_format_trend_row(r, "week") for r in rows]
            else:  # month
                cur.execute(f"""
                    SELECT DATE_FORMAT(MIN(data_date), '%%Y-%%m') AS x_date,
                           COALESCE(SUM(sale_amount), 0) AS sale_amount,
                           COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS profit_amount
                    FROM t_htma_sale
                    WHERE store_id = %s AND {date_cond}{category_cond}{sku_cond}
                    GROUP BY YEAR(data_date), MONTH(data_date)
                    ORDER BY MIN(data_date)
                """, params)
                rows = cur.fetchall()
                out = [_format_trend_row(r, "month") for r in rows]
            data_source = "sale"
        if not out:
            return jsonify({
                "data": [],
                "dates": [],
                "sales": [],
                "gross_profit": [],
                "data_source": None,
                "empty_hint": "所选条件下无销售数据，请调整周期或品类筛选后再试。",
            })
        dates = [r["x_date"] for r in out]
        sales = [r["sale_amount"] for r in out]
        gross_profit_list = [r["profit_amount"] for r in out]
        return jsonify({
            "data": out,
            "dates": dates,
            "sales": sales,
            "gross_profit": gross_profit_list,
            "data_source": data_source,
            "empty_hint": None,
        })
    except Exception as e:
        return jsonify({"error": str(e), "data": [], "data_source": None, "empty_hint": "请求异常，请稍后重试。"}), 500
    finally:
        conn.close()


def _format_trend_row(r, granularity):
    """安全格式化趋势行，避免日期/空值导致的异常"""
    x_date = r.get("x_date")
    if x_date is not None and hasattr(x_date, "strftime"):
        x_str = x_date.strftime("%Y-%m-%d" if granularity == "day" else "%Y-%m")
    else:
        x_str = str(x_date) if x_date else ""
    week_start = r.get("week_start")
    if week_start is not None and hasattr(week_start, "strftime"):
        ws_str = week_start.strftime("%Y-%m-%d")
    else:
        ws_str = str(week_start) if week_start else ""
    return {
        "x_date": x_str,
        "week_start": ws_str,
        "sale_amount": float(r.get("sale_amount") or 0),
        "profit_amount": float(r.get("profit_amount") or 0),
    }




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


def _price_band_unit_cond(band):
    """根据价格带返回 SQL 条件：件单价 (sale_amount/sale_qty) 落在该区间。返回 (cond_sql,)."""
    band = (band or "").strip()
    if band == "0":
        return (" AND COALESCE(sale_qty, 0) <= 0 ",)
    if band == "0-10":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) < 10 ",)
    if band == "10-30":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) >= 10 AND (sale_amount / sale_qty) < 30 ",)
    if band == "30-50":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) >= 30 AND (sale_amount / sale_qty) < 50 ",)
    if band == "50-100":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) >= 50 AND (sale_amount / sale_qty) < 100 ",)
    if band == "100+":
        return (" AND sale_qty > 0 AND sale_amount > 0 AND (sale_amount / sale_qty) >= 100 ",)
    return (" AND 1=0 ",)


def _advanced_search_range_days(period, start_date, end_date):
    """根据 period/start_date/end_date 计算查询区间天数，用于周转天数计算。"""
    if start_date and end_date:
        try:
            s = datetime.strptime(start_date, "%Y-%m-%d").date() if isinstance(start_date, str) else start_date
            e = datetime.strptime(end_date, "%Y-%m-%d").date() if isinstance(end_date, str) else end_date
            if s > e:
                s, e = e, s
            return max(1, (e - s).days + 1)
        except (ValueError, TypeError):
            pass
    if period == "day":
        return 1
    if period == "week":
        return 7
    if period == "month":
        today = date.today()
        try:
            from calendar import monthrange
            return monthrange(today.year, today.month)[1]
        except Exception:
            return 30
    return int(os.environ.get("HTMA_DAYS", DEFAULT_DAYS))


def _enrich_advanced_search_with_price_compare(conn, items):
    """为高级查询结果每项附加最新比价信息（从 t_price_compare 取各平台最新一条）。"""
    if not items:
        return items
    sku_list = list({x.get("sku_code") for x in items if x.get("sku_code")})
    if not sku_list:
        return items
    try:
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(sku_list))
        cur.execute(
            """
            SELECT sku_code, platform, price, original_price, promotion_info, good_rate, capture_date
            FROM t_price_compare
            WHERE sku_code IN (""" + placeholders + """)
            ORDER BY capture_date DESC
            """,
            sku_list,
        )
        rows = cur.fetchall()
        cur.close()
        by_sku = {}
        for r in rows:
            sku = r.get("sku_code")
            if sku not in by_sku:
                by_sku[sku] = {}
            platform = r.get("platform") or ""
            if platform and platform not in by_sku[sku]:
                cap = r.get("capture_date")
                by_sku[sku][platform] = {
                    "price": float(r["price"]) if r.get("price") is not None else None,
                    "original_price": float(r["original_price"]) if r.get("original_price") is not None else None,
                    "promotion": (r.get("promotion_info") or "")[:200],
                    "good_rate": float(r["good_rate"]) if r.get("good_rate") is not None else None,
                    "capture_date": cap.strftime("%Y-%m-%d %H:%M") if cap else None,
                }
        for x in items:
            x["price_compare"] = by_sku.get(x.get("sku_code")) or {}
        return items
    except Exception:
        for x in items:
            x["price_compare"] = {}
        return items


def _structured_report_to_html(report):
    """将结构化报告 dict 转为可读 HTML，用于导出下载。"""
    if not report:
        return "<!DOCTYPE html><html><head><meta charset=\"utf-8\"/><title>报告</title></head><body><p>无数据</p></body></html>"
    import html as html_module
    parts = ["<!DOCTYPE html><html><head><meta charset=\"utf-8\"/>", "<title>结构化分析报告</title>", "<style>body{font-family:sans-serif;margin:20px;background:#0f172a;color:#e2e8f0;} h2{margin-top:24px;color:#38bdf8;} table{border-collapse:collapse;} th,td{border:1px solid #334155;padding:6px 10px;text-align:left;} th{background:#1e293b;} .section{margin-bottom:20px;}</style>", "</head><body>"]
    summary = report.get("summary") or {}
    kpi = summary.get("kpi") or {}
    parts.append("<h2>1. 总览</h2><div class=\"section\">")
    parts.append("<p>销售额: %s | 毛利: %s | 毛利率: %s%% | 动销SKU: %s</p>" % (kpi.get("total_sale"), kpi.get("total_profit"), kpi.get("margin_pct"), kpi.get("sku_sold")))
    if summary.get("conclusion"):
        parts.append("<p>%s</p>" % html_module.escape(summary["conclusion"][:500]))
    parts.append("</div>")
    cat = report.get("category_structure") or {}
    if cat.get("top_sales") or cat.get("matrix"):
        parts.append("<h2>2. 品类结构</h2><div class=\"section\">")
        for row in (cat.get("top_sales") or cat.get("matrix") or [])[:15]:
            c = row.get("category") or row.get("cat") or "-"
            s = row.get("sale_amount") or row.get("sale") or 0
            p = row.get("profit") or 0
            parts.append("<p>%s — 销售: %s 毛利: %s</p>" % (html_module.escape(str(c)), s, p))
        parts.append("</div>")
    drill = report.get("drill_section") or {}
    if drill.get("brands") or drill.get("styles") or drill.get("skus"):
        parts.append("<h2>3. 下钻摘要</h2><div class=\"section\">")
        parts.append("<p>类型: %s</p>" % html_module.escape(drill.get("type", "")))
        for b in (drill.get("brands") or [])[:10]:
            parts.append("<p>品牌: %s 销售: %s</p>" % (html_module.escape(str(b.get("brand"))), b.get("sale_amount")))
        for s in (drill.get("styles") or [])[:10]:
            parts.append("<p>款式: %s 销售: %s</p>" % (html_module.escape(str(s.get("product_name"))), s.get("sale_amount")))
        for s in (drill.get("skus") or [])[:15]:
            parts.append("<p>货号: %s 销售: %s</p>" % (html_module.escape(str(s.get("sku_code"))), s.get("sale_amount")))
        parts.append("</div>")
    issues = report.get("issues") or {}
    rg = issues.get("return_gift") or {}
    if rg.get("return_rate") is not None or rg.get("return_by_cat"):
        parts.append("<h2>4. 问题与行动</h2><div class=\"section\">")
        parts.append("<p>退货率: %s%%</p>" % (rg.get("return_rate") or 0))
        parts.append("</div>")
    if report.get("market_expansion"):
        parts.append("<h2>5. 市场拓展</h2><div class=\"section\"><pre>%s</pre></div>" % html_module.escape((report["market_expansion"] or "")[:2000]))
    parts.append("</body></html>")
    return "".join(parts)


def _ensure_report_log_table(conn):
    """确保 t_htma_report_log 表存在"""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS t_htma_report_log (
              id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
              report_date DATE NOT NULL,
              report_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              store_id VARCHAR(32) DEFAULT '沈阳超级仓',
              report_content TEXT NOT NULL,
              feishu_at_user_id VARCHAR(64) DEFAULT NULL,
              feishu_at_user_name VARCHAR(32) DEFAULT NULL,
              send_status TINYINT DEFAULT 1,
              send_error VARCHAR(512) DEFAULT NULL,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              KEY idx_report_date (report_date),
              KEY idx_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.commit()
        cur.close()
    except Exception:
        pass


def _save_report_log(conn, report, send_ok, send_err=None):
    """将报告保存到 t_htma_report_log"""
    try:
        _ensure_report_log_table(conn)
        from feishu_util import FEISHU_AT_USER_ID, FEISHU_AT_USER_NAME
        uid = (FEISHU_AT_USER_ID or "").strip()
        if uid and not uid.startswith("ou_"):
            uid = f"ou_{uid}"
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO t_htma_report_log
               (report_date, report_time, store_id, report_content, feishu_at_user_id, feishu_at_user_name, send_status, send_error)
               VALUES (CURDATE(), NOW(), %s, %s, %s, %s, %s, %s)""",
            (STORE_ID, report, uid or None, FEISHU_AT_USER_NAME, 1 if send_ok else 0, (send_err or "")[:512]),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        pass  # 表可能未创建，静默失败


def _platforms_returned_from_items(items):
    """从比价结果 items 中汇总本次返回的平台名（用于前端展示）。"""
    seen = set()
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        plat = it.get("platform") or ""
        if not plat or plat == "模拟":
            continue
        for part in plat.replace("，", "、").split("、"):
            part = part.strip()
            if ":" in part:
                name = part.split(":", 1)[0].strip()
            else:
                name = part
            if name and len(name) < 20:
                seen.add(name)
        if it.get("jd_min_price") is not None:
            seen.add("京东")
        if it.get("taobao_min_price") is not None:
            seen.add("淘宝")
    return sorted(seen)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5002"))
    app.run(host="0.0.0.0", port=port, debug=False)
