# -*- coding: utf-8 -*-
"""经营分析扩展：overview / heatmap / trend_advanced / contribution 等；有 t_htma_sale 时与 Web 看板 KPI 同源走明细聚合。"""
from __future__ import annotations

import logging
import os
import secrets
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from db_config import get_conn
from flask import Response, request
from extensions import mobile_cached
from labor_routes import _labor_analysis_by_category, _labor_analysis_overview
from mobile_json import mobile_err, mobile_ok
from wechat_mobile_guard import mobile_store_sql_prefix

from analytics_utils import (  # noqa: E402
    compute_large_category_insights,
    fetch_category_large_sales_aggregates,
    merge_category_large_sales_mom_attribution,
)

from mobile_sale_aggregates import (  # noqa: E402
    fetch_category_share_rows,
    fetch_contribution_rows,
    fetch_day_series_limited,
    fetch_heatmap_month_rows,
    fetch_insights_daily_large_rows,
    fetch_month_series,
    fetch_week_series,
    use_sale_aggregates,
)

from routes_mobile import (  # noqa: E402
    _has_daily_category_stats_table,
    _labor_store_id_param,
)


def _app_mod():
    return sys.modules.get("app") or sys.modules.get("__main__")


def _dparse(s: str) -> Optional[date]:
    s = (s or "").strip()[:10]
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _kpi_range(
    kpi_cycle: str, custom_s: str, custom_e: str
) -> Tuple[date, date, str]:
    today = date.today()
    c = (kpi_cycle or "last_30_days").strip().lower()
    if c == "today":
        return today, today, c
    if c == "this_week":
        # 与 Web 看板 period=week（query_layer.date_condition）一致：含今日在内的过去 7 天，
        # 勿用「当周周一至今日」（周初仅数日、与环比/近30天口径割裂）
        return today - timedelta(days=6), today, c
    if c == "this_month":
        return date(today.year, today.month, 1), today, c
    if c == "last_30_days":
        return today - timedelta(days=29), today, c
    if c == "custom":
        ds, de = _dparse(custom_s), _dparse(custom_e)
        if not ds or not de:
            raise ValueError("custom 须传 start_date、end_date")
        if ds > de:
            ds, de = de, ds
        return ds, de, c
    return today - timedelta(days=29), today, "last_30_days"


def _prev_range(s: date, e: date) -> Tuple[date, date]:
    n = (e - s).days + 1
    pe = s - timedelta(days=1)
    ps = pe - timedelta(days=n - 1)
    return ps, pe


def _yoy_range(s: date, e: date) -> Tuple[date, date]:
    def shift(d: date) -> date:
        try:
            return date(d.year - 1, d.month, d.day)
        except ValueError:
            return date(d.year - 1, d.month, 28)

    return shift(s), shift(e)


def _weekday_index_mysql() -> str:
    """周一=1 … 周日=7：MySQL DAYOFWEEK 周日=1 → 转 ISO 式周一=1。"""
    return "((WEEKDAY(data_date) + 1))"


def _sum_stats(
    cur,
    s: str,
    e: str,
    sq: str,
    sp: List[Any],
    large_code: Optional[str] = None,
) -> Tuple[float, float]:
    q = (
        "SELECT COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(gross_profit),0) AS gp "
        "FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq
    )
    p: List[Any] = [s, e] + sp
    if large_code:
        q += " AND category_large_code = %s"
        p.append(large_code)
    cur.execute(q, tuple(p))
    r = cur.fetchone() or {}
    return float(r.get("sa") or 0), float(r.get("gp") or 0)


def _stats_min_max_dates(cur, sq: str, sp: List[Any]) -> Tuple[Optional[Any], Optional[Any]]:
    """一次查询 MIN/MAX(data_date)，替代分别查 min 与 stats_as_of。"""
    try:
        cur.execute(
            "SELECT MIN(data_date) AS mn, MAX(data_date) AS mx FROM daily_category_stats WHERE 1=1 " + sq,
            tuple(sp),
        )
        r = cur.fetchone() or {}
        return r.get("mn"), r.get("mx")
    except Exception:
        return None, None


def _sale_min_max_dates(cur, sq: str, sp: List[Any]) -> Tuple[Optional[Any], Optional[Any]]:
    """销售明细表上的 MIN/MAX(data_date)，与 t_htma_sale 实际有数据的区间一致。"""
    try:
        cur.execute(
            "SELECT MIN(data_date) AS mn, MAX(data_date) AS mx FROM t_htma_sale WHERE 1=1 " + sq,
            tuple(sp),
        )
        r = cur.fetchone() or {}
        return r.get("mn"), r.get("mx")
    except Exception:
        return None, None


def _sum_stats_from_sale(
    cur,
    s: str,
    e: str,
    sq: str,
    sp: List[Any],
    large_code: Optional[str] = None,
) -> Tuple[float, float]:
    """按 t_htma_sale 汇总销售额/毛利（与看板 KPI 明细口径一致，不依赖预聚合刷新）。"""
    q = (
        "SELECT COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(COALESCE(gross_profit,0)),0) AS gp "
        "FROM t_htma_sale WHERE data_date BETWEEN %s AND %s " + sq
    )
    p: List[Any] = [s, e] + list(sp)
    if large_code:
        q += " AND COALESCE(NULLIF(TRIM(category_large_code),''), '') = %s"
        p.append(large_code)
    cur.execute(q, tuple(p))
    r = cur.fetchone() or {}
    return float(r.get("sa") or 0), float(r.get("gp") or 0)


def _mx_to_iso10(mx: Any) -> str:
    if mx is None:
        return ""
    if hasattr(mx, "isoformat"):
        return mx.isoformat()[:10]
    return str(mx)[:10]


def _coerce_sql_date(val: Any) -> Optional[date]:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        try:
            return date.fromisoformat(str(val)[:10])
        except Exception:
            return None
    return _dparse(str(val)[:10])


def _link_ratio(cur: float, prev: float) -> Optional[float]:
    if prev == 0:
        return None
    return round((cur - prev) / prev * 100.0, 2)


def _inventory_total(cur) -> float:
    """t_htma_stock 最近日期的 stock_amount 合计；无表/无数据时 0（直接查表，避免 information_schema 往返）。"""
    sq_store, sp = mobile_store_sql_prefix()
    try:
        cur.execute(
            "SELECT MAX(data_date) AS mx FROM t_htma_stock WHERE 1=1 " + (sq_store or "").replace("store_id", "t_htma_stock.store_id"),
            tuple(sp),
        )
        mx = (cur.fetchone() or {}).get("mx")
        if not mx:
            return 0.0
        dstr = mx.isoformat()[:10] if hasattr(mx, "isoformat") else str(mx)[:10]
        q = "SELECT COALESCE(SUM(stock_amount),0) AS t FROM t_htma_stock WHERE data_date = %s " + (sq_store or "").replace(
            "store_id", "t_htma_stock.store_id"
        )
        cur.execute(q, (dstr,) + tuple(sp))
        return float((cur.fetchone() or {}).get("t") or 0.0)
    except Exception:
        return 0.0


