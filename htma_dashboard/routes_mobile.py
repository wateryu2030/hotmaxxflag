# -*- coding: utf-8 -*-
"""小程序/移动端：聚合接口；鉴权见 wechat_mobile_guard；统一样式 { code, data, msg }。"""
import os
import statistics
import sys
from datetime import date, timedelta
from urllib.parse import quote

from db_config import get_conn
from flask import Blueprint, g, request
from extensions import mobile_cached
from labor_routes import _labor_analysis_by_category, _labor_analysis_overview
from labor_utils import get_unmapped_categories
from mobile_json import mobile_err, mobile_ok
from mobile_sale_aggregates import (
    alerts_total_sale_and_large_rows,
    fetch_category_large_rows,
    fetch_category_mid_rows,
    fetch_day_series_sa_gp,
    sale_max_data_date,
    use_sale_aggregates,
)
from wechat_mobile_guard import mobile_store_sql_prefix, resolve_mobile_context


def _app_mod():
    return sys.modules.get("app") or sys.modules.get("__main__")


def _env_float(name, default):
    try:
        return float((os.environ.get(name) or str(default)).strip())
    except Exception:
        return float(default)


def _env_int(name, default):
    try:
        return int((os.environ.get(name) or str(default)).strip())
    except Exception:
        return int(default)


def _labor_store_id_param():
    """人力接口：URL store_id 优先；否则单店用 JWT 店；全部门店为 None（销售汇总不限店）。"""
    s = (request.args.get("store_id") or "").strip()
    if s:
        return s
    if getattr(g, "mobile_scope", "") == "all":
        return None
    return getattr(g, "mobile_store_id", None)


def _alerts_effective_store_id():
    s = (request.args.get("store_id") or "").strip()
    if s:
        return s
    if getattr(g, "mobile_scope", "") == "all":
        M = _app_mod()
        return (getattr(M, "STORE_ID", None) if M else None) or "沈阳超级仓"
    return getattr(g, "mobile_store_id", None) or "沈阳超级仓"


def _parse_days(default=30, cap=365):
    try:
        n = int(request.args.get("days") or default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, cap))


def _date_range_by_days(num_days: int):
    end_d = date.today()
    start_d = end_d - timedelta(days=num_days - 1)
    return start_d.isoformat(), end_d.isoformat()


def _parse_yyyy_mm_dd(name, default_iso):
    s = (request.args.get(name) or "").strip()[:10]
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return default_iso


def _has_daily_category_stats_table(cur) -> bool:
    try:
        cur.execute(
            """
            SELECT 1 FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'daily_category_stats' LIMIT 1
            """
        )
        return bool(cur.fetchone())
    except Exception:
        return False


def _has_t_htma_sale_table(cur) -> bool:
    try:
        cur.execute(
            """
            SELECT 1 FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_htma_sale' LIMIT 1
            """
        )
        return bool(cur.fetchone())
    except Exception:
        return False


def _stats_max_date(cur, sq: str, sprefix) -> str:
    try:
        cur.execute("SELECT MAX(data_date) AS mx FROM daily_category_stats WHERE 1=1 " + sq, tuple(sprefix))
        r = cur.fetchone() or {}
        mx = r.get("mx")
        if mx is None:
            return ""
        if hasattr(mx, "isoformat"):
            return mx.isoformat()[:10]
        return str(mx)[:10]
    except Exception:
        return ""


def _negative_sku_count(cur, s, e, sq, sprefix) -> int:
    try:
        qneg = (
            "SELECT COUNT(*) AS c FROM ( SELECT sku_code FROM t_htma_sale "
            "WHERE data_date BETWEEN %s AND %s " + sq
            + " GROUP BY sku_code HAVING SUM(sale_amount) > 0 "
            "AND SUM(gross_profit) / SUM(sale_amount) < 0 ) t"
        )
        cur.execute(qneg, (s, e) + tuple(sprefix))
        return int((cur.fetchone() or {}).get("c") or 0)
    except Exception:
        return 0


