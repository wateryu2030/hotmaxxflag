# -*- coding: utf-8 -*-
"""人力成本 HTML 页面：/labor、/labor_analysis。"""

import os

import pymysql
from flask import Blueprint, Response, current_app, request, send_from_directory

from db_config import get_conn
from page_auth import _auth_enabled, _has_module_access, _is_logged_in
import os


pages_labor_bp = Blueprint("pages_labor", __name__)


# 人力成本 position_type -> 前端展示类目名（与 12月薪资表 各 sheet 对应）
LABOR_POSITION_TYPE_NAMES = {
    "leader": "组长",
    "fulltime": "组员",
    "parttime": "兼职",
    "hourly": "小时工",
    "cleaner": "保洁",
    "management": "管理岗",
}
LABOR_CATEGORY_ORDER = ("组长", "组员", "兼职", "小时工", "保洁", "管理岗")
# 类目列表展示顺序：组长+组员合并为一行，便于人效分析；明细区仍保留组长/组员分表
LABOR_CATEGORY_ORDER_DISPLAY = ("组长+组员", "兼职", "小时工", "保洁", "管理岗")


def _labor_category_by_month(limit=24):
    """按类目×月份汇总：每个类目下有小计 + 各月数据，用于类目列表多行展示。
    组长与组员合并为「组长+组员」一行，并注明月份，便于人效分析。
    返回 (months_asc, by_cat)：months_asc 为月份升序，by_cat[类目名][月份] = {position_count, total_wage}，月份含 '小计'。"""
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT report_month, position_type,
                   COUNT(*) AS position_count,
                   COALESCE(SUM(COALESCE(total_cost, company_cost)), 0) AS total_wage
            FROM t_htma_labor_cost
            GROUP BY report_month, position_type
            ORDER BY report_month ASC
        """)
        rows = cur.fetchall()
        name_to_type = {v: k for k, v in LABOR_POSITION_TYPE_NAMES.items()}
        months_set = set()
        by_type_month = {}  # (position_type, report_month) -> {count, wage}
        for r in rows:
            m = (r.get("report_month") or "").strip()
            t = (r.get("position_type") or "").strip().lower()
            if not m or not t:
                continue
            months_set.add(m)
            cnt = int(r.get("position_count") or 0)
            wage = round(float(r.get("total_wage") or 0), 2)
            by_type_month[(t, m)] = {"position_count": cnt, "total_wage": wage}
        months_asc = sorted(months_set)[:limit]
        # 全口径 + 类目（组长+组员合并）+ 其他类目；每类目下 小计 + 各月
        by_cat = {}
        for display_name in ("全口径",) + tuple(LABOR_CATEGORY_ORDER_DISPLAY):
            by_cat[display_name] = {"小计": {"position_count": 0, "total_wage": 0}}
            for m in months_asc:
                if display_name == "全口径":
                    cnt = 0
                    wage = 0
                    for t in LABOR_POSITION_TYPE_NAMES:
                        v = by_type_month.get((t, m), {"position_count": 0, "total_wage": 0})
                        cnt += v["position_count"]
                        wage += v["total_wage"]
                    by_cat[display_name][m] = {"position_count": cnt, "total_wage": round(wage, 2)}
                elif display_name == "组长+组员":
                    # 组长 + 组员 合并计算，并注明月份（各列已是该月）
                    v_leader = by_type_month.get(("leader", m), {"position_count": 0, "total_wage": 0})
                    v_fulltime = by_type_month.get(("fulltime", m), {"position_count": 0, "total_wage": 0})
                    cnt = v_leader["position_count"] + v_fulltime["position_count"]
                    wage = round(v_leader["total_wage"] + v_fulltime["total_wage"], 2)
                    by_cat[display_name][m] = {"position_count": cnt, "total_wage": wage}
                else:
                    t = name_to_type.get(display_name, "")
                    v = by_type_month.get((t, m), {"position_count": 0, "total_wage": 0})
                    by_cat[display_name][m] = {"position_count": v["position_count"], "total_wage": v["total_wage"]}
                by_cat[display_name]["小计"]["position_count"] += by_cat[display_name][m]["position_count"]
                by_cat[display_name]["小计"]["total_wage"] += by_cat[display_name][m]["total_wage"]
            by_cat[display_name]["小计"]["total_wage"] = round(by_cat[display_name]["小计"]["total_wage"], 2)
        return months_asc, by_cat
    finally:
        conn.close()


def _labor_person_display(p):
    """姓名展示：空、纯数字（含 12.0、序号）均显示为「-」，避免把序号当姓名。供 /labor 页与 API 共用。"""
    if p is None:
        return "-"
    s = str(p).strip()
    if not s:
        return "-"
    try:
        float(s)
        return "-"
    except (ValueError, TypeError):
        pass
    if s.isdigit() or (len(s) <= 6 and s.replace(".", "", 1).replace("-", "", 1).isdigit()):
        return "-"
    return s.replace("<", "&lt;")


def _labor_cost_analysis_response(month):
    """人力成本分析逻辑，返回 (month, leaders, fulltime, summary) 或 (None, [], [], {})。
    全口径：汇总所有 position_type（组长/组员/兼职/小时工/保洁/管理岗）；再按类目拆分展示。"""
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        if not month:
            cur.execute("SELECT DISTINCT report_month FROM t_htma_labor_cost ORDER BY report_month DESC LIMIT 1")
            row = cur.fetchone()
            month = row["report_month"] if row and row.get("report_month") else None
            if not month:
                cur.execute("SELECT report_month FROM t_htma_labor_cost_analysis ORDER BY report_month DESC LIMIT 1")
                row = cur.fetchone()
                month = row["report_month"] if row and row.get("report_month") else None
            if not month:
                return None, [], [], {}

        cur.execute("""
            SELECT position_name, person_name, supplier_name, total_salary, pre_tax_pay, actual_salary, luxury_bonus, actual_income, company_cost, total_cost
            FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'leader' ORDER BY COALESCE(total_cost, 0) DESC
        """, (month,))
        leaders = cur.fetchall()
        cur.execute("""
            SELECT position_name, person_name, supplier_name, work_hours, base_salary, performance, position_allowance, total_salary, pre_tax_pay, luxury_amount, actual_income, company_cost, total_cost
            FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'fulltime' ORDER BY COALESCE(company_cost, 0) DESC
        """, (month,))
        fulltime = cur.fetchall()
        try:
            cur.execute("""
                SELECT position_name, person_name, supplier_name, company_cost, total_cost,
                       store_name, city, join_date, leave_date, work_hours, normal_hours, triple_pay_hours,
                       hourly_rate, pay_amount, service_fee_unit, service_fee_total, tax,
                       cost_include, department
                FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'parttime' ORDER BY position_name, COALESCE(total_cost, 0) DESC
            """, (month,))
            parttime = cur.fetchall()
        except Exception:
            cur.execute("""
                SELECT position_name, person_name, supplier_name, company_cost, total_cost
                FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'parttime' ORDER BY position_name, COALESCE(total_cost, 0) DESC
            """, (month,))
            parttime = cur.fetchall()
        cur.execute("""
            SELECT position_name, person_name, supplier_name, company_cost, total_cost
            FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'hourly' ORDER BY COALESCE(total_cost, 0) DESC
        """, (month,))
        hourly = cur.fetchall()
        cur.execute("""
            SELECT position_name, person_name, supplier_name, company_cost, total_cost
            FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'cleaner' ORDER BY COALESCE(total_cost, 0) DESC
        """, (month,))
        cleaner = cur.fetchall()
        cur.execute("""
            SELECT position_name, person_name, supplier_name, company_cost, total_cost
            FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'management' ORDER BY COALESCE(total_cost, 0) DESC
        """, (month,))
        management = cur.fetchall()
        # 全口径：按 position_type 汇总（含组长/组员/兼职/小时工/保洁/管理岗）
        cur.execute("""
            SELECT position_type, COUNT(*) AS position_count,
                   COALESCE(SUM(COALESCE(total_cost, company_cost)), 0) AS total_wage
            FROM t_htma_labor_cost WHERE report_month = %s
            GROUP BY position_type
        """, (month,))
        type_rows = cur.fetchall()
        total_labor_cost = 0
        total_positions = 0
        by_type = {}
        for r in type_rows:
            t = (r.get("position_type") or "").strip().lower()
            cnt = int(r.get("position_count") or 0)
            wage = round(float(r.get("total_wage") or 0), 2)
            by_type[t] = {"position_count": cnt, "total_wage": wage}
            total_labor_cost += wage
            total_positions += cnt
        total_labor_cost = round(total_labor_cost, 2)
        cur.execute("SELECT COALESCE(SUM(work_hours), 0) AS th FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'fulltime'", (month,))
        total_hours_row = cur.fetchone()
        total_hours = float(total_hours_row["th"] or 0) if total_hours_row else 0

        # 若明细表该月无数据，尝试从汇总表 t_htma_labor_cost_analysis 取汇总展示
        if total_positions == 0 and total_labor_cost == 0 and len(leaders) == 0 and len(fulltime) == 0:
            cur.execute("""
                SELECT report_month, leader_count, leader_total_cost, fulltime_count, fulltime_total_cost,
                       fulltime_total_hours, total_labor_cost, prev_month_total, mom_pct
                FROM t_htma_labor_cost_analysis WHERE report_month = %s
            """, (month,))
            ana = cur.fetchone()
            if ana:
                leader_total = float(ana.get("leader_total_cost") or 0)
                fulltime_total = float(ana.get("fulltime_total_cost") or 0)
                total_labor_cost = float(ana.get("total_labor_cost") or 0)
                total_hours = float(ana.get("fulltime_total_hours") or 0)
                lc = int(ana.get("leader_count") or 0)
                fc = int(ana.get("fulltime_count") or 0)
                by_category = [
                    {"name": "全口径", "total_wage": round(total_labor_cost, 2), "position_count": lc + fc},
                    {"name": "组长", "total_wage": round(leader_total, 2), "position_count": lc},
                    {"name": "组员", "total_wage": round(fulltime_total, 2), "position_count": fc},
                ]
                try:
                    _ty = (os.environ.get("TARGET_LABOR_COST_YUAN") or "530000").strip() or "530000"
                    _target_y = float(_ty)
                except Exception:
                    _target_y = 530000.0
                summary = {
                    "report_month": month,
                    "leader_position_count": lc,
                    "fulltime_position_count": fc,
                    "formal_employee_count": lc + fc,
                    "other_labor_count": 0,
                    "leader_total_cost": round(leader_total, 2),
                    "fulltime_total_cost": round(fulltime_total, 2),
                    "total_labor_cost": round(total_labor_cost, 2),
                    "fulltime_total_hours": round(total_hours, 2),
                    "by_category": by_category,
                    "target_labor_cost": _target_y,
                    "labor_cost_difference": round(_target_y - total_labor_cost, 2),
                    "labor_cost_difference_note": "实际支付约 53 万，本页全口径仅统计出 43 万，存在统计缺口。可能原因：① 部分类目或 sheet 未导入；② 薪资表与开票/实际支付口径不一致（如含税、服务费、社保等）；③ 某月或某店数据未覆盖。请核对「开票金额/总成本」及完整薪资表各 sheet 是否均已导入。",
                    "note": "以下为汇总表数据；组长/组员明细暂无。请使用「12月薪资表」完整 Excel 重新导入后可得到全口径（约 53 万）及兼职/小时工/保洁/管理岗等类目拆分。",
                }
                return month, [], [], summary
            return None, [], [], {}

        # 构建 by_category：先全口径，再按固定顺序各类目
        by_category = [{"name": "全口径", "total_wage": total_labor_cost, "position_count": total_positions}]
        type_to_name = LABOR_POSITION_TYPE_NAMES
        for display_name in LABOR_CATEGORY_ORDER:
            for ptype, dname in type_to_name.items():
                if dname != display_name:
                    continue
                if ptype in by_type and (by_type[ptype]["position_count"] or by_type[ptype]["total_wage"]):
                    by_category.append({
                        "name": display_name,
                        "total_wage": by_type[ptype]["total_wage"],
                        "position_count": by_type[ptype]["position_count"],
                    })
                    break

        leader_total = by_type.get("leader", {}).get("total_wage", 0)
        fulltime_total = by_type.get("fulltime", {}).get("total_wage", 0)
        leader_count = int(by_type.get("leader", {}).get("position_count", 0))
        fulltime_count = int(by_type.get("fulltime", {}).get("position_count", 0))
        parttime_count = int(by_type.get("parttime", {}).get("position_count", 0))
        hourly_count = int(by_type.get("hourly", {}).get("position_count", 0))
        cleaner_count = int(by_type.get("cleaner", {}).get("position_count", 0))
        management_count = int(by_type.get("management", {}).get("position_count", 0))
        formal_count = leader_count + fulltime_count
        other_count = parttime_count + hourly_count + cleaner_count + management_count
        try:
            _target_yuan = (os.environ.get("TARGET_LABOR_COST_YUAN") or "530000").strip() or "530000"
            target_labor_cost_yuan = float(_target_yuan)
        except Exception:
            target_labor_cost_yuan = 530000.0
        labor_cost_difference = round(target_labor_cost_yuan - total_labor_cost, 2)
        summary = {
            "report_month": month,
            "leader_position_count": leader_count,
            "fulltime_position_count": fulltime_count,
            "parttime_position_count": parttime_count,
            "hourly_position_count": hourly_count,
            "cleaner_position_count": cleaner_count,
            "management_position_count": management_count,
            "formal_employee_count": formal_count,
            "other_labor_count": other_count,
            "leader_total_cost": round(leader_total, 2),
            "fulltime_total_cost": round(fulltime_total, 2),
            "total_labor_cost": total_labor_cost,
            "fulltime_total_hours": round(total_hours, 2),
            "by_category": by_category,
            "target_labor_cost": target_labor_cost_yuan,
            "labor_cost_difference": labor_cost_difference,
            "labor_cost_difference_note": "实际支付约 53 万，本页全口径仅统计出 43 万，存在统计缺口。可能原因：① 部分类目或 sheet 未导入；② 薪资表与开票/实际支付口径不一致（如含税、服务费、社保等）；③ 某月或某店数据未覆盖。请核对「开票金额/总成本」及完整薪资表各 sheet 是否均已导入。",
            "note": "全口径为当月全部人员费用。正式职工=组长+组员，其他人力=兼职+小时工+保洁+管理岗，分开统计便于人效分析。",
        }
        def _decimals(obj):
            if obj is None:
                return None
            d = {}
            for k, v in obj.items():
                if k == "person_name":
                    d[k] = _labor_person_display(v)
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    d[k] = round(float(v), 2) if v is not None else None
                else:
                    d[k] = v
            return d
        summary["detail_parttime"] = [_decimals(r) for r in parttime]
        # 兼职按属性(岗位名)分组，便于先汇总再展开明细
        by_attr = {}
        for r in parttime:
            attr = (r.get("position_name") or "").strip() or "其他"
            if attr not in by_attr:
                by_attr[attr] = {"attribute": attr, "count": 0, "total_cost": 0, "persons": []}
            by_attr[attr]["count"] += 1
            by_attr[attr]["total_cost"] += float(r.get("total_cost") or r.get("company_cost") or 0)
            by_attr[attr]["persons"].append(_decimals(r))
        summary["parttime_by_attribute"] = list(by_attr.values())
        for g in summary["parttime_by_attribute"]:
            g["total_cost"] = round(g["total_cost"], 2)
        # 组员/全职按岗位分组，便于先汇总再展开明细（与兼职展示逻辑一致）
        fulltime_by_pos = {}
        for r in fulltime:
            pos = (r.get("position_name") or "").strip() or "其他"
            if pos not in fulltime_by_pos:
                fulltime_by_pos[pos] = {"position": pos, "count": 0, "total_cost": 0, "persons": []}
            fulltime_by_pos[pos]["count"] += 1
            fulltime_by_pos[pos]["total_cost"] += float(r.get("total_cost") or r.get("company_cost") or 0)
            fulltime_by_pos[pos]["persons"].append(_decimals(r))
        summary["fulltime_by_position"] = list(fulltime_by_pos.values())
        for g in summary["fulltime_by_position"]:
            g["total_cost"] = round(g["total_cost"], 2)
        summary["detail_hourly"] = [_decimals(r) for r in hourly]
        summary["detail_cleaner"] = [_decimals(r) for r in cleaner]
        summary["detail_management"] = [_decimals(r) for r in management]
        # 群组维度分析：按 position_name 聚合
        cur.execute("""
            SELECT position_name, COUNT(*) AS headcount,
                   COALESCE(SUM(COALESCE(total_cost, company_cost, 0)), 0) AS total_cost,
                   AVG(COALESCE(total_cost, company_cost, 0)) AS avg_cost,
                   COUNT(DISTINCT supplier_name) AS supplier_count,
                   GROUP_CONCAT(DISTINCT supplier_name SEPARATOR '、') AS suppliers
            FROM t_htma_labor_cost WHERE report_month = %s
            GROUP BY position_name ORDER BY total_cost DESC
        """, (month,))
        summary["group_analysis"] = cur.fetchall()
        cur.execute("""
            SELECT supplier_name, COUNT(*) AS headcount,
                   COALESCE(SUM(COALESCE(total_cost, company_cost, 0)), 0) AS total_cost,
                   COUNT(DISTINCT position_name) AS position_count,
                   GROUP_CONCAT(DISTINCT position_name SEPARATOR '、') AS positions
            FROM t_htma_labor_cost WHERE report_month = %s
            GROUP BY supplier_name ORDER BY total_cost DESC
        """, (month,))
        summary["supplier_analysis"] = cur.fetchall()
        cur.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN join_date!='' AND join_date<=%s THEN 1 ELSE 0 END) AS joined,
                   SUM(CASE WHEN leave_date!='' AND leave_date>=%s THEN 1 ELSE 0 END) AS left_count
            FROM t_htma_labor_cost WHERE report_month = %s
        """, (month, month, month))
        summary["turnover_analysis"] = cur.fetchone()
        return month, [_decimals(r) for r in leaders], [_decimals(r) for r in fulltime], summary
    finally:
        conn.close()