def _table_exists(cur, name: str) -> bool:
    try:
        cur.execute(
            "SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s LIMIT 1",
            (name,),
        )
        return bool(cur.fetchone())
    except Exception:
        return False


def _sale_has_column(cur, col: str) -> bool:
    try:
        cur.execute(
            "SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 't_htma_sale' AND COLUMN_NAME = %s LIMIT 1",
            (col,),
        )
        return bool(cur.fetchone())
    except Exception:
        return False


def augment_labor_summary_extras(
    s: str, e: str, store_id, ov: dict
) -> Dict[str, Any]:
    """为人力 summary 增加环比（上一同期）。"""
    try:
        ds, de = date.fromisoformat(s), date.fromisoformat(e)
    except Exception:
        return {}
    ps, pe = _prev_range(ds, de)
    pstart, pend = ps.isoformat(), pe.isoformat()
    conn = get_conn()
    try:
        p_ov = _labor_analysis_overview(conn, pstart, pend, store_id=store_id)
    except Exception:
        p_ov = {}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    tlc = float(ov.get("total_cost") or 0)
    p_tlc = float(p_ov.get("total_cost") or 0) if p_ov else 0.0
    t_sale = float(ov.get("total_sale") or 0)
    p_sale = float(p_ov.get("total_sale") or 0) if p_ov else 0.0
    spc = ov.get("sales_per_capita")
    p_spc = p_ov.get("sales_per_capita") if p_ov else None
    return {
        "labor_cost_link_ratio": _link_ratio(tlc, p_tlc) if p_tlc else None,
        "sales_link_ratio": _link_ratio(t_sale, p_sale) if p_sale else None,
        "sales_per_capita_link_ratio": _link_ratio(float(spc or 0), float(p_spc or 0))
        if spc is not None and p_spc is not None and float(p_spc) != 0
        else None,
        "labor_cost_to_sales_ratio": round(tlc / t_sale, 4) if t_sale > 0 else None,
        "prev_range": {"start_date": pstart, "end_date": pend},
    }


def _audit_blob() -> Dict[str, str]:
    import secrets
    from datetime import datetime, timezone

    return {
        "trace_id": secrets.token_hex(8),
        "queried_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _table_exists_bi(cur, name: str) -> bool:
    try:
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s LIMIT 1",
            (name,),
        )
        return cur.fetchone() is not None
    except Exception:
        return False


def mobile_attribution_response(*, audit_channel: str = "mobile"):
    """
    大类销售额环比归因（与 Web analytics_utils 口径一致）。
    供 /api/mobile/analysis/attribution 与 /api/wechat/mini/analysis/attribution 共用，避免网关只放行 /api/wechat 时 404。
    """
    from flask import request

    if request.method == "OPTIONS":
        return "", 204
    ds = (request.args.get("start_date") or "").strip()[:10]
    de = (request.args.get("end_date") or "").strip()[:10]
    d0, d1 = _dparse(ds), _dparse(de)
    if not d0 or not d1:
        return mobile_err("须传 start_date、end_date（YYYY-MM-DD）", code=1, http=400)
    if d0 > d1:
        d0, d1 = d1, d0
    ps, pe = _prev_range(d0, d1)
    s_cur, e_cur = d0.isoformat(), d1.isoformat()
    s_prev, e_prev = ps.isoformat(), pe.isoformat()
    sq, sp = mobile_store_sql_prefix()
    log = logging.getLogger("htma.api.attribution")
    conn = get_conn()
    try:
        cur = conn.cursor()
        if not _has_daily_category_stats_table(cur):
            return mobile_err("daily_category_stats 表不存在", code=1, http=501)
        rows_prev = fetch_category_large_sales_aggregates(cur, s_prev, e_prev, sq, tuple(sp))
        rows_cur = fetch_category_large_sales_aggregates(cur, s_cur, e_cur, sq, tuple(sp))
        body = merge_category_large_sales_mom_attribution(rows_prev, rows_cur)
        body["range"] = {
            "current": {"start_date": s_cur, "end_date": e_cur},
            "previous": {"start_date": s_prev, "end_date": e_prev},
        }
        trace = secrets.token_hex(8)
        body["audit"] = {
            "trace_id": trace,
            "queried_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "channel": audit_channel,
        }
        log.info(
            "analysis_attribution trace=%s channel=%s range=%s..%s",
            trace,
            audit_channel,
            s_cur,
            e_cur,
        )
        return mobile_ok(body)
    finally:
        conn.close()