def _alerts_list(cur, s, e, store_for_unmapped: str, sq: str, sprefix) -> list:
    items = []
    low_thr = _env_float("HTMA_ALERT_LOW_MARGIN_PCT", 20.0)
    share_thr = _env_float("HTMA_ALERT_LARGE_SHARE_PCT", 5.0)
    neg_thr = _env_int("HTMA_ALERT_NEG_SKU_THRESHOLD", 10)
    try:
        if use_sale_aggregates(cur):
            tot_sa, large_rows = alerts_total_sale_and_large_rows(cur, s, e, sq, sprefix)
            for row in large_rows:
                sa = float(row.get("sa") or 0)
                gp = float(row.get("gp") or 0)
                if sa <= 0:
                    continue
                m_pct = gp / sa * 100.0
                sh_pct = (sa / tot_sa * 100.0) if tot_sa > 0 else 0.0
                if m_pct < low_thr and sh_pct > share_thr:
                    lc = row.get("category_large_code") or ""
                    ln = row.get("category_large") or ""
                    q = f"large_code={quote(str(lc), safe='')}&large_name={quote(str(ln), safe='')}"
                    items.append(
                        {
                            "type": "low_margin_category",
                            "icon": "warning",
                            "title": "低毛利大类",
                            "detail": f"{(row.get('category_large') or row.get('category_large_code') or '')} 毛利率 {m_pct:.1f}%，"
                            f"销额占比 {sh_pct:.1f}%",
                            "link": f"htma://analysis?{q}",
                        }
                    )
        elif _has_daily_category_stats_table(cur):
            cur.execute(
                "SELECT COALESCE(SUM(sale_amount),0) AS t FROM daily_category_stats "
                "WHERE data_date BETWEEN %s AND %s " + sq,
                (s, e) + tuple(sprefix),
            )
            tot_sa = float((cur.fetchone() or {}).get("t") or 0.0) or 0.0
            cur.execute(
                """
                SELECT category_large_code,
                       MAX(category_large) AS category_large,
                       COALESCE(SUM(sale_amount),0) AS sa,
                       COALESCE(SUM(gross_profit),0) AS gp
                FROM daily_category_stats
                WHERE data_date BETWEEN %s AND %s
                """
                + sq
                + " GROUP BY category_large_code HAVING sa > 0.01",
                (s, e) + tuple(sprefix),
            )
            for row in cur.fetchall() or []:
                sa = float(row.get("sa") or 0)
                gp = float(row.get("gp") or 0)
                if sa <= 0:
                    continue
                m_pct = gp / sa * 100.0
                sh_pct = (sa / tot_sa * 100.0) if tot_sa > 0 else 0.0
                if m_pct < low_thr and sh_pct > share_thr:
                    lc = row.get("category_large_code") or ""
                    ln = row.get("category_large") or ""
                    q = f"large_code={quote(str(lc), safe='')}&large_name={quote(str(ln), safe='')}"
                    items.append(
                        {
                            "type": "low_margin_category",
                            "icon": "warning",
                            "title": "低毛利大类",
                            "detail": f"{(row.get('category_large') or row.get('category_large_code') or '')} 毛利率 {m_pct:.1f}%，"
                            f"销额占比 {sh_pct:.1f}%",
                            "link": f"htma://analysis?{q}",
                        }
                    )
    except Exception:
        pass
    negc = _negative_sku_count(cur, s, e, sq, sprefix)
    if negc > neg_thr:
        items.append(
            {
                "type": "negative_sku",
                "icon": "error",
                "title": f"负毛利 SKU 数过多（{negc}）",
                "detail": f"近区间负毛利且销售额>0 的 SKU 种数 {negc}，超过阈值 {neg_thr}。",
                "link": "/pages/index/index",
            }
        )
    try:
        conn2 = get_conn()
        ucur = conn2.cursor()
        try:
            ulist = get_unmapped_categories(conn2, s, e, store_id=store_for_unmapped) or []
        finally:
            try:
                conn2.close()
            except Exception:
                pass
    except Exception:
        ulist = []
    if ulist:
        sample = (ulist[0].get("category_large") or ulist[0].get("category_large_code") or "")[:20]
        items.append(
            {
                "type": "unmapped_labor",
                "icon": "info",
                "title": "存在未配置人力映射的大类",
                "detail": f"共 {len(ulist)} 条，如：{sample}…",
                "link": "/pages/labor/index",
            }
        )
    return items


