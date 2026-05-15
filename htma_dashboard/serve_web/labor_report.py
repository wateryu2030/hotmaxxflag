# -*- coding: utf-8 -*-
"""
人力分析报告 Blueprint：3个核心 API
三级人力模型：
  一级：店面总览（overview）
  二级：品类分摊（by_category）— 经营岗映射 + 通用岗按销售额占比分摊 + 管理岗独立列示
  三级：人员画像（persons）— 每人品类归属 + 人效等级
"""
import os
from datetime import date
from calendar import monthrange

from flask import Blueprint, jsonify, request
from db_config import get_conn
from labor_utils import (
    labor_analysis_mapping_effective_for_month as _mapping_for_month,
    labor_analysis_position_matches_mapping as _pos_matches,
)

labor_report_bp = Blueprint("labor_report_api", __name__, url_prefix="/api/labor_report")
STORE_ID = os.environ.get("STORE_ID") or "沈阳超级仓"

# ── 三级人力模型：cost_type ──
# "direct" = 经营岗（直接映射到品类的人力投入）
# "shared" = 通用岗（收银、物流、保洁等服务于全场的岗位，按销售比例分摊）
# "management" = 管理岗（店长、HRBP等不直接服务于品类的管理成本，独立列示）
POSITION_TYPE_META = {
    "management": {"label": "管理岗", "level": "management"},
    "fulltime":  {"label": "全职",   "level": "shared"},
    "leader":    {"label": "组长",   "level": "shared"},
    "parttime":  {"label": "兼职",   "level": "shared"},
    "hourly":    {"label": "小时工",  "level": "shared"},
    "cleaner":   {"label": "保洁",   "level": "shared"},
}
# 明确属于通用岗的 position_name 前缀（不直接服务于具体经营品类）
SHARED_POSITION_PREFIXES = ["收银", "保洁", "物流", "保安", "售后", "HR", "陈列"]

# ── helpers ──────────────────────────────────────────────────────────

def _month_range(ym):
    parts = ym.split("-")
    y, m = int(parts[0]), int(parts[1])
    start = date(y, m, 1)
    _, last = monthrange(y, m)
    return start, date(y, m, last)

def _months_between(start_ym, end_ym):
    out = []
    sy, sm = int(start_ym[:4]), int(start_ym[5:7])
    ey, em = int(end_ym[:4]), int(end_ym[5:7])
    while (sy, sm) <= (ey, em):
        out.append(f"{sy:04d}-{sm:02d}")
        sm += 1
        if sm > 12: sm = 1; sy += 1
    return out

