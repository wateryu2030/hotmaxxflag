# -*- coding: utf-8 -*-
"""指标语义层：与小程序 / Web 共用的纯计算逻辑（无 Flask 依赖）。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Tuple


def daterange_prev_period(s: date, e: date) -> Tuple[date, date]:
    """与 mobile_bi._prev_range 一致：等长上一段日期（用于环比）。"""
    n = (e - s).days + 1
    pe = s - timedelta(days=1)
    ps = pe - timedelta(days=n - 1)
    return ps, pe


def _row_sa(row: Any) -> float:
    if row is None:
        return 0.0
    if isinstance(row, dict):
        return float(row.get("sa") or row.get("sale_amount") or 0)
    return float(getattr(row, "sa", 0) or getattr(row, "sale_amount", 0) or 0)


def _row_code(row: Any) -> str:
    if row is None:
        return ""
    if isinstance(row, dict):
        return str(row.get("category_large_code") or "").strip()
    return str(getattr(row, "category_large_code", "") or "").strip()


def _row_name(row: Any) -> str:
    if row is None:
        return ""
    if isinstance(row, dict):
        return str(row.get("category_large") or row.get("nm") or row.get("category_large_code") or "").strip()
    return str(getattr(row, "category_large", None) or getattr(row, "nm", "") or "").strip()


ATTRIBUTION_LARGE_SQL = (
    "SELECT category_large_code, MAX(category_large) AS category_large, "
    "COALESCE(SUM(sale_amount),0) AS sa FROM daily_category_stats "
    "WHERE data_date BETWEEN %s AND %s "
)


def fetch_category_large_sales_aggregates(cur, s_iso: str, e_iso: str, sq: str, sp: Tuple[Any, ...]):
    """按大类聚合销售额；sq 为门店等 AND 片段（与 mobile_store_sql_prefix 一致）。"""
    cur.execute(
        ATTRIBUTION_LARGE_SQL + sq + " GROUP BY category_large_code HAVING sa > 0.0001",
        (s_iso, e_iso) + tuple(sp),
    )
    return cur.fetchall() or []


def merge_category_large_sales_mom_attribution(
    rows_prev: List[Any], rows_cur: List[Any]
) -> Dict[str, Any]:
    """
    大类销售额环比归因：各品类对「总销售额增量」的贡献 = 该品类本期-上期销售额。
    返回瀑布图所需 steps + 明细表。
    """
    prev_map: Dict[str, Dict[str, Any]] = {}
    for r in rows_prev or []:
        c = _row_code(r)
        if not c:
            continue
        prev_map[c] = {"code": c, "name": _row_name(r) or c, "sale": _row_sa(r)}
    cur_map: Dict[str, Dict[str, Any]] = {}
    for r in rows_cur or []:
        c = _row_code(r)
        if not c:
            continue
        cur_map[c] = {"code": c, "name": _row_name(r) or c, "sale": _row_sa(r)}
    codes = sorted(set(prev_map.keys()) | set(cur_map.keys()))
    prev_total = sum(v["sale"] for v in prev_map.values())
    cur_total = sum(v["sale"] for v in cur_map.values())
    delta_total = cur_total - prev_total

    table: List[Dict[str, Any]] = []
    for c in codes:
        sp = float(prev_map.get(c, {}).get("sale") or 0)
        sc = float(cur_map.get(c, {}).get("sale") or 0)
        nm = (cur_map.get(c) or prev_map.get(c) or {}).get("name") or c
        d = sc - sp
        share = (d / delta_total * 100.0) if delta_total and abs(delta_total) > 1e-9 else 0.0
        table.append(
            {
                "category_large_code": c,
                "category_large": nm,
                "sale_prev": round(sp, 2),
                "sale_cur": round(sc, 2),
                "delta": round(d, 2),
                "share_of_total_delta_pct": round(share, 2),
            }
        )
    table.sort(key=lambda x: abs(x["delta"]), reverse=True)

    steps: List[Dict[str, Any]] = [
        {"kind": "total", "label": "上期销售额", "value": round(prev_total, 2), "code": ""},
    ]
    for row in table:
        if abs(row["delta"]) < 1e-6:
            continue
        steps.append(
            {
                "kind": "delta",
                "label": row["category_large"] or row["category_large_code"],
                "value": round(row["delta"], 2),
                "code": row["category_large_code"],
            }
        )
    steps.append({"kind": "total", "label": "本期销售额", "value": round(cur_total, 2), "code": ""})

    return {
        "prev_total": round(prev_total, 2),
        "cur_total": round(cur_total, 2),
        "delta_total": round(delta_total, 2),
        "delta_pct_prev": round(delta_total / prev_total * 100.0, 2) if prev_total > 1e-9 else None,
        "by_category": table,
        "waterfall_steps": steps,
        "metric": "sale_amount",
        "granularity": "category_large",
    }


def _margin_pct(gp: float, sa: float) -> float:
    sa = float(sa or 0)
    if sa <= 1e-9:
        return 0.0
    return round(float(gp or 0) / sa * 100.0, 4)


def _pop_mean_std(values: List[float]) -> Tuple[float, float]:
    """总体标准差（ddof=0）；长度<2 时 std=0。"""
    xs = [float(x) for x in values if x is not None]
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    mu = sum(xs) / n
    if n < 2:
        return mu, 0.0
    var = sum((x - mu) ** 2 for x in xs) / n
    return mu, var**0.5


def zscore_last_vs_history(values: List[float]) -> Optional[float]:
    """
    用除最后一项外的子序列估计均值/标准差，对最后一项算 Z。
    历史长度<2 或 std 过小返回 None。
    """
    if len(values) < 2:
        return None
    hist, last = values[:-1], values[-1]
    mu, sd = _pop_mean_std(hist)
    if sd < 1e-6:
        return None
    return (float(last) - mu) / sd


def moving_average(values: List[float], window: int) -> List[float]:
    """简单 trailing MA；不足 window 的位置用已有长度平均。"""
    if not values:
        return []
    out: List[float] = []
    w = max(1, int(window))
    for i in range(len(values)):
        lo = max(0, i - w + 1)
        chunk = values[lo : i + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def total_sales_ma7_slope_pct(daily_total_sales: List[float]) -> Optional[float]:
    """
    全店日销额序列（按时间升序）上，最近 7 日均值相对「其前一日的 7 日均值」的环比变化率（%）。
    至少需要 14 个点才有意义；否则返回 None。
    """
    xs = [float(x or 0) for x in daily_total_sales]
    if len(xs) < 14:
        return None
    ma = moving_average(xs, 7)
    last_ma = ma[-1]
    prev_ma = ma[-8] if len(ma) >= 8 else None
    if prev_ma is None or abs(prev_ma) < 1e-6:
        return None
    return round((last_ma - prev_ma) / prev_ma * 100.0, 2)


def compute_large_category_insights(
    daily_large_rows: List[Dict[str, Any]],
    *,
    z_threshold: float = 2.0,
    min_hist_days: int = 5,
    min_last_sales: float = 500.0,
) -> Dict[str, Any]:
    """
    基于 daily_category_stats 按日×大类聚合后的行列表（字段含 data_date, category_large_code,
    category_large, sa/sale_amount, gp/gross_profit）。

    输出：
    - margin_zscore_hits: 最近一日毛利率相对自身历史异常偏低（Z 负向超阈）且销额达标的大类（利润侵蚀风险）
    - margin_zscore_high: 毛利率异常偏高（可选看定价/结构）
    - sales_ma7_slope_pct: 全店日销额 7 日均线动量
    """
    from collections import defaultdict

    by: Dict[str, List[Tuple[str, float, float]]] = defaultdict(list)
    for r in daily_large_rows or []:
        code = str(r.get("category_large_code") or "").strip()
        if not code:
            continue
        nm = str(r.get("category_large") or code).strip()
        d = r.get("data_date")
        ds = d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]
        sa = float(r.get("sa") or r.get("sale_amount") or 0)
        gp = float(r.get("gp") or r.get("gross_profit") or 0)
        by[code].append((ds, sa, gp))
    hits_low: List[Dict[str, Any]] = []
    hits_high: List[Dict[str, Any]] = []
    for code, triples in by.items():
        triples.sort(key=lambda x: x[0])
        margins: List[float] = []
        sales: List[float] = []
        dates: List[str] = []
        for ds, sa, gp in triples:
            dates.append(ds)
            sales.append(sa)
            margins.append(_margin_pct(gp, sa))
        if len(margins) < min_hist_days + 1:
            continue
        last_sa = sales[-1]
        if last_sa < min_last_sales:
            continue
        z = zscore_last_vs_history(margins)
        if z is None:
            continue
        last_name = code
        for r in daily_large_rows or []:
            if str(r.get("category_large_code") or "").strip() != code:
                continue
            d = r.get("data_date")
            ds = d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]
            if ds == dates[-1]:
                last_name = str(r.get("category_large") or code).strip()
                break
        last_m = margins[-1]
        item = {
            "category_large_code": code,
            "category_large": last_name,
            "latest_date": dates[-1],
            "latest_margin_pct": round(last_m, 2),
            "zscore_margin": round(z, 2),
            "latest_sales": round(last_sa, 2),
        }
        if z <= -float(z_threshold):
            hits_low.append(item)
        elif z >= float(z_threshold):
            hits_high.append(item)
    hits_low.sort(key=lambda x: x["zscore_margin"])
    hits_high.sort(key=lambda x: -x["zscore_margin"])

    # 全店按日总销额
    by_day: Dict[str, float] = defaultdict(float)
    for r in daily_large_rows or []:
        d = r.get("data_date")
        ds = d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]
        sa = float(r.get("sa") or r.get("sale_amount") or 0)
        by_day[ds] += sa
    ordered_dates = sorted(by_day.keys())
    totals = [by_day[d] for d in ordered_dates]
    slope = total_sales_ma7_slope_pct(totals)

    return {
        "margin_zscore_low": hits_low[:8],
        "margin_zscore_high": hits_high[:5],
        "sales_ma7_slope_pct": slope,
        "daily_points_used": len(ordered_dates),
        "categories_tracked": len(by),
    }