def _build_alerts_preview(cur, s, e, store_for_unmapped, sq, sprefix, n=3):
    full = _alerts_list(cur, s, e, store_for_unmapped, sq, sprefix)
    return full[:n], full


def _api_mobile_dashboard_body():
    days = _parse_days(30, 365)
    s, e = _date_range_by_days(days)
    sq, sprefix = mobile_store_sql_prefix()
    conn = get_conn()
    out = {
        "range": {"start_date": s, "end_date": e, "days": days},
        "kpi": {},
        "top_categories": [],
        "negative_margin_sku_count": 0,
        "alerts_preview": [],
        "alerts": [],
        "labor_hint": None,
        "data_source": "t_htma_sale",
        "store_scope": "all" if not sq else "single",
        "stats_as_of": None,
    }
    try:
        cur = conn.cursor()
        if _has_t_htma_sale_table(cur):
            try:
                cur.execute(
                    "SELECT MAX(data_date) AS mx FROM t_htma_sale WHERE 1=1 " + sq,
                    tuple(sprefix),
                )
                mx = (cur.fetchone() or {}).get("mx")
                if mx is not None:
                    out["stats_as_of"] = (
                        mx.isoformat()[:10] if hasattr(mx, "isoformat") else str(mx)[:10]
                    )
            except Exception:
                pass
        elif _has_daily_category_stats_table(cur):
            out["stats_as_of"] = _stats_max_date(cur, sq, sprefix)
        used_stats = False
        # KPI 与首页一致：优先 t_htma_sale，避免预聚合未刷新时销售额明显偏低
        if _has_t_htma_sale_table(cur):
            try:
                qsum2 = (
                    "SELECT COALESCE(SUM(sale_amount), 0) AS sa, COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS gp "
                    "FROM t_htma_sale WHERE data_date BETWEEN %s AND %s " + sq
                )
                cur.execute(qsum2, (s, e) + tuple(sprefix))
                r1 = cur.fetchone() or {}
                sa, gpv = float(r1.get("sa") or 0), float(r1.get("gp") or 0)
                used_stats = True
                out["data_source"] = "t_htma_sale"
                out["kpi"] = {
                    "total_sale_amount": round(sa, 2),
                    "total_gross_profit": round(gpv, 2),
                    "avg_profit_rate_pct": round(gpv / sa * 100, 2) if sa > 0 else 0,
                }
                qtop2 = (
                    "SELECT COALESCE(NULLIF(TRIM(category_large), ''), '未分类') AS nm, SUM(sale_amount) AS sa "
                    "FROM t_htma_sale WHERE data_date BETWEEN %s AND %s " + sq
                    + " GROUP BY nm ORDER BY sa DESC LIMIT 5"
                )
                cur.execute(qtop2, (s, e) + tuple(sprefix))
                for row in cur.fetchall() or []:
                    out["top_categories"].append(
                        {
                            "name": row.get("nm") or "",
                            "sale_amount": round(float(row.get("sa") or 0), 2),
                        }
                    )
            except Exception:
                used_stats = False
        if not used_stats and _has_daily_category_stats_table(cur):
            try:
                qsum = (
                    "SELECT COALESCE(SUM(sale_amount), 0) AS sa, COALESCE(SUM(gross_profit), 0) AS gp "
                    "FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq
                )
                cur.execute(qsum, (s, e) + tuple(sprefix))
                r0 = cur.fetchone() or {}
                sa0, gp0 = float(r0.get("sa") or 0), float(r0.get("gp") or 0)
                if sa0 > 0 or gp0 > 0:
                    used_stats = True
                    out["data_source"] = "daily_category_stats"
                    out["kpi"] = {
                        "total_sale_amount": round(sa0, 2),
                        "total_gross_profit": round(gp0, 2),
                        "avg_profit_rate_pct": round(gp0 / sa0 * 100, 2) if sa0 > 0 else 0,
                    }
                    qtop = (
                        "SELECT category_large_code, MAX(category_large) AS nm, SUM(sale_amount) AS sa "
                        "FROM daily_category_stats "
                        "WHERE data_date BETWEEN %s AND %s " + sq
                        + " GROUP BY category_large_code ORDER BY sa DESC LIMIT 5"
                    )
                    cur.execute(qtop, (s, e) + tuple(sprefix))
                    for row in cur.fetchall() or []:
                        out["top_categories"].append(
                            {
                                "name": row.get("nm") or "",
                                "sale_amount": round(float(row.get("sa") or 0), 2),
                            }
                        )
            except Exception:
                used_stats = False
        if not used_stats:
            qsum2 = (
                "SELECT COALESCE(SUM(sale_amount), 0) AS sa, COALESCE(SUM(COALESCE(gross_profit, 0)), 0) AS gp "
                "FROM t_htma_sale WHERE data_date BETWEEN %s AND %s " + sq
            )
            cur.execute(qsum2, (s, e) + tuple(sprefix))
            r1 = cur.fetchone() or {}
            sa, gpv = float(r1.get("sa") or 0), float(r1.get("gp") or 0)
            out["kpi"] = {
                "total_sale_amount": round(sa, 2),
                "total_gross_profit": round(gpv, 2),
                "avg_profit_rate_pct": round(gpv / sa * 100, 2) if sa > 0 else 0,
            }
            qtop2 = (
                "SELECT COALESCE(NULLIF(TRIM(category_large), ''), '未分类') AS nm, SUM(sale_amount) AS sa "
                "FROM t_htma_sale WHERE data_date BETWEEN %s AND %s " + sq
                + " GROUP BY nm ORDER BY sa DESC LIMIT 5"
            )
            cur.execute(qtop2, (s, e) + tuple(sprefix))
            for row in cur.fetchall() or []:
                out["top_categories"].append(
                    {
                        "name": row.get("nm") or "",
                        "sale_amount": round(float(row.get("sa") or 0), 2),
                    }
                )
        out["negative_margin_sku_count"] = _negative_sku_count(cur, s, e, sq, sprefix)
        st_al = _alerts_effective_store_id()
        prev, all_al = _build_alerts_preview(cur, s, e, st_al, sq, sprefix, 3)
        out["alerts_preview"] = prev
        out["alerts"] = all_al
    finally:
        try:
            conn.close()
        except Exception:
            pass
    d = {**out, "success": True}
    d["data_source"] = d.get("data_source")  # 明确
    return mobile_ok(
        d,
        msg="",
    )