def _labor_safe_response(f, fallback_success_json):
    """人力成本接口统一异常捕获：避免 DB/逻辑异常导致 500，始终返回 200 + JSON，便于前端独立展示错误。"""
    try:
        return f()
    except Exception as e:
        return jsonify({**fallback_success_json, "success": False, "message": "人力成本服务暂时异常，请稍后重试或使用独立页 /labor。（" + str(e)[:200] + "）"})


        return jsonify({"success": False, "message": "无权访问人力成本模块，请联系管理员"}), 403

    def _do():
        conn = get_conn()
        try:
            cur = conn.cursor(pymysql.cursors.DictCursor)
            cur.execute("SELECT COUNT(*) AS n FROM t_htma_labor_cost")
            raw_count = (cur.fetchone() or {}).get("n") or 0
            cur.execute("SELECT report_month FROM t_htma_labor_cost ORDER BY report_month DESC LIMIT 1")
            latest_row = cur.fetchone()
            latest_report_month = (latest_row or {}).get("report_month") or None
            cur.execute("SELECT report_month, leader_count, fulltime_count, leader_total_cost, fulltime_total_cost, total_labor_cost FROM t_htma_labor_cost_analysis ORDER BY report_month DESC LIMIT 24")
            analysis_months = cur.fetchall()
            cur.execute("SELECT DISTINCT report_month FROM t_htma_labor_cost ORDER BY report_month DESC LIMIT 24")
            detail_months = []
            for r in cur.fetchall():
                v = r.get("report_month") if isinstance(r, dict) else (r[0] if r else None)
                if v:
                    detail_months.append(str(v))
            for r in analysis_months:
                for k, v in list(r.items()):
                    if v is not None:
                        try:
                            f = float(v)
                            r[k] = int(f) if f == int(f) else round(f, 2)
                        except (TypeError, ValueError):
                            pass
            available = list(dict.fromkeys(detail_months + [str(r.get("report_month")) for r in analysis_months if r.get("report_month")]))
            available.sort(reverse=True)
            return jsonify({
                "success": True,
                "raw_count": raw_count,
                "latest_report_month": latest_report_month,
                "analysis_months": analysis_months,
                "available_months": available[:24],
            })
        finally:
            conn.close()

    return _labor_safe_response(_do, {"raw_count": 0, "latest_report_month": None, "analysis_months": [], "available_months": []})