def register_mobile_bi_routes(mobile_bp):
    @mobile_bp.route("/overview", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_mobile_overview():
        if request.method == "OPTIONS":
            return "", 204
        kc = (request.args.get("kpi_cycle") or "last_30_days").strip()
        try:
            ds, de, _tag = _kpi_range(
                kc, request.args.get("start_date") or "", request.args.get("end_date") or ""
            )
        except ValueError as ve:
            return mobile_err(str(ve), code=1, http=400)
        large = (request.args.get("category_large_code") or "").strip() or None
        sq, sp = mobile_store_sql_prefix()
        conn = get_conn()
        out: Dict[str, Any] = {
            "total_sales": 0.0,
            "total_profit": 0.0,
            "avg_margin": 0.0,
            "inventory_total": 0.0,
            "sales_link_ratio": None,
            "profit_link_ratio": None,
            "trend": {
                "daily_sales": [],
                "last_5_days_sales": 0.0,
                "last_5_days_profit": 0.0,
                "latest_date": "",
                "latest_sales": 0.0,
            },
            "yoy": {"sales_yoy": None, "profit_yoy": None, "need_data_days": 366, "note": ""},
            "weekday_compare": [],
            "kpi_cycle": kc,
            "range": {"start_date": "", "end_date": ""},
            "data_status": "ok",
            "overview_series": "daily_category_stats",
        }
        try:
            cur = conn.cursor()
            if not _has_daily_category_stats_table(cur):
                return mobile_err("daily_category_stats 表不存在", code=1, http=501)
            has_sale = _table_exists(cur, "t_htma_sale")
            use_sale = has_sale and (not large or _sale_has_column(cur, "category_large_code"))
            if use_sale:
                out["overview_series"] = "t_htma_sale"
            out["inventory_total"] = round(_inventory_total(cur), 2)
            if use_sale:
                mn_raw, mx_raw = _sale_min_max_dates(cur, sq, sp)
            else:
                mn_raw, mx_raw = _stats_min_max_dates(cur, sq, sp)
            mx_dt = _coerce_sql_date(mx_raw)
            agg_ds, agg_de = ds, de
            if mx_dt is not None and de > mx_dt:
                agg_de = mx_dt
            if agg_ds > agg_de:
                agg_ds = agg_de
            s, e = agg_ds.isoformat(), agg_de.isoformat()
            out["range"] = {"start_date": s, "end_date": e, "kpi_cycle": kc}
            if ds != agg_ds or de != agg_de:
                lag_note = (
                    "所选区间末尾尚无销售明细数据，销售额等按已有明细日期汇总（库存为实时表，可能不同步）。"
                    if use_sale
                    else "分类日汇总尚未更新到所选区间末尾，销售额/毛利等已按有数据的日期汇总（库存为实时表，可能不同步）。"
                )
                out["stats_lag"] = {
                    "calendar_start": ds.isoformat(),
                    "calendar_end": de.isoformat(),
                    "aggregated_start": s,
                    "aggregated_end": e,
                    "note": lag_note,
                }
            out["trend"]["latest_date"] = s
            ps, pe = _prev_range(agg_ds, agg_de)
            if use_sale:
                sa, gp = _sum_stats_from_sale(cur, s, e, sq, sp, large)
                psa, pgp = _sum_stats_from_sale(cur, ps.isoformat(), pe.isoformat(), sq, sp, large)
            else:
                sa, gp = _sum_stats(cur, s, e, sq, sp, large)
                psa, pgp = _sum_stats(cur, ps.isoformat(), pe.isoformat(), sq, sp, large)
            out["total_sales"] = round(sa, 2)
            out["total_profit"] = round(gp, 2)
            out["avg_margin"] = round(gp / sa * 100.0, 2) if sa > 0 else 0.0
            out["sales_link_ratio"] = _link_ratio(sa, psa) if psa is not None else None
            out["profit_link_ratio"] = _link_ratio(gp, pgp) if pgp is not None else None

            # 日趋势：仅拉最近 90 个有数据的自然日（按日倒序 LIMIT），避免长自定义区间全量 GROUP BY
            if use_sale:
                daily_where = (
                    "FROM t_htma_sale WHERE data_date BETWEEN %s AND %s " + sq
                    + (
                        large
                        and " AND COALESCE(NULLIF(TRIM(category_large_code),''), '') = %s "
                        or ""
                    )
                )
            else:
                daily_where = (
                    "FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq
                    + (large and " AND category_large_code = %s " or "")
                )
            daily_params: Tuple[Any, ...] = (s, e) + tuple(sp) + ((large,) if large else ())
            cur.execute(
                "SELECT data_date, COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(COALESCE(gross_profit,0)),0) AS gp "
                + daily_where
                + " GROUP BY data_date ORDER BY data_date DESC LIMIT 90",
                daily_params,
            )
            rows_desc = list(cur.fetchall() or [])
            daily_desc: List[Dict[str, Any]] = []
            last5_s = last5_p = 0.0
            for i, r in enumerate(rows_desc):
                dx = r.get("data_date")
                dss = dx.isoformat()[:10] if hasattr(dx, "isoformat") else str(dx)[:10]
                ssa = float(r.get("sa") or 0)
                gpp = float(r.get("gp") or 0)
                daily_desc.append({"date": dss, "value": round(ssa, 2), "profit": round(gpp, 2)})
                if i < 5:
                    last5_s += ssa
                    last5_p += gpp
            if rows_desc:
                lastr = rows_desc[0]
                ldx = lastr.get("data_date")
                lds = ldx.isoformat()[:10] if hasattr(ldx, "isoformat") else str(ldx)[:10]
                out["trend"]["latest_date"] = lds
                out["trend"]["latest_sales"] = round(float(lastr.get("sa") or 0), 2)
            out["trend"]["daily_sales"] = daily_desc
            out["trend"]["last_5_days_sales"] = round(last5_s, 2)
            out["trend"]["last_5_days_profit"] = round(last5_p, 2)

            # 周几对比（本区间内）
            wk_expr = _weekday_index_mysql()
            if use_sale:
                wk_from = (
                    "FROM t_htma_sale WHERE data_date BETWEEN %s AND %s " + sq
                    + (
                        large
                        and " AND COALESCE(NULLIF(TRIM(category_large_code),''), '') = %s "
                        or ""
                    )
                )
            else:
                wk_from = (
                    "FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq
                    + (large and " AND category_large_code = %s " or "")
                )
            cur.execute(
                f"SELECT {wk_expr} AS wd, COALESCE(SUM(sale_amount),0) AS sa "
                + wk_from
                + f" GROUP BY {wk_expr} ORDER BY wd",
                (s, e) + tuple(sp) + ((large,) if large else ()),
            )
            for r in cur.fetchall() or []:
                wdi = int(r.get("wd") or 0)
                if wdi == 0:
                    wdi = 7
                out["weekday_compare"].append(
                    {"weekday": wdi, "sales": round(float(r.get("sa") or 0), 2)}
                )

            # 同比 + stats_as_of（mn_raw/mx_raw 已在上方查询）
            mn_dt = _coerce_sql_date(mn_raw)
            ys, ye = _yoy_range(agg_ds, agg_de)
            need366 = (mn_dt is None) or (mn_dt > ys)
            if not need366:
                if use_sale:
                    ysa, ygp = _sum_stats_from_sale(cur, ys.isoformat(), ye.isoformat(), sq, sp, large)
                else:
                    ysa, ygp = _sum_stats(cur, ys.isoformat(), ye.isoformat(), sq, sp, large)
            else:
                ysa, ygp = (0.0, 0.0)
            if need366 or (ysa == 0 and ygp == 0):
                out["yoy"] = {
                    "sales_yoy": None,
                    "profit_yoy": None,
                    "need_data_days": 366,
                    "note": "数据周期不足1年" if need366 or ysa + ygp == 0 else "",
                }
            else:
                out["yoy"] = {
                    "sales_yoy": _link_ratio(sa, ysa) if ysa else None,
                    "profit_yoy": _link_ratio(gp, ygp) if ygp else None,
                    "need_data_days": 366,
                    "note": "",
                }
            # 「截止」应对齐本次 KPI 实际汇总窗口的末日，勿用全表 MAX（否则自定义选 1 月也会显示库内最新 4 月，易误解为未按区间汇总）
            out["stats_as_of"] = e
            out["sale_data_max_date"] = _mx_to_iso10(mx_raw)
        except Exception as ex:
            return mobile_err(str(ex), code=2, http=500)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return mobile_ok(out)

    @mobile_bp.route("/insights_signals", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_mobile_insights_signals():
        """大类毛利率 Z-异常 + 全店销额 7 日均线动量（daily_category_stats）。"""
        if request.method == "OPTIONS":
            return "", 204
        try:
            days = int((request.args.get("days") or "40").strip())
        except ValueError:
            days = 40
        days = max(14, min(days, 120))
        end_d = _dparse((request.args.get("end_date") or "").strip()[:10]) or date.today()
        start_d = end_d - timedelta(days=days - 1)
        sq, sp = mobile_store_sql_prefix()
        conn = get_conn()
        try:
            cur = conn.cursor()
            if not _has_daily_category_stats_table(cur):
                return mobile_err("daily_category_stats 表不存在", code=1, http=501)
            ins_use_sale = use_sale_aggregates(cur)
            if ins_use_sale:
                rows = fetch_insights_daily_large_rows(
                    cur, start_d.isoformat(), end_d.isoformat(), sq, sp
                )
            else:
                cur.execute(
                    "SELECT data_date, category_large_code, MAX(category_large) AS category_large, "
                    "SUM(sale_amount) AS sa, SUM(gross_profit) AS gp "
                    "FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq
                    + " GROUP BY data_date, category_large_code "
                    "ORDER BY data_date, category_large_code",
                    (start_d.isoformat(), end_d.isoformat()) + tuple(sp),
                )
                rows = list(cur.fetchall() or [])
            insights = compute_large_category_insights(
                rows, z_threshold=2.0, min_hist_days=5, min_last_sales=500
            )
            audit = _audit_blob()
            audit["source"] = "cursor_auto_evolve"
            audit["feature"] = "insights_signals"
            audit["series"] = "t_htma_sale" if ins_use_sale else "daily_category_stats"
            payload = {
                **insights,
                "range": {
                    "start_date": start_d.isoformat(),
                    "end_date": end_d.isoformat(),
                    "days": days,
                },
                "audit": audit,
            }
            return mobile_ok(payload)
        except Exception as ex:
            return mobile_err(str(ex), code=2, http=500)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @mobile_bp.route("/heatmap", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_mobile_heatmap():
        if request.method == "OPTIONS":
            return "", 204
        today = date.today()
        end_m = (request.args.get("year_month_end") or "").strip() or today.strftime("%Y-%m")
        try:
            ey, em = int(end_m[:4]), int(end_m[5:7])
            end_d = date(ey, em, 1)
        except Exception:
            return mobile_err("year_month_end 须为 YYYY-MM", code=1, http=400)
        start_m = (request.args.get("year_month_start") or "").strip()
        if not start_m:
            start_d = (end_d - timedelta(days=365)).replace(day=1)
        else:
            try:
                sy, sm = int(start_m[:4]), int(start_m[5:7])
                start_d = date(sy, sm, 1)
            except Exception:
                return mobile_err("year_month_start 须为 YYYY-MM", code=1, http=400)
        if start_d > end_d:
            start_d, end_d = end_d, start_d
        end_last = (end_d + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        s, e = start_d.isoformat(), end_last.isoformat()
        sq, sp = mobile_store_sql_prefix()
        conn = get_conn()
        mat: List[Dict[str, Any]] = []
        hm_src = "daily_category_stats"
        try:
            cur = conn.cursor()
            if not _has_daily_category_stats_table(cur):
                return mobile_err("daily_category_stats 表不存在", code=1, http=501)
            if use_sale_aggregates(cur):
                hm_src = "t_htma_sale"
                hrows = fetch_heatmap_month_rows(cur, s, e, sq, sp)
            else:
                cur.execute(
                    "SELECT DATE_FORMAT(data_date, '%%Y-%%m') AS ym, category_large_code, MAX(category_large) AS nm, "
                    "COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(gross_profit),0) AS gp "
                    "FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq
                    + " GROUP BY ym, category_large_code",
                    (s, e) + tuple(sp),
                )
                hrows = list(cur.fetchall() or [])
            for r in hrows:
                sa, gpp = float(r.get("sa") or 0), float(r.get("gp") or 0)
                mp = round(gpp / sa * 100.0, 2) if sa > 0 else 0.0
                mat.append(
                    {
                        "month": r.get("ym") or "",
                        "category_large": r.get("nm") or "",
                        "category_large_code": r.get("category_large_code") or "",
                        "margin_pct": mp,
                    }
                )
        finally:
            conn.close()
        return mobile_ok(
            {
                "matrix": mat,
                "range": {"start_date": s, "end_date": e},
                "data_source": hm_src,
            }
        )

    @mobile_bp.route("/category_share", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_category_share():
        if request.method == "OPTIONS":
            return "", 204
        kc = (request.args.get("kpi_cycle") or "last_30_days").strip()
        try:
            ds, de, _ = _kpi_range(
                kc, request.args.get("start_date") or "", request.args.get("end_date") or ""
            )
        except ValueError as ve:
            return mobile_err(str(ve), code=1, http=400)
        s, e = ds.isoformat(), de.isoformat()
        sq, sp = mobile_store_sql_prefix()
        conn = get_conn()
        share_src = "daily_category_stats"
        try:
            cur = conn.cursor()
            if not _has_daily_category_stats_table(cur):
                return mobile_err("daily_category_stats 表不存在", code=1, http=501)
            if use_sale_aggregates(cur):
                share_src = "t_htma_sale"
                rows = fetch_category_share_rows(cur, s, e, sq, sp)
            else:
                cur.execute(
                    "SELECT category_large_code, MAX(category_large) AS nm, COALESCE(SUM(sale_amount),0) AS sa "
                    "FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq
                    + " GROUP BY category_large_code ORDER BY sa DESC",
                    (s, e) + tuple(sp),
                )
                rows = list(cur.fetchall() or [])
            tot = sum(float((r or {}).get("sa") or 0) for r in rows) or 0.0
            items = []
            for r in rows:
                sa = float((r or {}).get("sa") or 0)
                items.append(
                    {
                        "category_large": (r or {}).get("nm") or "",
                        "category_large_code": (r or {}).get("category_large_code") or "",
                        "sales_amount": round(sa, 2),
                        "percentage": round(sa / tot * 100.0, 2) if tot > 0 else 0.0,
                    }
                )
        finally:
            conn.close()
        return mobile_ok(
            {
                "items": items,
                "range": {"start_date": s, "end_date": e, "kpi_cycle": kc},
                "data_source": share_src,
            }
        )

    @mobile_bp.route("/contribution", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_contribution():
        if request.method == "OPTIONS":
            return "", 204
        kc = (request.args.get("kpi_cycle") or "last_30_days").strip()
        try:
            ds, de, _ = _kpi_range(
                kc, request.args.get("start_date") or "", request.args.get("end_date") or ""
            )
        except ValueError as ve:
            return mobile_err(str(ve), code=1, http=400)
        s, e = ds.isoformat(), de.isoformat()
        sq, sp = mobile_store_sql_prefix()
        conn = get_conn()
        ctr_src = "daily_category_stats"
        try:
            cur = conn.cursor()
            if not _has_daily_category_stats_table(cur):
                return mobile_err("daily_category_stats 表不存在", code=1, http=501)
            if use_sale_aggregates(cur):
                ctr_src = "t_htma_sale"
                rows = fetch_contribution_rows(cur, s, e, sq, sp)
            else:
                cur.execute(
                    "SELECT category_large_code, MAX(category_large) AS nm, "
                    "COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(gross_profit),0) AS gp "
                    "FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq
                    + " GROUP BY category_large_code ORDER BY sa DESC",
                    (s, e) + tuple(sp),
                )
                rows = list(cur.fetchall() or [])
            ts = sum(float((r or {}).get("sa") or 0) for r in rows) or 0.0
            tgp = sum(float((r or {}).get("gp") or 0) for r in rows) or 0.0
            out = []
            for r in rows:
                sa, gp = float((r or {}).get("sa") or 0), float((r or {}).get("gp") or 0)
                out.append(
                    {
                        "large_category": (r or {}).get("nm") or "",
                        "category_large_code": (r or {}).get("category_large_code") or "",
                        "sales_share": round(sa / ts, 4) if ts else 0.0,
                        "profit_share": round(gp / tgp, 4) if tgp else 0.0,
                    }
                )
        finally:
            conn.close()
        return mobile_ok({"items": out, "range": {"start_date": s, "end_date": e}, "data_source": ctr_src})

    @mobile_bp.route("/contribution_export", methods=["GET", "OPTIONS"])
    def api_contribution_export():
        """与 contribution 同权限（mobile_bp 统一 before_request）；返回 CSV 文件。"""
        if request.method == "OPTIONS":
            return "", 204
        kc = (request.args.get("kpi_cycle") or "last_30_days").strip()
        try:
            ds, de, _ = _kpi_range(
                kc, request.args.get("start_date") or "", request.args.get("end_date") or ""
            )
        except ValueError:
            return mobile_err("参数错误", code=1, http=400)
        s, e = ds.isoformat(), de.isoformat()
        sq, sp = mobile_store_sql_prefix()
        conn = get_conn()
        try:
            cur = conn.cursor()
            if not _has_daily_category_stats_table(cur):
                return mobile_err("daily_category_stats 表不存在", code=1, http=501)
            if use_sale_aggregates(cur):
                rows = fetch_contribution_rows(cur, s, e, sq, sp)
            else:
                cur.execute(
                    "SELECT category_large_code, MAX(category_large) AS nm, "
                    "COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(gross_profit),0) AS gp "
                    "FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq
                    + " GROUP BY category_large_code ORDER BY sa DESC",
                    (s, e) + tuple(sp),
                )
                rows = list(cur.fetchall() or [])
            ts = sum(float((r or {}).get("sa") or 0) for r in rows) or 0.0
            tgp = sum(float((r or {}).get("gp") or 0) for r in rows) or 0.0
            lines = ["大类,销售额占比,毛利额占比,销售额(元),毛利(元)"]
            for r in rows:
                sa, gp = float((r or {}).get("sa") or 0), float((r or {}).get("gp") or 0)
                lines.append(
                    f"{(r or {}).get('nm') or ''},"
                    f"{(sa / ts if ts else 0):.4f},{(gp / tgp if tgp else 0):.4f},"
                    f"{sa:.2f},{gp:.2f}"
                )
            data = "\ufeff" + "\n".join(lines) + "\n"
        finally:
            conn.close()
        return Response(
            data,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=contribution_{s}_{e}.csv"},
        )

    @mobile_bp.route("/trend_advanced", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_trend_advanced():
        if request.method == "OPTIONS":
            return "", 204
        gran = (request.args.get("granularity") or "day").strip().lower()
        if gran not in ("day", "week", "month"):
            return mobile_err("granularity 须为 day|week|month", code=1, http=400)
        metric = (request.args.get("metric") or "sales").strip().lower()
        if metric not in ("sales", "profit", "margin"):
            return mobile_err("metric 须为 sales|profit|margin", code=1, http=400)
        s = (request.args.get("start_date") or "").strip()[:10] or (date.today() - timedelta(days=29)).isoformat()
        e = (request.args.get("end_date") or "").strip()[:10] or date.today().isoformat()
        ds, de = _dparse(s), _dparse(e)
        if not ds or not de:
            return mobile_err("start_date/end_date 须为 YYYY-MM-DD", code=1, http=400)
        if ds > de:
            ds, de = de, ds
        s, e = ds.isoformat(), de.isoformat()
        sq, sp = mobile_store_sql_prefix()
        conn = get_conn()
        out_dates: List[str] = []
        out_val: List[float] = []
        use_sale_adv = False
        try:
            cur = conn.cursor()
            if not _has_daily_category_stats_table(cur):
                return mobile_err("daily_category_stats 表不存在", code=1, http=501)
            use_sale_adv = use_sale_aggregates(cur)
            if gran == "day":
                if use_sale_adv:
                    day_rows = fetch_day_series_limited(cur, s, e, sq, sp, limit=400)
                else:
                    cur.execute(
                        "SELECT data_date, COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(gross_profit),0) AS gp "
                        "FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq
                        + " GROUP BY data_date ORDER BY data_date DESC LIMIT 400",
                        (s, e) + tuple(sp),
                    )
                    day_rows = list(reversed(list(cur.fetchall() or [])))
                for r in day_rows:
                    dx = r.get("data_date")
                    dss = dx.isoformat()[:10] if hasattr(dx, "isoformat") else str(dx)[:10]
                    sa, gp = float(r.get("sa") or 0), float(r.get("gp") or 0)
                    v = _metric_value(metric, sa, gp)
                    out_dates.append(dss)
                    out_val.append(v)
            elif gran == "week":
                if use_sale_adv:
                    wrows = fetch_week_series(cur, s, e, sq, sp)
                else:
                    cur.execute(
                        "SELECT YEARWEEK(data_date, 1) AS yw, "
                        "COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(gross_profit),0) AS gp "
                        "FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq
                        + " GROUP BY yw ORDER BY yw DESC LIMIT 120",
                        (s, e) + tuple(sp),
                    )
                    wrows = list(cur.fetchall() or [])
                for r in reversed(wrows):
                    yw = r.get("yw")
                    sa, gp = float(r.get("sa") or 0), float(r.get("gp") or 0)
                    v = _metric_value(metric, sa, gp)
                    out_dates.append("W" + str(yw))
                    out_val.append(v)
            else:
                if use_sale_adv:
                    mrows = fetch_month_series(cur, s, e, sq, sp)
                else:
                    cur.execute(
                        "SELECT DATE_FORMAT(data_date, '%%Y-%%m') AS ym, "
                        "COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(gross_profit),0) AS gp "
                        "FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq
                        + " GROUP BY ym ORDER BY ym DESC LIMIT 60",
                        (s, e) + tuple(sp),
                    )
                    mrows = list(cur.fetchall() or [])
                for r in reversed(mrows):
                    sa, gp = float(r.get("sa") or 0), float(r.get("gp") or 0)
                    v = _metric_value(metric, sa, gp)
                    out_dates.append((r.get("ym") or "").strip())
                    out_val.append(v)
        finally:
            conn.close()
        return mobile_ok(
            {
                "granularity": gran,
                "metric": metric,
                "dates": out_dates,
                "values": out_val,
                "range": {"start_date": s, "end_date": e},
                "data_source": "t_htma_sale" if use_sale_adv else "daily_category_stats",
            }
        )

    @mobile_bp.route("/four_quadrant_simple", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_four_quadrant_simple():
        if request.method == "OPTIONS":
            return "", 204
        start_d, end_d = (date.today() - timedelta(days=29)).isoformat(), date.today().isoformat()
        s = (request.args.get("start_date") or start_d)[:10]
        e = (request.args.get("end_date") or end_d)[:10]
        _sid_req = (request.args.get("store_id") or "").strip() or None
        sid = _sid_req if _sid_req else _labor_store_id_param()
        conn = get_conn()
        try:
            rows = _labor_analysis_by_category(conn, s, e, store_id=sid) or []
            pts = []
            for r in rows:
                sale = float(r.get("sale") or 0)
                profit = float(r.get("profit") or 0)
                labor = float(r.get("labor_cost") or 0)
                if profit <= 0:
                    continue
                m_pct = float(r.get("margin_pct") or (profit / sale * 100.0 if sale > 0 else 0.0))
                intensity = labor / profit if profit else 0.0
                pts.append(
                    {
                        "category": r.get("category") or r.get("category_large_code") or "",
                        "category_large_code": (r.get("category_large_code") or "").strip(),
                        "margin_pct": round(m_pct, 2),
                        "labor_intensity": round(intensity, 4),
                    }
                )
            mx = statistics.median([p["margin_pct"] for p in pts]) if pts else 0.0
            my = statistics.median([p["labor_intensity"] for p in pts]) if pts else 0.0
            low_high = [
                p
                for p in pts
                if p["margin_pct"] < mx and p["labor_intensity"] > my and p["labor_intensity"] > 0
            ]
        finally:
            conn.close()
        return mobile_ok(
            {
                "low_margin_high_labor": low_high[:30],
                "hint": "低毛利高人力：低于中位毛利率且高于中位人力/毛利；建议压缩编制或提毛利。",
            }
        )

    @mobile_bp.route("/sku_search", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_sku_search():
        if request.method == "OPTIONS":
            return "", 204
        kw = (request.args.get("keyword") or request.args.get("q") or "").strip()
        if len(kw) < 1:
            return mobile_err("keyword 必填", code=1, http=400)
        if len(kw) > 64:
            kw = kw[:64]
        sq, sp = mobile_store_sql_prefix()
        conn = get_conn()
        items = []
        try:
            cur = conn.cursor()
            if not _table_exists(cur, "t_htma_sale"):
                return mobile_ok({"items": [], "note": "无销售明细表"}, msg="")
            like = "%" + kw.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
            end_d = date.today()
            start_d = end_d - timedelta(days=90)
            name_sel = "sku_code"
            if _sale_has_column(cur, "product_name"):
                name_sel = "COALESCE(NULLIF(product_name,''), sku_code)"
            wh = " (sku_code LIKE %s"
            p: List[Any] = [start_d.isoformat(), end_d.isoformat()] + list(sp) + [like]
            if _sale_has_column(cur, "product_name"):
                wh += " OR product_name LIKE %s"
                p.append(like)
            wh += ")"
            q = (
                f"SELECT sku_code, MAX({name_sel}) AS nm, "
                "COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(gross_profit),0) AS gp, "
                "COALESCE(SUM(sale_qty),0) AS qty "
                "FROM t_htma_sale WHERE data_date BETWEEN %s AND %s " + sq
                + " AND "
                + wh
                + " GROUP BY sku_code ORDER BY sa DESC LIMIT 50"
            )
            cur.execute(q, tuple(p))
            for r in cur.fetchall() or []:
                sa, gp = float(r.get("sa") or 0), float(r.get("gp") or 0)
                items.append(
                    {
                        "sku_code": (r or {}).get("sku_code") or "",
                        "name": (r or {}).get("nm") or "",
                        "sale_amount": round(sa, 2),
                        "gross_profit": round(gp, 2),
                        "margin_pct": round(gp / sa * 100, 2) if sa else 0.0,
                        "sale_qty": float((r or {}).get("qty") or 0),
                    }
                )
        finally:
            conn.close()
        return mobile_ok({"items": items})

    @mobile_bp.route("/tax_summary", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_tax_summary():
        if request.method == "OPTIONS":
            return "", 204
        sq, sp = mobile_store_sql_prefix()
        conn = get_conn()
        out = {
            "avg_tax_rate_pct": None,
            "note": "",
            "data_mode": "none",
        }
        try:
            cur = conn.cursor()
            if not _table_exists(cur, "t_htma_sale") or not _sale_has_column(cur, "tax_amount"):
                out["note"] = "t_htma_sale 未配置 tax_amount 字段，以下为占位说明"
                out["data_mode"] = "placeholder"
            else:
                end_d = date.today()
                start_d = end_d - timedelta(days=30)
                cur.execute(
                    "SELECT COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(tax_amount),0) AS tx "
                    "FROM t_htma_sale WHERE data_date BETWEEN %s AND %s " + sq,
                    (start_d.isoformat(), end_d.isoformat()) + tuple(sp),
                )
                r = cur.fetchone() or {}
                sa, tx = float(r.get("sa") or 0), float(r.get("tx") or 0)
                if sa > 0:
                    out["avg_tax_rate_pct"] = round(tx / sa * 100.0, 3)
                out["data_mode"] = "db"
        finally:
            conn.close()
        return mobile_ok(out)

    @mobile_bp.route("/selection", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_selection():
        if request.method == "OPTIONS":
            return "", 204
        sq, sp = mobile_store_sql_prefix()
        conn = get_conn()
        items = []
        try:
            cur = conn.cursor()
            if not _table_exists(cur, "t_htma_sale"):
                return mobile_ok({"items": [], "note": "无销售表明细"})
            end_d = date.today()
            start_d = end_d - timedelta(days=30)
            nm_expr = "MAX(sku_code)"
            if _sale_has_column(cur, "product_name"):
                nm_expr = "MAX(COALESCE(NULLIF(product_name,''), sku_code))"
            cur.execute(
                f"SELECT sku_code, {nm_expr} AS nm, "
                "COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(gross_profit),0) AS gp, "
                "COALESCE(SUM(sale_qty),0) AS qty "
                "FROM t_htma_sale WHERE data_date BETWEEN %s AND %s " + sq
                + " GROUP BY sku_code "
                "HAVING sa > 0 AND SUM(gross_profit) / NULLIF(SUM(sale_amount),0) >= 0.30 "
                "ORDER BY qty DESC LIMIT 20",
                (start_d.isoformat(), end_d.isoformat()) + tuple(sp),
            )
            for r in cur.fetchall() or []:
                sa, gp = float(r.get("sa") or 0), float(r.get("gp") or 0)
                items.append(
                    {
                        "sku_code": (r or {}).get("sku_code") or "",
                        "name": (r or {}).get("nm") or "",
                        "sale_amount": round(sa, 2),
                        "gross_profit": round(gp, 2),
                        "margin_pct": round(gp / sa * 100, 2) if sa else 0.0,
                        "tag": "高毛利&高销量",
                    }
                )
        finally:
            conn.close()
        return mobile_ok({"items": items, "note": "规则：近30天毛利率≥30% 按销量 Top"})

    @mobile_bp.route("/ai_advice", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_ai_advice():
        if request.method == "OPTIONS":
            return "", 204
        parts = []
        s, e = (date.today() - timedelta(days=29)).isoformat(), date.today().isoformat()
        sq, sp = mobile_store_sql_prefix()
        try:
            conn = get_conn()
            cur = conn.cursor()
            if _has_daily_category_stats_table(cur):
                sa, gp = _sum_stats(cur, s, e, sq, sp, None)
                ps, pe = _prev_range(date.fromisoformat(s), date.fromisoformat(e))
                psa, pgp = _sum_stats(cur, ps.isoformat(), pe.isoformat(), sq, sp, None)
                lr = _link_ratio(sa, psa) if psa is not None else None
                if lr is not None and lr < -3:
                    parts.append(f"近30天销售额环比约 {lr:.1f}%，需关注客单与动销；")
                m = gp / sa * 100 if sa else 0
                if m < 20:
                    parts.append(f"整体毛利率约 {m:.1f}%，建议核查定价与进货结构；")
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if not parts:
            parts.append("近30天经营数据波动在可控范围，建议持续跟踪大类毛利与人力效率。")
        return mobile_ok({"text": "".join(parts), "generated_at": e, "audit": _audit_blob()})

    @mobile_bp.route("/alerts/list", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_mobile_alerts_list():
        if request.method == "OPTIONS":
            return "", 204
        from flask import g
        from urllib.parse import quote

        from routes_mobile import (
            _alerts_effective_store_id,
            _alerts_list,
            _date_range_by_days,
            _parse_days,
        )

        audit = _audit_blob()
        days = _parse_days(30, 365)
        s, e = _date_range_by_days(days)
        st = _alerts_effective_store_id()
        sq, sprefix = mobile_store_sql_prefix()
        items: List[Dict[str, Any]] = []
        used_alert_table = False
        conn = get_conn()
        try:
            cur = conn.cursor()
            if _table_exists_bi(cur, "alert_events"):
                used_alert_table = True
                include_ack = (request.args.get("include_ack") or "").strip().lower() in ("1", "true", "yes")
                q = (
                    "SELECT id, type, level, title, summary, payload_json, created_at, acked_at "
                    "FROM alert_events WHERE store_id=%s "
                )
                p: List[Any] = [st or ""]
                if not include_ack:
                    q += " AND acked_at IS NULL "
                q += " ORDER BY created_at DESC LIMIT 80"
                cur.execute(q, tuple(p))
                for r in cur.fetchall() or []:
                    pj = r.get("payload_json")
                    if isinstance(pj, (bytes, str)):
                        try:
                            import json as _json

                            pj = _json.loads(pj)
                        except Exception:
                            pj = {}
                    if not isinstance(pj, dict):
                        pj = {}
                    lc = (pj.get("category_large_code") or "").strip()
                    ln = (pj.get("category_large") or "").strip()
                    link = ""
                    if lc:
                        link = (
                            "htma://analysis?large_code="
                            + quote(str(lc), safe="")
                            + "&large_name="
                            + quote(str(ln), safe="")
                        )
                    lvl = (r.get("level") or "warning").strip().lower()
                    icon = "error" if lvl == "critical" else ("warning" if lvl == "warning" else "info")
                    items.append(
                        {
                            "id": int(r.get("id") or 0),
                            "type": r.get("type") or "",
                            "level": lvl,
                            "title": r.get("title") or "",
                            "detail": (r.get("summary") or "").strip(),
                            "link": link,
                            "icon": icon,
                            "created_at": str(r.get("created_at") or "")[:19],
                            "acked_at": str(r.get("acked_at") or "")[:19] if r.get("acked_at") else None,
                        }
                    )
            if not items:
                for row in _alerts_list(cur, s, e, st, sq, sprefix):
                    items.append(
                        {
                            "id": 0,
                            "type": row.get("type") or "legacy",
                            "level": "warning"
                            if row.get("icon") == "warning"
                            else ("critical" if row.get("icon") == "error" else "info"),
                            "title": row.get("title") or "",
                            "detail": row.get("detail") or "",
                            "link": row.get("link") or "",
                            "icon": row.get("icon") or "info",
                            "created_at": "",
                            "acked_at": None,
                        }
                    )
            stats_as_of = ""
            if _has_daily_category_stats_table(cur):
                cur.execute(
                    "SELECT MAX(data_date) AS mx FROM daily_category_stats WHERE 1=1 " + sq,
                    tuple(sprefix),
                )
                mx = (cur.fetchone() or {}).get("mx")
                if mx:
                    stats_as_of = mx.isoformat()[:10] if hasattr(mx, "isoformat") else str(mx)[:10]
        finally:
            conn.close()
        return mobile_ok(
            {
                "items": items,
                "range": {"start_date": s, "end_date": e, "store_id": st},
                "data_source": "alert_events" if used_alert_table else "legacy",
                "stats_as_of": stats_as_of,
                "audit": audit,
            }
        )

    @mobile_bp.route("/alerts/ack", methods=["POST", "OPTIONS"])
    def api_mobile_alerts_ack():
        if request.method == "OPTIONS":
            return "", 204
        from flask import g

        pl = getattr(g, "wechat_jwt_payload", None) or {}
        try:
            uid = int(str(pl.get("sub") or "0").strip() or 0)
        except Exception:
            uid = 0
        body = request.get_json(silent=True) or {}
        try:
            aid = int(body.get("id") or 0)
        except Exception:
            aid = 0
        if aid <= 0:
            return mobile_err("须传 id", code=1, http=400)
        sid_ctx = getattr(g, "mobile_store_id", None) or ""
        scope = getattr(g, "mobile_scope", "single")
        conn = get_conn()
        try:
            cur = conn.cursor()
            if not _table_exists_bi(cur, "alert_events"):
                return mobile_err("alert_events 表不存在", code=1, http=501)
            cur.execute(
                "SELECT id, store_id FROM alert_events WHERE id=%s LIMIT 1",
                (aid,),
            )
            row = cur.fetchone()
            if not row:
                return mobile_err("记录不存在", code=1, http=404)
            row_sid = str((row or {}).get("store_id") or "").strip()
            if scope != "all" and row_sid and row_sid != str(sid_ctx or "").strip():
                return mobile_err("无权处理该预警", code=1, http=403)
            cur.execute(
                "UPDATE alert_events SET acked_at=NOW(), ack_user_id=%s WHERE id=%s AND acked_at IS NULL",
                (uid if uid else None, aid),
            )
            conn.commit()
        finally:
            conn.close()
        return mobile_ok({"ok": True, "id": aid, "audit": _audit_blob()})

    @mobile_bp.route("/ai_daily/latest", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_mobile_ai_daily_latest():
        if request.method == "OPTIONS":
            return "", 204
        from flask import g

        sid = getattr(g, "mobile_store_id", None) or ""
        if getattr(g, "mobile_scope", "single") == "all":
            sid = (os.environ.get("HTMA_STORE_ID") or "沈阳超级仓").strip()
        audit = _audit_blob()
        conn = get_conn()
        try:
            cur = conn.cursor()
            if not _table_exists_bi(cur, "daily_ai_reports"):
                return mobile_ok(
                    {
                        "content": "",
                        "report_date": "",
                        "note": "daily_ai_reports 表不存在，请先执行建表脚本",
                        "audit": audit,
                    }
                )
            cur.execute(
                "SELECT report_date, content, meta_json, created_at FROM daily_ai_reports WHERE store_id=%s ORDER BY report_date DESC LIMIT 1",
                (sid or "",),
            )
            r = cur.fetchone()
            if not r:
                return mobile_ok({"content": "", "report_date": "", "note": "暂无快报", "audit": audit})
            mj = r.get("meta_json")
            if isinstance(mj, (bytes, str)):
                try:
                    import json as _json

                    mj = _json.loads(mj)
                except Exception:
                    mj = {}
            return mobile_ok(
                {
                    "content": (r.get("content") or "").strip(),
                    "report_date": str(r.get("report_date") or "")[:10],
                    "meta": mj if isinstance(mj, dict) else {},
                    "created_at": str(r.get("created_at") or "")[:19],
                    "audit": audit,
                }
            )
        finally:
            conn.close()

    @mobile_bp.route("/generate_report", methods=["POST", "OPTIONS"])
    def api_generate_report():
        if request.method == "OPTIONS":
            return "", 204
        base = (os.environ.get("HTMA_PUBLIC_URL") or "").rstrip("/")
        if not base:
            base = "https://htma.greatagain.com.cn"
        return mobile_ok(
            {
                "status": "ok",
                "url": base + "/",
                "message": "请在 PC 看板或运行 npm run htma:report 生成报告；此入口预留异步 PDF。",
            }
        )

    @mobile_bp.route("/inventory_summary", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_inventory_summary():
        if request.method == "OPTIONS":
            return "", 204
        sq, sp = mobile_store_sql_prefix()
        conn = get_conn()
        out = {
            "inventory_total": 0.0,
            "low_stock_items": [],
            "as_of": None,
            "note": "",
        }
        try:
            cur = conn.cursor()
            out["inventory_total"] = round(_inventory_total(cur), 2)
            if _table_exists(cur, "t_htma_stock"):
                cur.execute(
                    "SELECT MAX(data_date) AS mx FROM t_htma_stock WHERE 1=1 " + sq.replace(
                        "store_id", "t_htma_stock.store_id"
                    ),
                    tuple(sp),
                )
                mx = (cur.fetchone() or {}).get("mx")
                if mx:
                    dstr = mx.isoformat()[:10] if hasattr(mx, "isoformat") else str(mx)[:10]
                    out["as_of"] = dstr
                    cur.execute(
                        "SELECT sku_code, stock_qty, stock_amount FROM t_htma_stock "
                        "WHERE data_date = %s " + sq.replace("store_id", "t_htma_stock.store_id")
                        + " AND stock_amount > 0 AND stock_qty < 5 "
                        "ORDER BY stock_amount ASC LIMIT 20",
                        (dstr,) + tuple(sp),
                    )
                    for r in cur.fetchall() or []:
                        out["low_stock_items"].append(
                            {
                                "sku_code": (r or {}).get("sku_code") or "",
                                "stock_qty": float((r or {}).get("stock_qty") or 0),
                                "stock_amount": float((r or {}).get("stock_amount") or 0),
                            }
                        )
            else:
                out["note"] = "未找到 t_htma_stock，请导入库存数据"
        finally:
            conn.close()
        return mobile_ok(out)

    @mobile_bp.route("/analysis/attribution", methods=["GET", "OPTIONS"])
    @mobile_bp.route("/attribution", methods=["GET", "OPTIONS"])
    @mobile_cached
    def api_mobile_analysis_attribution():
        """大类销售额环比归因（与 Web 共用 analytics_utils 口径）。"""
        return mobile_attribution_response(audit_channel="mobile")


def _metric_value(metric: str, sa: float, gp: float) -> float:
    if metric == "sales":
        return round(sa, 2)
    if metric == "profit":
        return round(gp, 2)
    return round(gp / sa * 100.0, 2) if sa > 0 else 0.0