mobile_bp = Blueprint("mobile", __name__, url_prefix="/api/mobile")


def register_mobile_routes(app):
    from mobile_bi import register_mobile_bi_routes

    register_mobile_bi_routes(mobile_bp)
    app.register_blueprint(mobile_bp)


@mobile_bp.before_request
def _mobile_require_context():
    if request.method == "OPTIONS":
        return None
    rv = resolve_mobile_context()
    if rv is not None:
        body, code = rv
        return body, code
    return None


@mobile_bp.route("/dashboard", methods=["GET", "OPTIONS"])
@mobile_cached
def api_mobile_dashboard():
    if request.method == "OPTIONS":
        return "", 204
    try:
        return _api_mobile_dashboard_body()
    except Exception as e:
        return mobile_err(str(e), code=2, http=500)


@mobile_bp.route("/category_large", methods=["GET", "OPTIONS"])
@mobile_cached
def api_mobile_category_large():
    if request.method == "OPTIONS":
        return "", 204
    start_d, end_d = _date_range_by_days(_parse_days(30, 365))
    s = _parse_yyyy_mm_dd("start_date", start_d)
    e = _parse_yyyy_mm_dd("end_date", end_d)
    if s > e:
        s, e = e, s
    sq, sprefix = mobile_store_sql_prefix()
    conn = get_conn()
    try:
        cur = conn.cursor()
        if not _has_daily_category_stats_table(cur):
            return mobile_err("daily_category_stats 表不存在", code=1, http=501)
        use_sale = use_sale_aggregates(cur)
        if use_sale:
            raw = fetch_category_large_rows(cur, s, e, sq, sprefix)
            src = "t_htma_sale"
            stats_as_of = sale_max_data_date(cur, sq, sprefix)
        else:
            cur.execute(
                """
                SELECT category_large_code,
                       MAX(category_large) AS category_large,
                       COALESCE(SUM(sale_amount),0) AS sale_amount,
                       COALESCE(SUM(gross_profit),0) AS gross_profit,
                       COALESCE(SUM(sale_qty),0) AS sale_qty
                FROM daily_category_stats
                WHERE data_date BETWEEN %s AND %s
                """
                + sq
                + " GROUP BY category_large_code ORDER BY sale_amount DESC",
                (s, e) + tuple(sprefix),
            )
            raw = list(cur.fetchall() or [])
            src = "daily_category_stats"
            stats_as_of = _stats_max_date(cur, sq, sprefix)
        rows = []
        for r in raw:
            sa = float(r.get("sale_amount") or 0)
            gp = float(r.get("gross_profit") or 0)
            m = round(gp / sa * 100, 2) if sa > 0 else 0.0
            rows.append(
                {
                    "category_large_code": r.get("category_large_code") or "",
                    "category_large": r.get("category_large") or "",
                    "sale_amount": round(sa, 2),
                    "gross_profit": round(gp, 2),
                    "margin_pct": m,
                    "sale_qty": float(r.get("sale_qty") or 0),
                }
            )
    finally:
        conn.close()
    return mobile_ok(
        {
            "items": rows,
            "range": {"start_date": s, "end_date": e},
            "data_source": src,
            "stats_as_of": stats_as_of,
        }
    )