def _api_labor_cost_impl():
    """人力成本分析逻辑（独立于主看板 KPI 周期，仅按报表月份）。"""
    month = (request.args.get("month") or request.form.get("month") or "").strip()
    if not month and request.get_json(silent=True):
        month = (request.get_json().get("month") or "").strip()
    report_month, leaders, fulltime, summary = _labor_cost_analysis_response(month)
    if report_month is None:
        return jsonify({"success": True, "report_month": None, "leaders": [], "fulltime": [], "summary": {}, "message": "暂无人力成本数据，请先导入"})
    return jsonify({"success": True, "report_month": report_month, "leaders": leaders, "fulltime": fulltime, "summary": summary})






def _labor_months_overview(limit=24):
    """返回各月汇总列表，用于「汇总」表展示。按 report_month 升序。含正式职工(组长+组员)与其他人力(兼职+小时工+保洁+管理岗)人数，便于分开统计。"""
    try:
        _ty = (os.environ.get("TARGET_LABOR_COST_YUAN") or "530000").strip() or "530000"
        target = float(_ty)
    except Exception:
        target = 530000.0
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT report_month, position_type,
                   COUNT(*) AS position_count,
                   COALESCE(SUM(COALESCE(total_cost, company_cost)), 0) AS total_wage
            FROM t_htma_labor_cost
            GROUP BY report_month, position_type
            ORDER BY report_month ASC
        """)
        rows = cur.fetchall()
        by_month = {}
        for r in rows:
            m = (r.get("report_month") or "").strip()
            if not m:
                continue
            t = (r.get("position_type") or "").strip().lower()
            cnt = int(r.get("position_count") or 0)
            wage = round(float(r.get("total_wage") or 0), 2)
            if m not in by_month:
                by_month[m] = {"total_labor_cost": 0, "position_count": 0, "formal_count": 0, "other_count": 0}
            by_month[m]["total_labor_cost"] += wage
            by_month[m]["position_count"] += cnt
            if t in ("leader", "fulltime"):
                by_month[m]["formal_count"] += cnt
            else:
                by_month[m]["other_count"] += cnt
        months_asc = sorted(by_month.keys())[:limit]
        out = []
        for m in months_asc:
            d = by_month[m]
            d["total_labor_cost"] = round(d["total_labor_cost"], 2)
            out.append({
                "report_month": str(m),
                "total_labor_cost": d["total_labor_cost"],
                "position_count": d["position_count"],
                "formal_count": d["formal_count"],
                "other_count": d["other_count"],
                "target_labor_cost": target,
                "labor_cost_difference": round(target - d["total_labor_cost"], 2),
            })
        return out
    finally:
        conn.close()


def _labor_available_months(limit=24):
    """返回有人力数据的报表月份列表，用于分月展示选择。先查明细表，无则查汇总表；兼容 tuple 行。
    后续扩展：人力成本将支持按自定义起止日期（start_date/end_date）分解计算，与 KPI 自定义时间起点同一模式。"""
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT DISTINCT report_month FROM t_htma_labor_cost ORDER BY report_month DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        out = []
        for r in rows:
            v = r.get("report_month") if isinstance(r, dict) else (r[0] if r else None)
            if v:
                out.append(str(v))
        if not out:
            cur.execute("SELECT report_month FROM t_htma_labor_cost_analysis ORDER BY report_month DESC LIMIT %s", (limit,))
            for r in cur.fetchall():
                v = r.get("report_month") if isinstance(r, dict) else (r[0] if r else None)
                if v and str(v) not in out:
                    out.append(str(v))
        return out
    finally:
        conn.close()


@pages_labor_bp.route("/labor")
def page_labor():
    """人力成本独立页：服务端直接取数并渲染，分月展示、每类目到人明细便于查看人员稳定。"""
    if _auth_enabled() and not (os.environ.get("HTMA_UNITTEST_DISABLE_AUTH") or "").strip().lower() in ("1", "true") and (not _is_logged_in() or not _has_module_access("labor")):
        return Response("您无权访问人力成本模块，请联系管理员。", status=403)
    month = (request.args.get("month") or "").strip()
    report_month, leaders, fulltime, summary = _labor_cost_analysis_response(month or None)
    available_months = _labor_available_months()
    if not available_months and report_month:
        available_months = [report_month]
    # 月份显示为 2025年12月
    def _month_label(ym):
        if not ym or len(ym) < 7:
            return str(ym)
        try:
            y, m = ym.split("-")[0], ym.split("-")[1].lstrip("0") or "0"
            return "%s年%s月" % (y, int(m))
        except Exception:
            return str(ym)
    base_css = (
        "body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:20px;}"
        ".box{background:#1e293b;border:1px solid #334155;border-radius:6px;padding:12px 10px;margin-bottom:12px;}"
        ".label{color:#94a3b8;font-size:0.9rem;}"
        ".value{font-size:1.2rem;font-weight:700;color:#38bdf8;}"
        "table{border-collapse:collapse;width:100%;margin-top:8px;} th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #334155;} th{color:#94a3b8;} .num{text-align:right;}"
        ".empty{color:#64748b;padding:16px;}"
        "a{color:#38bdf8;}"
        ".labor-list{list-style:none;padding:0;margin:0 0 12px 0;} .labor-list li{padding:6px 0;border-bottom:1px solid #334155;} .labor-list li:last-child{border-bottom:none;}"
        ".labor-overview-list li{padding:8px 0;} .labor-summary-list li .label{margin-right:8px;} .labor-summary-list li .value{font-size:1rem;}"
        ".labor-category-list li{padding:8px 0;} .labor-category-list li a{text-decoration:underline;}"
        ".labor-note-item{color:#94a3b8;font-size:0.9rem;padding:8px 0;}"
        "details.labor-parttime-group, details.labor-fulltime-group{margin:12px 0;border:1px solid #334155;border-radius:6px;} details.labor-parttime-group summary, details.labor-fulltime-group summary{padding:10px 12px;cursor:pointer;color:#38bdf8;} details.labor-parttime-group table, details.labor-fulltime-group table{margin:8px 12px 12px;}"
    )
    if report_month is None:
        month_links = ""
        if available_months:
            month_links = "<p class='label'>分月查看： " + " | ".join(
                '<a href="/labor?month=%s">%s</a>' % (m, m) for m in available_months
            ) + "</p>"
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'/><title>人力成本</title><style>%s</style></head><body>"
            "<div class='box'><h2>👥 人力成本 · 全口径与类目</h2>"
            "%s"
            "<p class='empty'><strong>该月暂无数据</strong><br/>请选择上方月份或到 <a href='/import'>数据导入</a> 上传 Excel；"
            "若已导入，留空将显示最近月份。</p></div>"
            "<p><a href='/'>返回看板</a> | <a href='/import'>去导入</a></p></body></html>"
        ) % (base_css, month_links)
        return Response(html, mimetype="text/html; charset=utf-8")
    s = summary or {}

    by_cat = s.get("by_category") or []
    cat_ids = {"全口径": "quankoujing", "组长+组员": "leader-fulltime", "组长": "leader", "组员": "fulltime", "兼职": "parttime", "小时工": "hourly", "保洁": "cleaner", "管理岗": "management"}
    month_label = _month_label(report_month)
    # 类目列表：按类目、按月份表格化展示（组长+组员合并），便于人效分析
    months_asc, by_cat_month = _labor_category_by_month()
    category_display_order = ("全口径",) + LABOR_CATEGORY_ORDER_DISPLAY
    n_cols = 2 + len(months_asc)
    header_cells = ["<th>类目</th>", "<th class='num'>合计(元)</th>"] + [
        "<th class='num'><a href='/labor?month=%s' style='color:#38bdf8;'>%s</a></th>" % (m, _month_label(m).replace("<", "&lt;")) for m in months_asc
    ]
    table_rows = []
    for cat_name in category_display_order:
        cat_data = by_cat_month.get(cat_name, {})
        cid = cat_ids.get(cat_name, "cat")
        safe_name = (cat_name or "").replace("<", "&lt;")
        subtotal = cat_data.get("小计", {})
        total_wage = float(subtotal.get("total_wage") or 0)
        cells = [
            "<td><a href='#detail-%s' style='color:#38bdf8;text-decoration:underline;'>%s</a></td>" % (cid, safe_name),
            "<td class='num'>%s</td>" % "{:,.2f}".format(total_wage),
        ]
        for m in months_asc:
            row_data = cat_data.get(m, {"position_count": 0, "total_wage": 0})
            wage = float(row_data.get("total_wage") or 0)
            cells.append("<td class='num'><a href='/labor?month=%s#detail-%s' style='color:#38bdf8;'>%s</a></td>" % (m, cid, "{:,.2f}".format(wage)))
        table_rows.append("<tr id='row-%s'>%s</tr>" % (cid, "\n".join(cells)))
    table_body = "\n".join(table_rows) if table_rows else "<tr><td colspan='%d' class='empty'>无汇总</td></tr>" % n_cols
    note = (s.get("note") or "").replace("<", "&lt;")
    total_val = float(s.get("total_labor_cost") or 0)
    total_display = "{:,.2f}".format(total_val)
    # 若全口径明显偏低（如仅组长+组员约 13 万、实际应为约 53 万），提示用完整 Excel 重新导入
    incomplete_tip = ""
    if total_val > 0 and total_val < 400000 and len(by_cat) <= 3:
        incomplete_tip = (
            "<p class='label' style='margin-top:12px;padding:10px;background:#334155;border-radius:6px;'>"
            "若全口径应与实际支付一致（如约 53 万），请使用<strong>完整薪资表 Excel</strong>（含所有 sheet：组长、组员、兼职、小时工、保洁、管理岗）在 "
            "<a href='/import'>数据导入</a> 重新上传该月份；或在服务器上执行：<code>python scripts/import_labor_excel_and_analyze.py \"Excel路径\" 报表月份</code> 做整体导入与刷新。</p>"
        )
    def _fmt(v):
        return "{:,.2f}".format(float(v)) if v is not None else "-"
    _person_display = _labor_person_display
    leaders_tbl = "<p class='empty'>共 %d 条</p>" % len(leaders) if not leaders else (
        "<p class='label'>共 %d 人</p>" % len(leaders)
        + "<table><thead><tr><th>#</th><th>岗位</th><th>姓名</th><th>供应商</th><th class='num'>税前应发</th><th class='num'>合计薪资</th><th class='num'>实际薪资</th><th class='num'>奢品奖金</th><th class='num'>实得收入</th><th class='num'>公司成本</th><th class='num'>开票/总成本(元)</th></tr></thead><tbody>"
        + "\n".join(
            "<tr><td class='num'>%d</td><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td></tr>"
            % (
                idx,
                str(row.get("position_name") or "").replace("<", "&lt;"),
                _person_display(row.get("person_name")),
                str(row.get("supplier_name") or "").replace("<", "&lt;") or "-",
                _fmt(row.get("pre_tax_pay")),
                _fmt(row.get("total_salary")),
                _fmt(row.get("actual_salary")),
                _fmt(row.get("luxury_bonus")),
                _fmt(row.get("actual_income")),
                _fmt(row.get("company_cost")),
                _fmt(row.get("total_cost")),
            )
            for idx, row in enumerate(leaders, start=1)
        )
        + "</tbody></table>"
    )
    fulltime_tbl = "<p class='empty'>共 %d 条</p>" % len(fulltime) if not fulltime else (
        "<p class='label'>共 %d 人</p>" % len(fulltime)
        + "<table><thead><tr><th>#</th><th>岗位</th><th>姓名</th><th>供应商</th><th class='num'>工时</th><th class='num'>基本工资</th><th class='num'>绩效</th><th class='num'>岗位补贴</th><th class='num'>合计薪资</th><th class='num'>税前应发</th><th class='num'>奢品</th><th class='num'>实得收入</th><th class='num'>公司成本</th><th class='num'>开票/总成本(元)</th></tr></thead><tbody>"
        + "\n".join(
            "<tr><td class='num'>%d</td><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td></tr>"
            % (
                idx,
                str(row.get("position_name") or "").replace("<", "&lt;"),
                _person_display(row.get("person_name")),
                str(row.get("supplier_name") or "").replace("<", "&lt;") or "-",
                str(row.get("work_hours")) if row.get("work_hours") is not None else "-",
                _fmt(row.get("base_salary")),
                _fmt(row.get("performance")),
                _fmt(row.get("position_allowance")),
                _fmt(row.get("total_salary")),
                _fmt(row.get("pre_tax_pay")),
                _fmt(row.get("luxury_amount")),
                _fmt(row.get("actual_income")),
                _fmt(row.get("company_cost")),
                _fmt(row.get("total_cost")),
            )
            for idx, row in enumerate(fulltime, start=1)
        )
        + "</tbody></table>"
    )
    def _simple_cost_table(items, with_person=True):
        if not items:
            return "<p class='empty'>暂无明细</p>"
        has_person = with_person and any(str(r.get("person_name") or "").strip() for r in items)
        has_supplier = any(str(r.get("supplier_name") or "").strip() for r in items)
        if has_person:
            if has_supplier:
                trs = []
                for idx, r in enumerate(items, start=1):
                    trs.append("<tr><td class='num'>%d</td><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s 元</td></tr>" % (
                        idx,
                        str(r.get("position_name") or "-").replace("<", "&lt;"),
                        _person_display(r.get("person_name")),
                        str(r.get("supplier_name") or "").replace("<", "&lt;") or "-",
                        "{:,.2f}".format(float(r.get("total_cost") or r.get("company_cost") or 0)),
                    ))
                return "<table><thead><tr><th>#</th><th>岗位</th><th>姓名</th><th>供应商</th><th class='num'>开票/总成本(元)</th></tr></thead><tbody>%s</tbody></table>" % "\n".join(trs)
            trs = []
            for idx, r in enumerate(items, start=1):
                trs.append("<tr><td class='num'>%d</td><td>%s</td><td>%s</td><td class='num'>%s 元</td></tr>" % (
                    idx,
                    str(r.get("position_name") or "-").replace("<", "&lt;"),
                    _labor_person_display(r.get("person_name")),
                    "{:,.2f}".format(float(r.get("total_cost") or r.get("company_cost") or 0)),
                ))
            return "<table><thead><tr><th>#</th><th>岗位</th><th>姓名</th><th class='num'>开票/总成本(元)</th></tr></thead><tbody>%s</tbody></table>" % "\n".join(trs)
        trs = []
        for idx, r in enumerate(items, start=1):
            trs.append("<tr><td class='num'>%d</td><td>%s</td><td class='num'>%s 元</td></tr>" % (
                idx,
                str(r.get("position_name") or "-").replace("<", "&lt;"),
                "{:,.2f}".format(float(r.get("total_cost") or r.get("company_cost") or 0)),
            ))
        return "<table><thead><tr><th>#</th><th>岗位/姓名</th><th class='num'>开票/总成本(元)</th></tr></thead><tbody>%s</tbody></table>" % "\n".join(trs)

    def _parttime_section_html():
        """兼职：按属性汇总，点击展开显示全量明细表（店铺名、姓名、城市、属性、入职/离职、工时、时薪、发薪、服务费、税费、费用合计）"""
        by_attr = s.get("parttime_by_attribute") or []
        if not by_attr:
            return _simple_cost_table(s.get("detail_parttime") or [])
        parts = []
        for g in by_attr:
            attr_name = (g.get("attribute") or "其他").replace("<", "&lt;")
            cnt = int(g.get("count") or 0)
            total = float(g.get("total_cost") or 0)
            persons = g.get("persons") or []
            summary_line = "<strong>%s</strong> %d 人 · 费用合计 %s 元" % (attr_name, cnt, "{:,.2f}".format(total))
            # 明细表：全列
            if not persons:
                parts.append("<details class='labor-parttime-group'><summary>%s</summary><p class='empty'>无明细</p></details>" % summary_line)
                continue
            th = "<thead><tr><th>#</th><th>成本计入</th><th>店铺名</th><th>姓名</th><th>城市</th><th>属性</th><th>用人部门</th><th>入职日期</th><th>离职日期</th><th class='num'>总工时</th><th class='num'>普通工时</th><th class='num'>三薪工时</th><th class='num'>时薪</th><th class='num'>发薪金额</th><th class='num'>服务费单价</th><th class='num'>服务费总计</th><th class='num'>税费</th><th class='num'>费用合计(元)</th></tr></thead>"
            rows = []
            for idx, r in enumerate(persons, start=1):
                cost_include = str(r.get("cost_include") or "").replace("<", "&lt;") or "-"
                store_name = str(r.get("store_name") or "").replace("<", "&lt;") or "-"
                person_name = _person_display(r.get("person_name"))
                city = str(r.get("city") or "").replace("<", "&lt;") or "-"
                position_name = str(r.get("position_name") or "").replace("<", "&lt;") or "-"
                dept = str(r.get("department") or "").replace("<", "&lt;") or "-"
                join_date = str(r.get("join_date") or "").replace("<", "&lt;") or "-"
                leave_date = str(r.get("leave_date") or "").replace("<", "&lt;") or "-"
                rows.append(
                    "<tr>"
                    f"<td class='num'>{idx}</td>"
                    f"<td>{cost_include}</td>"
                    f"<td>{store_name}</td>"
                    f"<td>{person_name}</td>"
                    f"<td>{city}</td>"
                    f"<td>{position_name}</td>"
                    f"<td>{dept}</td>"
                    f"<td>{join_date}</td>"
                    f"<td class='num'>{_fmt(r.get('work_hours'))}</td>"
                    f"<td class='num'>{_fmt(r.get('normal_hours'))}</td>"
                    f"<td class='num'>{_fmt(r.get('triple_pay_hours'))}</td>"
                    f"<td class='num'>{_fmt(r.get('hourly_rate'))}</td>"
                    f"<td class='num'>{_fmt(r.get('pay_amount'))}</td>"
                    f"<td class='num'>{_fmt(r.get('service_fee_unit'))}</td>"
                    f"<td class='num'>{_fmt(r.get('service_fee_total'))}</td>"
                    f"<td class='num'>{_fmt(r.get('tax'))}</td>"
                    f"<td class='num'>{_fmt(r.get('total_cost') or r.get('company_cost'))}</td>"
                    "</tr>"
                )
            parts.append("<details class='labor-parttime-group'><summary>%s</summary><table>%s<tbody>%s</tbody></table></details>" % (summary_line, th, "\n".join(rows)))
        return "\n".join(parts)

    def _fulltime_section_html():
        """组员/全职：按岗位汇总，点击展开显示全量明细（与兼职展示逻辑一致）"""
        by_pos = s.get("fulltime_by_position") or []
        if not by_pos:
            return "<p class='empty'>暂无组员明细</p>"
        parts = []
        for g in by_pos:
            pos_name = (g.get("position") or "其他").replace("<", "&lt;")
            cnt = int(g.get("count") or 0)
            total = float(g.get("total_cost") or 0)
            persons = g.get("persons") or []
            summary_line = "<strong>%s</strong> %d 人 · 费用合计 %s 元" % (pos_name, cnt, "{:,.2f}".format(total))
            if not persons:
                parts.append("<details class='labor-fulltime-group'><summary>%s</summary><p class='empty'>无明细</p></details>" % summary_line)
                continue
            th = "<thead><tr><th>#</th><th>岗位</th><th>姓名</th><th>供应商</th><th class='num'>工时</th><th class='num'>基本工资</th><th class='num'>绩效</th><th class='num'>岗位补贴</th><th class='num'>合计薪资</th><th class='num'>税前应发</th><th class='num'>奢品</th><th class='num'>实得收入</th><th class='num'>公司成本</th><th class='num'>开票/总成本(元)</th></tr></thead>"
            rows = ["<tr><td class='num'>%d</td><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td></tr>" % (
                idx,
                str(r.get("position_name") or "").replace("<", "&lt;"),
                _person_display(r.get("person_name")),
                str(r.get("supplier_name") or "").replace("<", "&lt;") or "-",
                str(r.get("work_hours")) if r.get("work_hours") is not None else "-",
                _fmt(r.get("base_salary")), _fmt(r.get("performance")), _fmt(r.get("position_allowance")),
                _fmt(r.get("total_salary")), _fmt(r.get("pre_tax_pay")), _fmt(r.get("luxury_amount")),
                _fmt(r.get("actual_income")), _fmt(r.get("company_cost")), _fmt(r.get("total_cost")),
            ) for idx, r in enumerate(persons, start=1)]
            parts.append("<details class='labor-fulltime-group'><summary>%s</summary><table>%s<tbody>%s</tbody></table></details>" % (summary_line, th, "\n".join(rows)))
        return "\n".join(parts)

    parttime_detail = s.get("detail_parttime") or []
    hourly_detail = s.get("detail_hourly") or []
    cleaner_detail = s.get("detail_cleaner") or []
    management_detail = s.get("detail_management") or []
    month_links_html = ""
    total_positions = sum(int(c.get("position_count") or 0) for c in by_cat if (c.get("name") or "") != "全口径")
    if by_cat and (by_cat[0].get("name") or "") == "全口径":
        total_positions = int(by_cat[0].get("position_count") or 0)
    formal_count = int(s.get("formal_employee_count") or 0)
    other_count = int(s.get("other_labor_count") or 0)
    avg_cost = (total_val / total_positions) if total_positions else 0
    overview_list = _labor_months_overview()
    # 各月人力成本一览：以列表方式展示（每行一月）
    merged_summary_items = []
    if overview_list:
        for row in overview_list:
            ym = row.get("report_month") or ""
            lab = _month_label(ym)
            total = float(row.get("total_labor_cost") or 0)
            target = float(row.get("target_labor_cost") or 0)
            diff = float(row.get("labor_cost_difference") or 0)
            cnt = int(row.get("position_count") or 0)
            merged_summary_items.append(
                "<li><a href='/labor?month=%s' style='color:#38bdf8;'>%s</a> — "
                "全口径(元) %s · 实际支付(元) %s · 统计缺口(元) %s · 人数 %s 人</li>"
                % (ym, lab, "{:,.2f}".format(total), "{:,.2f}".format(target), "{:,.2f}".format(diff), cnt))
    overview_list_html = ""
    if merged_summary_items:
        overview_list_html = "<ul class='labor-list labor-overview-list'>%s</ul>" % "\n".join(merged_summary_items)
    else:
        overview_list_html = "<p class='empty'>暂无各月汇总</p>"
    labor_note = (s.get("labor_cost_difference_note") or "").replace("<", "&lt;")
    # 附表合并：各月一览 + 人力汇总数据 + 当前月/全口径/实际支付/统计缺口 + 说明（仅一次）+ 类目列表（列表项）
    category_list_items = []
    for cat_name in category_display_order:
        cat_data = by_cat_month.get(cat_name, {})
        cid = cat_ids.get(cat_name, "cat")
        safe_name = (cat_name or "").replace("<", "&lt;")
        subtotal = cat_data.get("小计", {})
        total_wage = float(subtotal.get("total_wage") or 0)
        parts = ["合计 %s 元" % "{:,.2f}".format(total_wage)]
        for m in months_asc:
            row_data = cat_data.get(m, {"position_count": 0, "total_wage": 0})
            wage = float(row_data.get("total_wage") or 0)
            lab = _month_label(m).replace("<", "&lt;")
            parts.append("<a href='/labor?month=%s#detail-%s' style='color:#38bdf8;'>%s</a> %s 元" % (m, cid, lab, "{:,.2f}".format(wage)))
        category_list_items.append(
            "<li><a href='#detail-%s' style='color:#38bdf8;'>%s</a> — %s</li>" % (cid, safe_name, " · ".join(parts))
        )
    category_list_html = "<ul class='labor-list labor-category-list'>%s</ul>" % "\n".join(category_list_items) if category_list_items else "<p class='empty'>无类目汇总</p>"
    merged_section = (
        "<div class='box' id='detail-quankoujing' style='margin-bottom:12px;background:#0f172a;border-color:#475569;'>"
        "<h2 style='margin-top:0;color:#e2e8f0;'>📊 人力汇总 · 全口径与类目（列表）</h2>"
        "%s"
        "<p class='label' style='margin-bottom:8px;'>各月人力成本一览（点击月份可查看该类目明细）</p>"
        "%s"
        "<p class='label' style='margin:16px 0 6px;'>人力汇总数据（当前月）</p>"
        "<ul class='labor-list labor-summary-list'>"
        "<li><span class='label'>报表月份</span> <strong>%s</strong></li>"
        "<li><span class='label'>全口径合计</span> <span class='value'>%s 元</span></li>"
        "<li><span class='label'>正式职工（组长+组员）</span> %s 人 · <span class='label'>其他人力</span> %s 人 · <span class='label'>总人数</span> %s 人</li>"
        "<li><span class='label'>按类型人数</span> 组长 %s 人 · 组员 %s 人 · 兼职 %s 人 · 小时工 %s 人 · 保洁 %s 人 · 管理岗 %s 人</li>"
        "<li><span class='label'>人均成本</span> %s 元/人</li>"
        "<li><span class='label'>实际支付（如开票/总成本）</span> %s 元 · <span class='label'>统计缺口</span> <span class='value'>%s 元</span></li>"
        "</ul>"
        "<p class='label labor-note-item' style='margin-top:8px;'>%s</p>"
        "<p class='label' style='margin:16px 0 6px;'>类目列表（点击类目或月份可跳转下方到人明细）</p>"
        "%s"
        "</div>"
    ) % (
        month_links_html or "",
        overview_list_html,
        report_month.replace("<", "&lt;"),
        total_display,
        formal_count,
        other_count,
        total_positions,
        int(s.get("leader_position_count") or 0),
        int(s.get("fulltime_position_count") or 0),
        int(s.get("parttime_position_count") or 0),
        int(s.get("hourly_position_count") or 0),
        int(s.get("cleaner_position_count") or 0),
        int(s.get("management_position_count") or 0),
        "{:,.2f}".format(avg_cost),
        "{:,.2f}".format(float(s.get("target_labor_cost") or 0)),
        "{:,.2f}".format(float(s.get("labor_cost_difference") or 0)),
        labor_note,
        category_list_html,
    )
    month_nav_block = ""
    # ---- 群组/供应商/人员稳定性分析区块 ----
    _group_html = ""
    _sup_html = ""
    _to_html = ""
    _ga = s.get("group_analysis") or []
    if _ga:
        _gr = "".join(
            "<tr>"
            "<td class='num'>%d</td>"
            "<td>%s</td>"
            "<td class='num'>%d 人</td>"
            "<td class='num'>%s</td>"
            "<td class='num'>%s</td>"
            "<td>%s</td>"
            "</tr>"
            % (idx+1,
               str(g.get("position_name","")).replace("<","&lt;"),
               int(g.get("headcount",0)),
               "{:,.2f}".format(float(g.get("total_cost",0))),
               "{:,.2f}".format(float(g.get("avg_cost",0))),
               str(g.get("suppliers","")).replace("<","&lt;"))
            for idx, g in enumerate(_ga)
        )
        _group_html = (
            "<div class='box' id='detail-group'><h3>群组/岗位维度人效</h3>"
            "<p class='label'>按岗位群组聚合，展示各区域/品类的人员投入与人均成本</p>"
            "<table><thead><tr><th>#</th><th>群组/区域</th><th class='num'>人数</th><th class='num'>总成本(元)</th><th class='num'>人均成本(元)</th><th>供应商</th></tr></thead><tbody>%s</tbody></table></div>"
        ) % _gr
    _sup_html = ""
    _sa = s.get("supplier_analysis") or []
    if _sa:
        _sr = "".join(
            "<tr>"
            "<td class='num'>%d</td>"
            "<td>%s</td>"
            "<td class='num'>%d 人</td>"
            "<td class='num'>%s</td>"
            "<td class='num'>%d 岗</td>"
            "<td>%s</td>"
            "</tr>"
            % (idx+1,
               str(r.get("supplier_name","")).replace("<","&lt;"),
               int(r.get("headcount",0)),
               "{:,.2f}".format(float(r.get("total_cost",0))),
               int(r.get("position_count",0)),
               str(r.get("positions","")).replace("<","&lt;"))
            for idx, r in enumerate(_sa)
        )
        _sup_html = (
            "<div class='box'><h3>供应商维度</h3>"
            "<p class='label'>各供应商提供的岗位数与费用分布</p>"
            "<table><thead><tr><th>#</th><th>供应商</th><th class='num'>人数</th><th class='num'>总成本(元)</th><th class='num'>岗位数</th><th>覆盖岗位</th></tr></thead><tbody>%s</tbody></table></div>"
        ) % _sr
    _to_html = ""
    _to = s.get("turnover_analysis") or {}
    if _to and int(_to.get("total",0)) > 0:
        _tt = int(_to["total"])
        _joined = int(_to.get("joined",0))
        _left = int(_to.get("left_count",0))
        _jr = round(_joined / _tt * 100, 1)
        _lr = round(_left / _tt * 100, 1)
        _retention = round(100 - _lr, 1)
        _to_html = (
            "<div class='box'><h3>人员稳定性</h3>"
            "<p class='label'>总人数 %d 人 · 新入职 %d 人(%s%%) · 离职 %d 人(%s%%) · 留存率 %s%%</p></div>"
        ) % (_tt, _joined, _jr, _left, _lr, _retention)

    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/><title>人力成本 · 全口径与类目 · %s</title><style>%s</style></head><body>"
        "%s"
        "%s"
        "<span id='detail-leader-fulltime'></span>"
        "<div class='box' id='detail-leader'><h3>组长/职能明细（%s）</h3>%s<p class='label' style='margin-top:8px;font-size:0.85rem;'>若姓名为「-」，请确保薪资表 Excel 含「姓名」列后重新导入。</p></div>"
        "<div class='box' id='detail-fulltime'><h3>组员/全职明细（%s）</h3><p class='label'>按岗位汇总，点击展开查看该岗位下人员及费用明细。</p>%s<p class='label' style='margin-top:8px;font-size:0.85rem;'>若姓名为「-」，请确保薪资表 Excel 含「姓名」列后重新导入。</p></div>"
        "<div class='box' id='detail-parttime'><h3>兼职明细（%s）</h3><p class='label'>按属性汇总，点击展开查看该属性下人员及费用明细。</p>%s</div>"
        "<div class='box' id='detail-hourly'><h3>小时工明细（%s）</h3>%s</div>"
        "<div class='box' id='detail-cleaner'><h3>保洁明细（%s）</h3>%s</div>"
        "<div class='box' id='detail-management'><h3>管理岗明细（%s）</h3>%s</div>"
        "%s%s%s"
        "<p class='label' style='margin-top:8px;'>人力成本基本固定，可作为经营分析的成本基准；全口径 = 组长+组员+兼职+小时工+保洁+管理岗。各类目下表均为<strong>到人明细</strong>，便于追踪人员变动与稳定情况。与「开票金额/总成本」汇总表口径一致（如沈阳 斗米全职+管理组+兼职、中锐/快聘小时工、保洁 合计约 53.25 万）。</p>"
        "<p><a href='/'>返回看板</a> | <a href='/import'>数据导入</a> | <a href='/labor_analysis'>人力分析</a> | <a href='/labor'>刷新</a> | <button type='button' id='btnLaborClear' style='margin-left:8px;padding:6px 12px;background:#64748b;color:#e2e8f0;border:1px solid #475569;border-radius:6px;cursor:pointer;font-size:0.9rem;'>清空人力数据</button></p>"
    "<script>"
    "document.getElementById('btnLaborClear') && document.getElementById('btnLaborClear').addEventListener('click', function(){"
    "  if(!confirm('【提醒】将永久删除全部人力成本明细与汇总数据，且无法恢复。仅清空人力相关表，不影响销售/库存/商品档案。\n\n确定清空？清空后需重新导入人力 Excel。')) return;"
    "  var f = new FormData(); f.append('confirm','yes');"
    "  fetch('/api/labor_cost_clear', { method:'POST', body: f, credentials:'include' })"
    "    .then(function(r){ return r.json(); })"
    "    .then(function(d){ alert(d.success ? d.message : (d.message||'失败')); if(d.success) location.reload(); })"
    "    .catch(function(){ alert('请求失败'); });"
    "});"
    "</script></body></html>"
    ) % (
        report_month.replace("<", "&lt;"),
        base_css,
        merged_section,
        month_nav_block,
        month_label.replace("<", "&lt;"), (leaders_tbl or "").replace("%", "%%"),
        month_label.replace("<", "&lt;"), (_fulltime_section_html() or "").replace("%", "%%"),
        month_label.replace("<", "&lt;"), (_parttime_section_html() or "").replace("%", "%%"),
        month_label.replace("<", "&lt;"), (_simple_cost_table(hourly_detail) or "").replace("%", "%%"),
        month_label.replace("<", "&lt;"), (_simple_cost_table(cleaner_detail) or "").replace("%", "%%"),
        month_label.replace("<", "&lt;"), (_simple_cost_table(management_detail) or "").replace("%", "%%"),
        (_group_html or "").replace("%", "%%"),
        (_sup_html or "").replace("%", "%%"),
        (_to_html or "").replace("%", "%%"),
    )
    return Response(html, mimetype="text/html; charset=utf-8")

@pages_labor_bp.route("/labor_analysis")
def page_labor_analysis():
    """人力分析 Tab 页：时间段选择、经营/管理总览、类目明细、管理按岗位与人名。"""
    if _auth_enabled() and not (os.environ.get("HTMA_UNITTEST_DISABLE_AUTH") or "").strip().lower() in ("1", "true") and (not _is_logged_in() or not _has_module_access("labor")):
        return Response("您无权访问人力分析，请联系管理员。", status=403)
    return send_from_directory(current_app.static_folder, "labor_analysis.html")