def _get_sale_profit_by_month(conn, month):
    start, end = _month_range(month)
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT COALESCE(SUM(sale_amount),0) AS s, COALESCE(SUM(gross_profit),0) AS p
            FROM t_htma_sale WHERE store_id = %s AND data_date BETWEEN %s AND %s
        """, (STORE_ID, start, end))
        r = cur.fetchone()
        return float(r.get("s", 0) or 0), float(r.get("p", 0) or 0)
    except Exception:
        return 0, 0
    finally:
        cur.close()

def _is_shared_position(pos):
    """判断岗位是否为通用岗（不直接服务于经营品类的岗位）"""
    pos_lower = pos.strip().lower()
    for prefix in SHARED_POSITION_PREFIXES:
        if pos_lower.startswith(prefix.lower()):
            return True
    return False

def _get_labor_by_month(conn, month):
    """按月返回人力明细并按三级模型分类：direct/shared/management"""
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT position_name, position_type, person_name, COALESCE(total_cost, company_cost, 0) AS cost,
                   work_hours, base_salary, performance
            FROM t_htma_labor_cost WHERE report_month = %s
        """, (month,))
        rows = cur.fetchall()
    except Exception:
        rows = []

    mapping = _mapping_for_month(conn, month)
    # 经营映射：position -> category key
    direct_mapping = {}
    mgr_set = set()
    for m in mapping:
        ct = (m.get("cost_type") or "").strip().lower()
        lab = (m.get("labor_position_name") or "").strip()
        mt = m.get("match_type") or "prefix"
        large_code = (m.get("sales_category_large_code") or "").strip()
        cat_name = (m.get("sales_category") or "").strip()
        key = large_code if large_code else cat_name
        if not key or key in ("--", "——", "-"):
            # cost_type=management 但无品类映射的记入管理岗集合
            if ct == "management":
                mgr_set.add((lab, mt))
            continue
        if ct == "management":
            # 管理岗但有品类编码的也记入管理岗集合
            mgr_set.add((lab, mt))
        else:
            # 经营岗映射
            if key not in direct_mapping:
                direct_mapping[key] = []
            direct_mapping[key].append((lab, mt))

    total_cost = 0.0
    management_cost = 0.0
    direct_cost = 0.0
    shared_cost = 0.0
    by_type_cost = {}
    by_type_count = {}
    persons = []
    person_seen = set()

    for r in rows:
        pos = (r.get("position_name") or "").strip()
        ptype = (r.get("position_type") or "").strip().lower()
        cost = float(r.get("cost") or 0)
        pname = (r.get("person_name") or "").strip()
        if not pname:
            continue
        total_cost += cost

        # 三级模型判定：管理岗 > 通用岗 > 经营岗
        # 先根据 position_type 兜底，避免 mapping 缺失时的错误分类
        if ptype == "management":
            cost_type = "management"
        elif ptype == "cleaner":
            cost_type = "shared"
        elif pos.startswith(("收银", "保洁", "物流")):
            cost_type = "shared"
        elif _is_shared_position(pos):
            cost_type = "shared"
        else:
            # 尝试经营映射
            matched_mgr = any(_pos_matches(pos, lab, mt) for lab, mt in mgr_set)
            if matched_mgr:
                cost_type = "management"
            else:
                # 有经营映射的算 direct，否则也算 shared
                has_direct = any(
                    any(_pos_matches(pos, lab, mt) for lab, mt in pos_list)
                    for pos_list in direct_mapping.values()
                )
                cost_type = "direct" if has_direct else "shared"

        if cost_type == "management":
            management_cost += cost
        elif cost_type == "direct":
            direct_cost += cost
        else:
            shared_cost += cost

        # 按岗位类型统计
        by_type_cost[ptype] = by_type_cost.get(ptype, 0) + cost
        by_type_count[ptype] = by_type_count.get(ptype, 0) + 1

        pkey = (month, pname)
        if pkey not in person_seen:
            person_seen.add(pkey)
            persons.append({
                "person_name": pname,
                "position_name": pos,
                "position_type": ptype,
                "total_cost": round(cost, 2),
                "cost_type": cost_type,
                "cost_type_label": {"direct": "经营岗", "shared": "通用岗", "management": "管理岗"}[cost_type],
                "work_hours": float(r.get("work_hours") or 0),
                "base_salary": float(r.get("base_salary") or 0),
                "performance": float(r.get("performance") or 0),
            })

    # 岗位类型标签
    for p in persons:
        meta = POSITION_TYPE_META.get(p["position_type"], {"label": "其他", "level": "shared"})
        p["position_type_label"] = meta["label"]

    # by_type 排序
    type_order = ["leader", "fulltime", "parttime", "hourly", "cleaner", "management"]
    by_type = {}
    for t in type_order:
        if t in by_type_count:
            by_type[t] = {"count": by_type_count[t], "cost": round(by_type_cost[t], 2)}
    for t in sorted(by_type_cost.keys()):
        if t not in by_type:
            by_type[t] = {"count": by_type_count[t], "cost": round(by_type_cost[t], 2)}

    mgmt_headcount = sum(1 for p in persons if p["cost_type"] == "management")
    direct_headcount = sum(1 for p in persons if p["cost_type"] == "direct")
    shared_headcount = sum(1 for p in persons if p["cost_type"] == "shared")

    return {
        "total_cost": round(total_cost, 2),
        "management_cost": round(management_cost, 2),
        "direct_cost": round(direct_cost, 2),
        "shared_cost": round(shared_cost, 2),
        "total_headcount": len(persons),
        "management_headcount": mgmt_headcount,
        "direct_headcount": direct_headcount,
        "shared_headcount": shared_headcount,
        "by_position_type": by_type,
        "persons": persons,
        "direct_mapping": direct_mapping,
    }


# ── API 1: /overview ────────────────────────────────────────────────