@mobile_bp.route("/category_mid", methods=["GET", "OPTIONS"])
@mobile_cached
def api_mobile_category_mid():
    if request.method == "OPTIONS":
        return "", 204
    large_code = (request.args.get("category_large_code") or "").strip()
    if not large_code:
        return mobile_err("category_large_code 必填", code=1, http=400)
    start_d, end_d = _date_range_by_days(_parse_days(30, 365))
    s = _parse_yyyy_mm_dd("start_date", start_d)
    e = _parse_yyyy_mm_dd("end_date", end_d)
    if s > e:
        s, e = e, s
    sq, sprefix = mobile_store_sql_prefix()
    conn = get_conn()
    src = "daily_category_stats"
    try:
        cur = conn.cursor()
        if not _has_daily_category_stats_table(cur):
            return mobile_err("daily_category_stats 表不存在", code=1, http=501)
        use_sale = use_sale_aggregates(cur)
        mid_from_sale = fetch_category_mid_rows(cur, s, e, sq, sprefix, large_code) if use_sale else None
        if mid_from_sale is not None:
            raw = mid_from_sale
            src = "t_htma_sale"
            stats_as_of = sale_max_data_date(cur, sq, sprefix)
        else:
            cur.execute(
                """
                SELECT category_mid_code,
                       MAX(category_mid) AS category_mid,
                       COALESCE(SUM(sale_amount),0) AS sale_amount,
                       COALESCE(SUM(gross_profit),0) AS gross_profit,
                       COALESCE(SUM(sale_qty),0) AS sale_qty
                FROM daily_category_stats
                WHERE data_date BETWEEN %s AND %s
                  AND category_large_code = %s
                """
                + sq
                + " GROUP BY category_mid_code ORDER BY sale_amount DESC",
                (s, e, large_code) + tuple(sprefix),
            )
            raw = list(cur.fetchall() or [])
            src = "daily_category_stats"
            stats_as_of = _stats_max_date(cur, sq, sprefix)
        rows = []
        for r in raw:
            sa = float(r.get("sale_amount") or 0)
            gp = float(r.get("gross_profit") or 0)
            m = round(gp / sa * 100, 2) if sa > 0 else 0.0
            rows.append(
                {
                    "category_mid_code": r.get("category_mid_code") or "",
                    "category_mid": r.get("category_mid") or "",
                    "sale_amount": round(sa, 2),
                    "gross_profit": round(gp, 2),
                    "margin_pct": m,
                    "sale_qty": float(r.get("sale_qty") or 0),
                }
            )
    finally:
        conn.close()
    return mobile_ok(
        {
            "items": rows,
            "category_large_code": large_code,
            "range": {"start_date": s, "end_date": e},
            "data_source": src,
            "stats_as_of": stats_as_of,
        }
    )


def _sale_has_col(cur, col: str) -> bool:
    try:
        cur.execute(
            "SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 't_htma_sale' AND COLUMN_NAME = %s LIMIT 1",
            (col,),
        )
        return bool(cur.fetchone())
    except Exception:
        return False


@mobile_bp.route("/category_small", methods=["GET", "OPTIONS"])
@mobile_cached
def api_mobile_category_small():
    if request.method == "OPTIONS":
        return "", 204
    large_code = (request.args.get("category_large_code") or "").strip()
    mid_code = (request.args.get("category_mid_code") or "").strip()
    if not large_code or not mid_code:
        return mobile_err("category_large_code 与 category_mid_code 均必填", code=1, http=400)
    start_d, end_d = _date_range_by_days(_parse_days(30, 365))
    s = _parse_yyyy_mm_dd("start_date", start_d)
    e = _parse_yyyy_mm_dd("end_date", end_d)
    if s > e:
        s, e = e, s
    sq, sprefix = mobile_store_sql_prefix()
    conn = get_conn()
    rows = []
    note = ""
    try:
        cur = conn.cursor()
        if not _sale_has_col(cur, "sku_code"):
            return mobile_ok(
                {"items": [], "note": "t_htma_sale 无 sku_code 列", "range": {"start_date": s, "end_date": e}}
            )
        has_sc = _sale_has_col(cur, "category_small_code")
        has_sn = _sale_has_col(cur, "category_small")
        if not has_sn and not has_sc:
            return mobile_ok(
                {"items": [], "note": "t_htma_sale 无小类字段", "range": {"start_date": s, "end_date": e}}
            )
        grp = (
            "COALESCE(NULLIF(TRIM(category_small_code), ''), TRIM(category_small), '')"
            if has_sc
            else "TRIM(COALESCE(category_small, ''))"
        )
        nm_sel = "MAX(category_small)" if has_sn else "MAX(TRIM(category_small))"
        wh = (
            "FROM t_htma_sale WHERE data_date BETWEEN %s AND %s "
            + sq
            + " AND category_large_code = %s AND category_mid_code = %s"
        )
        params = (s, e) + tuple(sprefix) + (large_code, mid_code)
        cur.execute(
            f"SELECT {grp} AS category_small_code, {nm_sel} AS category_small, "
            "COALESCE(SUM(sale_amount),0) AS sale_amount, "
            "COALESCE(SUM(gross_profit),0) AS gross_profit, "
            "COALESCE(SUM(sale_qty),0) AS sale_qty "
            + wh
            + f" GROUP BY {grp} HAVING SUM(sale_amount) > 0.01 ORDER BY sale_amount DESC LIMIT 200",
            params,
        )
        for r in cur.fetchall() or []:
            sa = float(r.get("sale_amount") or 0)
            gp = float(r.get("gross_profit") or 0)
            m = round(gp / sa * 100, 2) if sa > 0 else 0.0
            rows.append(
                {
                    "category_small_code": (r.get("category_small_code") or "").strip(),
                    "category_small": (r.get("category_small") or "").strip() or "未分类",
                    "sale_amount": round(sa, 2),
                    "gross_profit": round(gp, 2),
                    "margin_pct": m,
                    "sale_qty": float(r.get("sale_qty") or 0),
                }
            )
    except Exception as ex:
        note = str(ex)[:200]
    finally:
        conn.close()
    return mobile_ok(
        {
            "items": rows,
            "category_large_code": large_code,
            "category_mid_code": mid_code,
            "range": {"start_date": s, "end_date": e},
            "data_source": "t_htma_sale",
            "note": note,
        }
    )