@labor_report_bp.route("/overview", methods=["GET", "OPTIONS"])
def api_overview():
    if request.method == "OPTIONS":
        return "", 204

    month_from = (request.args.get("month_from") or "").strip()
    month_to = (request.args.get("month_to") or "").strip()

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT MIN(report_month) AS min_m, MAX(report_month) AS max_m FROM t_htma_labor_cost")
        r = cur.fetchone()
        if not r or not r.get("min_m"):
            conn.close()
            return jsonify({"success": True, "months": [], "data": [], "trends": {}})
        min_month = month_from if month_from else r["min_m"]
        max_month = month_to if month_to else r["max_m"]
        months = _months_between(min_month, max_month)
    finally:
        cur.close()

    data = []
    trends = {"labor_cost": [], "labor_sale_ratio": [], "labor_profit_ratio": [],
              "sale_per_capita": [], "profit_per_cost": []}

    for m in months:
        sale, profit = _get_sale_profit_by_month(conn, m)
        labor = _get_labor_by_month(conn, m)
        tc = labor["total_cost"]
        row = {
            "month": m,
            "total_cost": tc,
            "management_cost": labor["management_cost"],
            "direct_cost": labor["direct_cost"],
            "shared_cost": labor["shared_cost"],
            "total_headcount": labor["total_headcount"],
            "management_headcount": labor["management_headcount"],
            "direct_headcount": labor["direct_headcount"],
            "shared_headcount": labor["shared_headcount"],
            "sale": round(sale, 2),
            "profit": round(profit, 2),
            "labor_sale_ratio": round(tc / sale * 100, 2) if sale else 0,
            "labor_profit_ratio": round(tc / profit * 100, 2) if profit else 0,
            "sale_per_capita": round(sale / labor["total_headcount"], 2) if labor["total_headcount"] else 0,
            "profit_per_cost": round(profit / tc, 4) if tc else 0,
            "by_position_type": labor["by_position_type"],
        }
        data.append(row)
        trends["labor_cost"].append(round(tc, 2))
        trends["labor_sale_ratio"].append(row["labor_sale_ratio"])
        trends["labor_profit_ratio"].append(row["labor_profit_ratio"])
        trends["sale_per_capita"].append(row["sale_per_capita"])
        trends["profit_per_cost"].append(row["profit_per_cost"])

    mom = {}
    for i in range(1, len(data)):
        prev = data[i - 1]["total_cost"]
        curr = data[i]["total_cost"]
        if prev:
            mom[f"{data[i]['month']}_cost_pct_change"] = round((curr - prev) / prev * 100, 2)
    trends["mom"] = mom

    conn.close()
    return jsonify({"success": True, "months": months, "data": data, "trends": trends})


# ── API 2: /by_category ─────────────────────────────────────────────