@mobile_bp.route("/category_skus", methods=["GET", "OPTIONS"])
@mobile_cached
def api_mobile_category_skus():
    if request.method == "OPTIONS":
        return "", 204
    large_code = (request.args.get("category_large_code") or "").strip()
    mid_code = (request.args.get("category_mid_code") or "").strip()
    small_code = (request.args.get("category_small_code") or "").strip()
    if not large_code or not mid_code:
        return mobile_err("category_large_code 与 category_mid_code 均必填", code=1, http=400)
    start_d, end_d = _date_range_by_days(_parse_days(30, 365))
    s = _parse_yyyy_mm_dd("start_date", start_d)
    e = _parse_yyyy_mm_dd("end_date", end_d)
    if s > e:
        s, e = e, s
    sq, sprefix = mobile_store_sql_prefix()
    conn = get_conn()
    items = []
    note = ""
    try:
        cur = conn.cursor()
        if not _sale_has_col(cur, "sku_code"):
            return mobile_ok({"items": [], "note": "t_htma_sale 无 sku_code"})
        has_pn = _sale_has_col(cur, "product_name")
        name_sel = "COALESCE(NULLIF(TRIM(product_name),''), sku_code)" if has_pn else "sku_code"
        wh = (
            "FROM t_htma_sale WHERE data_date BETWEEN %s AND %s "
            + sq
            + " AND category_large_code = %s AND category_mid_code = %s"
        )
        params = [s, e] + list(sprefix) + [large_code, mid_code]
        has_sc = _sale_has_col(cur, "category_small_code")
        has_sn = _sale_has_col(cur, "category_small")
        if small_code:
            if has_sc:
                wh += " AND COALESCE(NULLIF(TRIM(category_small_code),''), TRIM(category_small), '') = %s"
                params.append(small_code)
            elif has_sn:
                wh += " AND TRIM(COALESCE(category_small,'')) = %s"
                params.append(small_code)
        q = (
            f"SELECT sku_code, MAX({name_sel}) AS nm, "
            "COALESCE(SUM(sale_amount),0) AS sa, COALESCE(SUM(gross_profit),0) AS gp, "
            "COALESCE(SUM(sale_qty),0) AS qty "
            + wh
            + " GROUP BY sku_code HAVING SUM(sale_amount) > 0.01 ORDER BY sa DESC LIMIT 100"
        )
        cur.execute(q, tuple(params))
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
    except Exception as ex:
        note = str(ex)[:200]
    finally:
        conn.close()
    return mobile_ok(
        {
            "items": items,
            "category_large_code": large_code,
            "category_mid_code": mid_code,
            "category_small_code": small_code or None,
            "range": {"start_date": s, "end_date": e},
            "data_source": "t_htma_sale",
            "note": note,
        }
    )


@mobile_bp.route("/trend", methods=["GET", "OPTIONS"])
@mobile_cached
def api_mobile_trend():
    if request.method == "OPTIONS":
        return "", 204
    metric = (request.args.get("metric") or "sale").strip().lower()
    if metric not in ("sale", "profit", "margin"):
        return mobile_err("metric 须为 sale|profit|margin", code=1, http=400)
    days = _parse_days(30, 90)
    end_d = date.today()
    start_d = end_d - timedelta(days=days - 1)
    s, e = start_d.isoformat(), end_d.isoformat()
    sq, sprefix = mobile_store_sql_prefix()
    conn = get_conn()
    src = "daily_category_stats"
    try:
        cur = conn.cursor()
        if not _has_daily_category_stats_table(cur):
            return mobile_err("daily_category_stats 表不存在", code=1, http=501)
        use_sale = use_sale_aggregates(cur)
        if use_sale:
            day_rows = fetch_day_series_sa_gp(cur, s, e, sq, sprefix)
            src = "t_htma_sale"
            stats_as_of = sale_max_data_date(cur, sq, sprefix)
        else:
            cur.execute(
                """
                SELECT data_date,
                       COALESCE(SUM(sale_amount),0) AS sa,
                       COALESCE(SUM(gross_profit),0) AS gp
                FROM daily_category_stats
                WHERE data_date BETWEEN %s AND %s
                """
                + sq
                + " GROUP BY data_date ORDER BY data_date",
                (s, e) + tuple(sprefix),
            )
            day_rows = list(cur.fetchall() or [])
            src = "daily_category_stats"
            stats_as_of = _stats_max_date(cur, sq, sprefix)
        dmap = {}
        for r in day_rows:
            dx = r.get("data_date")
            if hasattr(dx, "isoformat"):
                ds = dx.isoformat()[:10]
            else:
                ds = str(dx)[:10]
            dmap[ds] = {
                "sa": float(r.get("sa") or 0),
                "gp": float(r.get("gp") or 0),
            }
        out_dates = []
        out_val = []
        d0 = start_d
        while d0 <= end_d:
            ds = d0.isoformat()
            o = dmap.get(ds, {"sa": 0.0, "gp": 0.0})
            sa, gpv = o["sa"], o["gp"]
            if metric == "sale":
                v = sa
            elif metric == "profit":
                v = gpv
            else:
                v = round(gpv / sa * 100, 4) if sa > 0 else 0.0
            out_dates.append(ds)
            out_val.append(v)
            d0 = d0 + timedelta(days=1)
    finally:
        conn.close()
    return mobile_ok(
        {
            "metric": metric,
            "days": days,
            "dates": out_dates,
            "values": out_val,
            "data_source": src,
            "stats_as_of": stats_as_of,
        }
    )


@mobile_bp.route("/alerts", methods=["GET", "OPTIONS"])
@mobile_cached
def api_mobile_alerts():
    if request.method == "OPTIONS":
        return "", 204
    days = _parse_days(30, 365)
    s, e = _date_range_by_days(days)
    sq, sprefix = mobile_store_sql_prefix()
    st = _alerts_effective_store_id()
    conn = get_conn()
    dsrc = "daily_category_stats"
    try:
        cur = conn.cursor()
        items = _alerts_list(cur, s, e, st, sq, sprefix)
        us = use_sale_aggregates(cur)
        if us:
            stats_as_of = sale_max_data_date(cur, sq, sprefix)
            dsrc = "t_htma_sale"
        else:
            stats_as_of = _stats_max_date(cur, sq, sprefix) if _has_daily_category_stats_table(cur) else ""
            dsrc = "daily_category_stats"
    finally:
        conn.close()
    return mobile_ok(
        {
            "items": items,
            "range": {"start_date": s, "end_date": e, "store_id": st},
            "data_source": dsrc,
            "stats_as_of": stats_as_of,
        }
    )


@mobile_bp.route("/labor_summary", methods=["GET", "OPTIONS"])
@mobile_cached
def api_mobile_labor_summary():
    if request.method == "OPTIONS":
        return "", 204
    start_d, end_d = _date_range_by_days(_parse_days(30, 120))
    s = _parse_yyyy_mm_dd("start_date", start_d)
    e = _parse_yyyy_mm_dd("end_date", end_d)
    if s > e:
        s, e = e, s
    sid = _labor_store_id_param()
    conn = get_conn()
    try:
        ov = _labor_analysis_overview(conn, s, e, store_id=sid)
        rows = _labor_analysis_by_category(conn, s, e, store_id=sid) or []
        points = []
        for r in rows:
            sale = float(r.get("sale") or 0)
            profit = float(r.get("profit") or 0)
            labor = float(r.get("labor_cost") or 0)
            if profit <= 0:
                continue
            m_pct = float(r.get("margin_pct") or (profit / sale * 100.0 if sale > 0 else 0.0))
            intensity = labor / profit if profit else 0.0
            points.append(
                {
                    "category": r.get("category") or r.get("category_large_code") or "",
                    "category_large_code": r.get("category_large_code") or "",
                    "margin_pct": round(m_pct, 2),
                    "labor_intensity": round(intensity, 4),
                }
            )
        mx = statistics.median([p["margin_pct"] for p in points]) if points else 0.0
        my = statistics.median([p["labor_intensity"] for p in points]) if points else 0.0
        q3 = [
            p
            for p in points
            if p["margin_pct"] < mx and p["labor_intensity"] > my and p["labor_intensity"] > 0
        ]
        quad_hint = "四象限：以毛利率与人力/毛利为轴；低于中位毛利率且高于中位人力强度的大类为「低毛利高人力」关注区。" if points else "样本不足，无法生成四象限结论。"
    finally:
        conn.close()
    data = {
        "total_labor_cost": ov.get("total_cost"),
        "operational_cost": ov.get("operational_cost"),
        "management_cost": ov.get("management_cost"),
        "total_sales": ov.get("total_sale"),
        "total_gross_profit": ov.get("total_profit"),
        "profit_cost_ratio": ov.get("profit_cost_ratio"),
        "sales_per_capita": ov.get("sales_per_capita"),
        "low_margin_high_labor_categories": q3[:20],
        "quadrant_median": {"margin_pct": round(mx, 2), "labor_intensity": round(my, 4)},
        "quadrant_summary": quad_hint,
        "data_source": "labor + t_htma_sale (store filter by JWT)",
        "stats_as_of": e,
    }
    try:
        from mobile_bi import augment_labor_summary_extras

        data.update(augment_labor_summary_extras(s, e, sid, dict(ov or {})))
    except Exception:
        pass
    return mobile_ok(data)