def _get_category_sales(conn, month):
    """返回该月所有大类的销售/毛利数据"""
    start, end = _month_range(month)
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT COALESCE(NULLIF(TRIM(category_large_code), ''), TRIM(category_large)) AS code,
                   COALESCE(MAX(TRIM(category_large)), '') AS cat,
                   COALESCE(SUM(sale_amount),0) AS s, COALESCE(SUM(gross_profit),0) AS p
            FROM t_htma_sale
            WHERE data_date BETWEEN %s AND %s AND store_id = %s
              AND (COALESCE(TRIM(category_large_code),'') != '' OR (category_large IS NOT NULL AND TRIM(category_large) != ''))
            GROUP BY 1 ORDER BY s DESC
        """, (start, end, STORE_ID))
        out = {}
        name_map = {}
        for r in cur.fetchall():
            code = (r.get("code") or "").strip()
            cat = (r.get("cat") or "").strip()
            s = float(r.get("s") or 0)
            p = float(r.get("p") or 0)
            out[code] = (s, p)
            name_map[code] = cat
        return out, name_map
    except Exception:
        return {}, {}
    finally:
        cur.close()

@labor_report_bp.route("/by_category", methods=["GET", "OPTIONS"])
def api_by_category():
    """按经营类目返回：原始映射 + 分摊后（通用岗按销售比例分摊）
    参数 ?share=true 开启分摊"""
    if request.method == "OPTIONS":
        return "", 204

    month = (request.args.get("month") or "").strip()
    share = (request.args.get("share") or "").strip().lower() in ("true", "1", "yes")

    conn = get_conn()
    cur = conn.cursor()
    try:
        if not month:
            cur.execute("SELECT MAX(report_month) FROM t_htma_labor_cost")
            r = cur.fetchone()
            month = r.get("MAX(report_month)") or list(r.values())[0] if not isinstance(r, dict) else None
            if not month:
                conn.close()
                return jsonify({"success": True, "month": None, "categories": []})
    finally:
        cur.close()

    sales_map, code_to_name = _get_category_sales(conn, month)
    if not sales_map:
        conn.close()
        return jsonify({"success": True, "month": month, "categories": [], "summary": {}})

    total_sale_all = sum(s for s, _ in sales_map.values())

    labor = _get_labor_by_month(conn, month)
    persons = labor["persons"]
    direct_mapping = labor["direct_mapping"]

    # Step 1: 经营岗（direct）直接映射到品类
    cat_direct = {code: {"cost": 0.0, "persons": set()} for code in sales_map}
    cat_direct["__管理__"] = {"cost": 0.0, "persons": set()}

    for ps in persons:
        if ps["cost_type"] != "direct":
            continue
        pos = ps["position_name"]
        cost = ps["total_cost"]
        pname = ps["person_name"]
        assigned = False
        for cat_key, pos_list in direct_mapping.items():
            for lab, mt in pos_list:
                if _pos_matches(pos, lab, mt):
                    if cat_key not in cat_direct:
                        cat_direct[cat_key] = {"cost": 0.0, "persons": set()}
                    cat_direct[cat_key]["cost"] += cost
                    cat_direct[cat_key]["persons"].add(pname)
                    assigned = True
                    break
            if assigned:
                break
        if not assigned:
            cat_direct["__管理__"]["cost"] += cost
            cat_direct["__管理__"]["persons"].add(pname)

    # Step 2: 管理岗（management）单独列示
    management_cost_total = 0.0
    management_head = set()
    for ps in persons:
        if ps["cost_type"] == "management":
            management_cost_total += ps["total_cost"]
            management_head.add(ps["person_name"])

    # Step 3: 通用岗（shared）按销售占比分摊
    shared_cost_total = 0.0
    for ps in persons:
        if ps["cost_type"] == "shared":
            shared_cost_total += ps["total_cost"]

    # 拼装输出
    categories = []
    total_cost_direct = 0
    total_cost_with_share = 0

    # 人效等级函数
    def _efficiency_grade(margin_pct, labor_profit_ratio):
        if labor_profit_ratio is None or margin_pct <= 0:
            return {"level": "N/A", "label": "未评估", "color": "#999"}
        if margin_pct > 35 and labor_profit_ratio < 15:
            return {"level": "A", "label": "高效 ⭐", "color": "#2ecc71"}
        if labor_profit_ratio > 40 or (margin_pct < 25 and labor_profit_ratio > 25):
            return {"level": "C", "label": "低效 🔻", "color": "#e74c3c"}
        return {"level": "B", "label": "正常", "color": "#f39c12"}

    for code in sorted(sales_map.keys(), key=lambda c: sales_map[c][0], reverse=True):
        s, p = sales_map[code]
        cat_name = code_to_name.get(code, code)
        margin_pct = round(p / s * 100, 2) if s else 0

        # 直接映射成本
        di = cat_direct.get(code, {"cost": 0, "persons": set()})
        direct_lc = di["cost"]
        direct_hc = len(di["persons"]) if isinstance(di["persons"], set) else 0

        # 分摊成本（按销售占比）
        sale_ratio = s / total_sale_all if total_sale_all else 0
        shared_lc = shared_cost_total * sale_ratio
        total_lc = direct_lc + shared_lc
        total_hc = direct_hc

        total_cost_direct += direct_lc
        total_cost_with_share += total_lc

        lc_before = direct_lc  # 分摊前
        lc_after = round(total_lc, 2) if share else round(direct_lc, 2)
        lc_shared_part = round(shared_lc, 2) if share else 0

        labor_profit_ratio = round(lc_after / p * 100, 2) if share and p else (round(direct_lc / p * 100, 2) if direct_lc and p else None)
        labor_sale_ratio = round(lc_after / s * 100, 2) if share and s else (round(direct_lc / s * 100, 2) if direct_lc and s else None)

        categories.append({
            "category_large_code": code,
            "category": cat_name,
            "sale": round(s, 2),
            "profit": round(p, 2),
            "margin_pct": margin_pct,
            "labor_cost": lc_after,                    # 展示用（受 share 参数影响）
            "labor_cost_direct": round(direct_lc, 2),  # 经营岗直接成本
            "labor_cost_shared": lc_shared_part,       # 通用岗分摊成本（仅share=true时有值）
            "headcount": total_hc,
            "labor_cost_per_sale": labor_sale_ratio,
            "labor_cost_per_profit": labor_profit_ratio,
            "profit_per_cost": round(p / lc_after, 4) if lc_after else 0,
            "efficiency": _efficiency_grade(margin_pct, labor_profit_ratio),
        })

    # 管理岗总览行
    categories.append({
        "category_large_code": "__管理__",
        "category": "🏛 管理/后台成本",
        "sale": 0, "profit": 0, "margin_pct": 0,
        "labor_cost": round(management_cost_total, 2),
        "labor_cost_direct": 0,
        "labor_cost_shared": 0,
        "headcount": len(management_head),
        "labor_cost_per_sale": None,
        "labor_cost_per_profit": None,
        "profit_per_cost": 0,
        "efficiency": {"level": "M", "label": "管理成本", "color": "#9b59b6"},
    })

    grand_total_cost = total_cost_with_share + management_cost_total if share else total_cost_direct + management_cost_total
    total_sale_val = sum(s for s, _ in sales_map.values())
    total_profit_val = sum(p for _, p in sales_map.values())

    conn.close()
    return jsonify({
        "success": True,
        "month": month,
        "share_enabled": share,
        "categories": categories,
        "summary": {
            "total_sale": round(total_sale_val, 2),
            "total_profit": round(total_profit_val, 2),
            "total_labor_cost": round(grand_total_cost, 2),
            "labor_cost_direct": round(total_cost_direct, 2),
            "labor_cost_shared": round(shared_cost_total, 2) if share else 0,
            "labor_cost_management": round(management_cost_total, 2),
            "total_headcount": labor["total_headcount"],
            "management_headcount": len(management_head),
            "labor_sale_ratio": round(grand_total_cost / total_sale_val * 100, 2) if total_sale_val else 0,
            "labor_profit_ratio": round(grand_total_cost / total_profit_val * 100, 2) if total_profit_val else 0,
        },
        "cost_type_breakdown": {
            "direct": {"cost": round(labor["direct_cost"], 2), "headcount": labor["direct_headcount"]},
            "shared": {"cost": round(shared_cost_total, 2), "headcount": labor["shared_headcount"]},
            "management": {"cost": round(management_cost_total, 2), "headcount": len(management_head)},
        },
    })


# ── API 4: /by_person (整体汇总) ────────────────────────────────────

@labor_report_bp.route("/by_person", methods=["GET", "OPTIONS"])
def api_by_person():
    """全年累计/多个月份整体：每人每月成本 + 归属品类 + 累计人效。
    不指定参数返回全部月份汇总。"""
    if request.method == "OPTIONS":
        return "", 204

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT MIN(report_month) AS min_m, MAX(report_month) AS max_m FROM t_htma_labor_cost")
        r = cur.fetchone()
        if not r or not r.get("min_m"):
            conn.close()
            return jsonify({"success": True, "months": [], "persons": [], "summary": {}})
        min_month = (request.args.get("month_from") or "").strip() or r["min_m"]
        max_month = (request.args.get("month_to") or "").strip() or r["max_m"]
    finally:
        cur.close()

    months = _months_between(min_month, max_month)

    # 按人聚合
    person_agg = {}  # pname -> {position_name, cost_type, total_cost, by_month:{}, categories:set, headcount_weight}
    for m in months:
        labor = _get_labor_by_month(conn, m)
        for ps in labor["persons"]:
            pname = ps["person_name"]
            if pname not in person_agg:
                person_agg[pname] = {
                    "person_name": pname,
                    "position_name": ps["position_name"],
                    "cost_type": ps["cost_type"],
                    "cost_type_label": ps["cost_type_label"],
                    "position_type_label": ps["position_type_label"],
                    "total_cost": 0.0,
                    "by_month": {},
                    "present_months": [],
                }
            person_agg[pname]["by_month"][m] = round(ps["total_cost"], 2)
            person_agg[pname]["total_cost"] = round(person_agg[pname]["total_cost"] + ps["total_cost"], 2)
            person_agg[pname]["present_months"].append(m)

    # 每人映射品类（取最新月份）
    last_month = months[-1]
    direct_mapping = _get_labor_by_month(conn, last_month)["direct_mapping"]
    cat_sales_all = _get_category_sales(conn, months[-1])[0]
    code_to_name = _get_category_sales(conn, months[-1])[1]

    for pname, pa in person_agg.items():
        assigned_cat = None
        pos = pa["position_name"]
        if pa["cost_type"] == "direct":
            for cat_key, pos_list in direct_mapping.items():
                for lab, mt in pos_list:
                    if _pos_matches(pos, lab, mt):
                        assigned_cat = cat_key
                        break
                if assigned_cat:
                    break
        pa["mapped_category"] = assigned_cat or (
            "（管理岗）" if pa["cost_type"] == "management" else "（通用岗）")
        pa["category_sale"] = round(cat_sales_all.get(assigned_cat, (0,0))[0], 2) if assigned_cat and assigned_cat in cat_sales_all else 0
        pa["category_profit"] = round(cat_sales_all.get(assigned_cat, (0,0))[1], 2) if assigned_cat and assigned_cat in cat_sales_all else 0
        pa["avg_monthly_cost"] = round(pa["total_cost"] / len(pa["present_months"]), 2)

    persons = sorted(person_agg.values(), key=lambda p: p["total_cost"], reverse=True)

    total_cost = sum(p["total_cost"] for p in persons)
    direct_cost = sum(p["total_cost"] for p in persons if p["cost_type"] == "direct")
    shared_cost = sum(p["total_cost"] for p in persons if p["cost_type"] == "shared")
    mgmt_cost = sum(p["total_cost"] for p in persons if p["cost_type"] == "management")

    conn.close()
    return jsonify({
        "success": True,
        "months": months,
        "persons": persons,
        "summary": {
            "total_headcount": len(persons),
            "total_cost": round(total_cost, 2),
            "direct_cost": round(direct_cost, 2),
            "shared_cost": round(shared_cost, 2),
            "management_cost": round(mgmt_cost, 2),
            "month_count": len(months),
        },
    })

@labor_report_bp.route("/persons", methods=["GET", "OPTIONS"])
def api_persons():
    """逐人明细 + 三级模型分类 + 管理岗独立标识 + 人效等级"""
    if request.method == "OPTIONS":
        return "", 204

    month = (request.args.get("month") or "").strip()
    conn = get_conn()
    cur = conn.cursor()
    try:
        if not month:
            cur.execute("SELECT MAX(report_month) FROM t_htma_labor_cost")
            r = cur.fetchone()
            month = r.get("MAX(report_month)") or list(r.values())[0] if not isinstance(r, dict) else None
            if not month:
                conn.close()
                return jsonify({"success": True, "month": None, "persons": []})
    finally:
        cur.close()

    labor = _get_labor_by_month(conn, month)
    direct_mapping = labor["direct_mapping"]
    sales_map, code_to_name = _get_category_sales(conn, month)
    total_sale_all = sum(s for s, _ in sales_map.values()) if sales_map else 1

    # 为每个人分配品类
    out = []
    for ps in labor["persons"]:
        pos = ps["position_name"]
        cost = ps["total_cost"]
        pname = ps["person_name"]
        cost_type = ps["cost_type"]

        assigned_cat = None
        assigned_pos_name = None
        if cost_type == "direct":
            for cat_key, pos_list in direct_mapping.items():
                for lab, mt in pos_list:
                    if _pos_matches(pos, lab, mt):
                        assigned_cat = cat_key
                        assigned_pos_name = lab
                        break
                if assigned_cat:
                    break

        cat_sale, cat_profit = 0, 0
        if assigned_cat and assigned_cat in sales_map:
            cat_sale, cat_profit = sales_map[assigned_cat]

        out.append({
            "person_name": pname,
            "position_name": pos,
            "position_type": ps["position_type"],
            "position_type_label": ps["position_type_label"],
            "total_cost": cost,
            "work_hours": float(ps.get("work_hours") or 0),
            "base_salary": float(ps.get("base_salary") or 0),
            "performance": float(ps.get("performance") or 0),
            "cost_type": cost_type,
            "cost_type_label": {"direct": "经营岗", "shared": "通用岗", "management": "管理岗"}[cost_type],
            "mapped_category": assigned_cat or ("（管理岗）" if cost_type == "management" else "（通用岗）"),
            "mapped_position": assigned_pos_name or "-",
            "category_sale": round(cat_sale, 2) if assigned_cat else 0,
            "category_profit": round(cat_profit, 2) if assigned_cat else 0,
            "cost_sale_ratio": round(cost / cat_sale * 100, 4) if assigned_cat and cat_sale else None,
            "cost_profit_ratio": round(cost / cat_profit * 100, 4) if assigned_cat and cat_profit else None,
        })

    conn.close()
    return jsonify({"success": True, "month": month, "persons": out, "summary": {
        "total_cost": labor["total_cost"],
        "total_headcount": labor["total_headcount"],
        "management_cost": labor["management_cost"],
        "direct_cost": labor["direct_cost"],
        "shared_cost": labor["shared_cost"],
        "management_headcount": labor["management_headcount"],
        "direct_headcount": labor["direct_headcount"],
        "shared_headcount": labor["shared_headcount"],
    }})


# ── API 4: /ai_analysis ── 综合分析报告 ───────────────────────────

@labor_report_bp.route("/ai_analysis", methods=["GET", "OPTIONS"])
def api_labor_ai_analysis():
    """人力成本AI综合分析：人效趋势、结构、与销售/毛利的交叉分析，含建议"""
    if request.method == "OPTIONS":
        return "", 204

    from datetime import datetime
    conn = get_conn()
    cur = conn.cursor()
    try:
        # 获取所有月度数据
        cur.execute("""
            SELECT report_month, COUNT(*) as cnt, ROUND(SUM(total_cost),2) as total_cost,
                   ROUND(SUM(company_cost),2) as company_cost,
                   ROUND(AVG(work_hours),1) as avg_hours,
                   ROUND(SUM(work_hours),1) as total_hours
            FROM t_htma_labor_cost WHERE total_cost > 0
            GROUP BY report_month ORDER BY report_month
        """)
        monthly_data = cur.fetchall()

        if not monthly_data:
            return jsonify({"success": False, "message": "无人力成本数据"}), 404

        # 各月人力构成
        for m in monthly_data:
            cur.execute("""
                SELECT position_type, COUNT(*) as cnt, ROUND(SUM(total_cost),2) as cost
                FROM t_htma_labor_cost WHERE report_month=%s AND total_cost > 0
                GROUP BY position_type ORDER BY position_type
            """, (m["report_month"],))
            m["by_type"] = cur.fetchall()

        # 各月销售额/毛利
        for m in monthly_data:
            ym = m["report_month"]
            y, mt = ym.split("-")
            start = f"{y}-{mt}-01"
            if mt == "12":
                end = f"{y}-12-31"
            else:
                nm = int(mt) + 1
                end = f"{y}-{nm:02d}-01"
            cur.execute("""
                SELECT COALESCE(SUM(sale_amount),0) as sale, COALESCE(SUM(COALESCE(gross_profit,0)),0) as profit
                FROM t_htma_sale WHERE store_id=%s AND data_date>=%s AND data_date<%s
            """, (STORE_ID, start, end))
            sr = cur.fetchone()
            m["sale"] = float(sr["sale"] or 0)
            m["profit"] = float(sr["profit"] or 0)
            tc = float(m["total_cost"])
            sale = float(m["sale"])
            profit = float(m["profit"])
            cnt = int(m["cnt"])
            m["labor_sale_ratio"] = round(tc / sale * 100, 2) if sale else 0
            m["labor_profit_ratio"] = round(tc / profit * 100, 2) if profit else 0
            m["sale_per_capita"] = round(sale / cnt, 2) if cnt else 0

        latest = monthly_data[-1]
        prev = monthly_data[-2] if len(monthly_data) >= 2 else None

        # 生成分析结论
        conclusions = []

        # 1. 人效趋势结论
        if prev:
            hc_change = latest["cnt"] - prev["cnt"]
            hc_pct = round(hc_change / prev["cnt"] * 100, 1) if prev["cnt"] else 0
            sale_change = round(latest["sale"] - prev["sale"], 2)
            sale_pct = round(sale_change / prev["sale"] * 100, 1) if prev["sale"] else 0
            pps_change = round(latest["sale_per_capita"] - prev["sale_per_capita"], 2)
            pps_pct = round(pps_change / prev["sale_per_capita"] * 100, 1) if prev["sale_per_capita"] else 0

            conclusions.append({
                "title": "人效趋势",
                "type": "success" if pps_pct > 0 else "warning",
                "detail": (
                    f"对比{prev['report_month']}→{latest['report_month']}："
                    f"人员{prev['cnt']}→{latest['cnt']}人({hc_pct:+.1f}%), "
                    f"销售额{prev['sale']:.0f}→{latest['sale']:.0f}({sale_pct:+.1f}%), "
                    f"人均销售{prev['sale_per_capita']:.0f}→{latest['sale_per_capita']:.0f}元({pps_pct:+.1f}%)"
                ),
                'suggestion': '人员效率持续改善' if pps_pct > 0 else '人均产出下降需关注',
            })

        # 2. 人力成本占比
        lr = latest["labor_profit_ratio"]
        conclusions.append({
            "title": "人力成本占毛利比",
            "type": "warning" if lr > 25 else ("info" if lr > 15 else "success"),
            "detail": f"{latest['report_month']} 人力成本 {latest['total_cost']:.0f} 元，占毛利 {lr:.1f}%（销售额 {latest['sale']:.0f} 元，毛利 {latest['profit']:.0f} 元）",
            "suggestion": "建议优化排班或提升高毛利品类占比以改善人力/毛利比" if lr > 20 else "人力成本占比在合理范围内",
        })

        # 3. 人力结构分析
        tc_latest = float(latest["total_cost"])
        cnt_latest = int(latest["cnt"])
        type_parts = []
        type_meta = {"fulltime": "组员", "leader": "组长", "management": "管理岗", "cleaner": "保洁", "parttime": "兼职", "hourly": "小时工"}
        for t in latest.get("by_type", []):
            tp = t["position_type"]
            label = type_meta.get(tp, tp)
            cnt = t["cnt"]
            ccost = float(t["cost"])
            pct = round(ccost / tc_latest * 100, 1) if tc_latest else 0
            type_parts.append(f"{label}{cnt}人({pct}%)")
        conclusions.append({
            "title": "人力结构",
            "type": "info",
            "detail": f"{latest['report_month']} 人力结构：{'、'.join(type_parts)}。总成本约 {tc_latest:.0f} 元，"
                      f"人均成本 {tc_latest/cnt_latest:.0f} 元/月",
            "suggestion": "管理岗占比偏高时可考虑职能合并",
        })

        # 4. 品类人力映射摘要
        cur.execute("""
            SELECT p.position_name, COUNT(*) as cnt, ROUND(SUM(p.total_cost),2) as cost
            FROM t_htma_labor_cost p
            WHERE p.report_month=%s AND p.total_cost > 0 AND p.position_type IN ('fulltime','leader')
            GROUP BY p.position_name ORDER BY SUM(p.total_cost) DESC
        """, (latest["report_month"],))
        pos_rows = cur.fetchall()
        if pos_rows:
            pos_parts = [f"{r['position_name']}{r['cnt']}人({r['cost']:.0f}元)" for r in pos_rows[:8]]
            conclusions.append({
                "title": "经营岗位分布",
                "type": "info",
                "detail": f"{latest['report_month']} 经营岗位：{'、'.join(pos_parts)}",
                "suggestion": "可对照品类销售占比，评估各岗位人员配置是否合理",
            })

        # 5. 管理岗成本
        cur.execute("""
            SELECT person_name, position_name, total_cost, work_hours,
                   ROUND(total_cost/NULLIF(work_hours,0),2) as hourly_rate
            FROM t_htma_labor_cost
            WHERE report_month=%s AND position_type='management' AND total_cost > 0
            ORDER BY total_cost DESC
        """, (latest["report_month"],))
        mgmt_rows = cur.fetchall()
        if mgmt_rows:
            mgmt_total = sum(float(r["total_cost"]) for r in mgmt_rows)
            mgmt_pct = round(mgmt_total / tc_latest * 100, 1) if tc_latest else 0
            mgmt_parts = [f"{r['person_name']}({r['position_name']}){r['total_cost']:.0f}元" for r in mgmt_rows]
            conclusions.append({
                "title": "管理岗成本",
                "type": "warning" if mgmt_pct > 20 else "info",
                "detail": f"{latest['report_month']} 管理岗{len(mgmt_rows)}人，总成本 {mgmt_total:.0f} 元，占人力总成本 {mgmt_pct}%"
                          + (f"（{'; '.join(mgmt_parts)}）" if len(mgmt_parts) <= 6 else ""),
                "suggestion": "管理岗占比偏高，建议评估职能重叠与扁平化空间" if mgmt_pct > 20 else "管理岗成本在正常范围",
            })

        # 6. 总趋势概览
        if len(monthly_data) >= 2:
            first = monthly_data[0]
            fc = float(first["total_cost"])
            lc = float(latest["total_cost"])
            fs = float(first["sale"])
            ls = float(latest["sale"])
            fcnt = int(first["cnt"])
            lcnt = int(latest["cnt"])
            cost_pct = round((lc - fc) / fc * 100, 1) if fc else 0
            hc_pct_all = round((lcnt - fcnt) / fcnt * 100, 1) if fcnt else 0
            sale_pct_all = round((ls - fs) / fs * 100, 1) if fs else 0
            conclusions.append({
                "title": "整体趋势",
                "type": "success" if sale_pct_all > cost_pct else "info",
                "detail": f"自 {first['report_month']} 至 {latest['report_month']}：人力成本 {fc:.0f}→{lc:.0f}元({cost_pct:+.1f}%), " 
                          f"人数 {fcnt}→{lcnt}人({hc_pct_all:+.1f}%), 销售额 {fs:.0f}→{ls:.0f}元({sale_pct_all:+.1f}%)",
                "suggestion": "人力成本增长快于销售增长，需关注人效平衡" if cost_pct > sale_pct_all else "人力成本增长慢于销售增长，运营效率向好",
            })

        # 生成简要摘要
        summary = (
            f"{latest['report_month']} 人力成本 {tc_latest:.0f} 元（{cnt_latest}人），"
            f"销售额 {latest['sale']:.0f} 元，人力/销售占比 {latest['labor_sale_ratio']:.1f}%，"
            f"人力/毛利占比 {latest['labor_profit_ratio']:.1f}%，人均销售 {latest['sale_per_capita']:.0f} 元。"
        )

        return jsonify({
            "success": True,
            "summary": summary,
            "conclusions": conclusions,
            "monthly_data": [{
                "month": m["report_month"],
                "headcount": int(m["cnt"]),
                "total_cost": float(m["total_cost"]),
                "labor_sale_ratio": float(m["labor_sale_ratio"]),
                "labor_profit_ratio": float(m["labor_profit_ratio"]),
                "sale_per_capita": float(m["sale_per_capita"]),
                "sale": float(m["sale"]),
                "profit": float(m["profit"]),
                "by_type": [{"position_type": t["position_type"], "cnt": int(t["cnt"]), "cost": float(t["cost"])} for t in (m.get("by_type") or [])],
            } for m in monthly_data],
            "latest_month": latest["report_month"],
        })
    finally:
        conn.close()
