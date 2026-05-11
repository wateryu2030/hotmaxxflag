# -*- coding: utf-8 -*-
"""人力成本与人力分析：Blueprint + url_prefix（由 app 注册）。"""
import os
import re
import statistics
import sys
import tempfile
import threading
import traceback

import pymysql
from flask import Blueprint, Response, current_app, jsonify, request, send_from_directory

from db_config import get_conn
from import_logic import (
    import_labor_cost,
    import_labor_cost_from_image,
    refresh_labor_cost_analysis,
)
from labor_utils import (
    labor_analysis_month_weights as _labor_analysis_month_weights,
    labor_analysis_mapping_effective_for_month as _labor_analysis_mapping_effective_for_month,
    labor_analysis_position_matches_mapping as _labor_analysis_position_matches_mapping,
    get_unmapped_categories,
)


def _app():
    return sys.modules.get("app")


def _auth_enabled():
    M = _app()
    return bool(M and M._auth_enabled())


def _has_module_access(module):
    M = _app()
    if M and (os.environ.get("HTMA_UNITTEST_DISABLE_AUTH") or "").strip().lower() in ("1", "true"):
        return True
    return bool(M and M._has_module_access(module))


def _is_logged_in():
    M = _app()
    return bool(M and M._is_logged_in())


labor_api_bp = Blueprint("labor_api", __name__, url_prefix="/api")
labor_analysis_api_bp = Blueprint("labor_analysis_api", __name__, url_prefix="/api/labor_analysis")


@labor_api_bp.route("/import_labor_cost", methods=["POST", "OPTIONS"])
def api_import_labor_cost():
    """上传人力成本 Excel（组长+全职+兼职/小时工/保洁/管理岗），按报表月份导入。
    支持单 sheet 或多 sheet，自动识别类目并清洗岗位名、归类写入。
    表单: file=Excel, report_month=YYYY-MM。与 scripts/import_labor_excel_and_analyze.py 使用同一 import_labor_cost 逻辑。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力成本模块，请联系管理员"}), 403
    report_month = (request.form.get("report_month") or "").strip()
    if not report_month:
        return jsonify({"success": False, "message": "请提供 report_month，如 2026-01"}), 400
    import re
    if not re.match(r"^\d{4}-\d{2}$", report_month):
        return jsonify({"success": False, "message": "report_month 格式为 YYYY-MM，如 2026-01"}), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"success": False, "message": "请上传 Excel 文件（file）"}), 400
    if not (f.filename.lower().endswith(".xls") or f.filename.lower().endswith(".xlsx")):
        return jsonify({"success": False, "message": "仅支持 .xls / .xlsx"}), 400
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.filename)[1]) as tmp:
            f.save(tmp.name)
            try:
                conn = get_conn()
                counts, diag, _ = import_labor_cost(tmp.name, report_month, conn)
                try:
                    refresh_labor_cost_analysis(conn)
                except Exception:
                    pass
                conn.close()
                # 按类目拼导入结果文案（仅列出有数据的类目）
                labels = {"leader": "组长/职能", "fulltime": "全职", "parttime": "兼职", "hourly": "小时工", "cleaner": "保洁", "management": "管理岗"}
                parts = [f"{labels.get(k, k)} {v} 条" for k, v in counts.items() if v and isinstance(v, int)]
                msg = "导入完成：" + "，".join(parts) + "；已自动清洗并归类，已刷新汇总表。请在看板「人力成本」Tab 查看（报表月份留空即最近月份）。" if parts else "导入完成：已刷新汇总表。请在看板「人力成本」Tab 查看。"
                return jsonify({
                    "success": True,
                    "report_month": report_month,
                    "leader_count": counts.get("leader", 0),
                    "fulltime_count": counts.get("fulltime", 0),
                    "counts": counts,
                    "message": msg,
                    "diagnostics": diag or [],
                })
            finally:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass
    except Exception as e:
        import traceback
        return jsonify({"success": False, "message": str(e), "traceback": traceback.format_exc()[-1500:]}), 500


@labor_api_bp.route("/import_labor_cost_image", methods=["POST", "OPTIONS"])
def api_import_labor_cost_image():
    """上传人力成本附表截图/照片，OCR 识别后写入 MySQL。表单: file=图片, report_month=YYYY-MM, position_type=leader|fulltime（必填：组长表/组员表二选一）"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力成本模块，请联系管理员"}), 403
    report_month = (request.form.get("report_month") or "").strip()
    if not report_month:
        return jsonify({"success": False, "message": "请提供 report_month，如 2026-01"}), 400
    import re
    if not re.match(r"^\d{4}-\d{2}$", report_month):
        return jsonify({"success": False, "message": "report_month 格式为 YYYY-MM"}), 400
    position_type = (request.form.get("position_type") or "").strip().lower()
    if position_type not in ("leader", "fulltime"):
        return jsonify({"success": False, "message": "请选择表类型：组长表(leader) 或 组员表(fulltime)，与附图一一对应"}), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"success": False, "message": "请上传图片文件（file）"}), 400
    low = f.filename.lower()
    if not (low.endswith(".png") or low.endswith(".jpg") or low.endswith(".jpeg")):
        return jsonify({"success": False, "message": "仅支持 .png / .jpg / .jpeg 图片"}), 400
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.filename)[1]) as tmp:
            f.save(tmp.name)
            tmp_path = tmp.name
        result = {"done": False, "leader_count": 0, "fulltime_count": 0, "diag": [], "err": None}

        def run_import():
            try:
                conn = get_conn()
                lc, fc, diag = import_labor_cost_from_image(tmp_path, report_month, conn, position_type=position_type)
                conn.close()
                result["leader_count"] = lc
                result["fulltime_count"] = fc
                result["diag"] = diag or []
            except Exception as e:
                result["err"] = str(e)
            finally:
                result["done"] = True

        th = threading.Thread(target=run_import, daemon=True)
        th.start()
        th.join(timeout=90)
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        if not result["done"]:
            return jsonify({
                "success": False,
                "message": "OCR 识别超时（90 秒），请缩小图片、裁剪仅保留表格区域，或改用 Excel 导入",
                "diagnostics": ["请求已取消"],
            })
        if result["err"]:
            return jsonify({"success": False, "message": result["err"], "diagnostics": result["diag"]})
        lc, fc = result["leader_count"], result["fulltime_count"]
        return jsonify({
            "success": True,
            "report_month": report_month,
            "leader_count": lc,
            "fulltime_count": fc,
            "message": f"附图导入完成：组长 {lc} 条，组员 {fc} 条",
            "diagnostics": result["diag"] or [],
        })
    except Exception as e:
        import traceback
        return jsonify({"success": False, "message": str(e), "traceback": traceback.format_exc()[-1500:]}), 500

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
        # 如果 position_type='leader' 无数据，从 management 取数（部分月份组长被录入为管理岗）
        if not leaders:
            cur.execute("""
                SELECT position_name, person_name, supplier_name, total_salary, pre_tax_pay, actual_salary, luxury_bonus, actual_income, company_cost, total_cost
                FROM t_htma_labor_cost WHERE report_month = %s AND position_type = 'management' ORDER BY COALESCE(total_cost, 0) DESC
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
        _show_management_separately = True
        if ("leader" not in by_type or by_type["leader"]["position_count"] == 0) and "management" in by_type:
            _show_management_separately = False  # management 将被合并到 leader，不单独显示管理岗行
        by_category = [{"name": "全口径", "total_wage": total_labor_cost, "position_count": total_positions}]
        type_to_name = LABOR_POSITION_TYPE_NAMES
        for display_name in LABOR_CATEGORY_ORDER:
            for ptype, dname in type_to_name.items():
                if dname != display_name:
                    continue
                if ptype in by_type and (by_type[ptype]["position_count"] or by_type[ptype]["total_wage"]):
                    # 如果没有 leader 行但有 management，把 management 合并到 leader 展示
                    if ptype == "management" and not _show_management_separately:
                        continue  # management 已被合并到 leader，不重复显示
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
        # 如果 leader 无数据但有 management，将 management 合并到 leader（部分月份组长被录入为管理岗）
        if leader_count == 0 and leader_total == 0 and "management" in by_type:
            leader_total = by_type["management"]["total_wage"]
            leader_count = int(by_type["management"]["position_count"])
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
        return month, [_decimals(r) for r in leaders], [_decimals(r) for r in fulltime], summary
    finally:
        conn.close()


def _labor_safe_response(f, fallback_success_json):
    """人力成本接口统一异常捕获：避免 DB/逻辑异常导致 500，始终返回 200 + JSON，便于前端独立展示错误。"""
    try:
        return f()
    except Exception as e:
        return jsonify({**fallback_success_json, "success": False, "message": "人力成本服务暂时异常，请稍后重试或使用独立页 /labor。（" + str(e)[:200] + "）"})


@labor_api_bp.route("/labor_cost_status", methods=["GET", "OPTIONS"])
def api_labor_cost_status():
    """人力成本数据状态：明细表条数、汇总表月份列表。独立于主看板 KPI 周期，异常时返回 200+success:false。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
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


@labor_api_bp.route("/labor_cost", methods=["GET", "POST", "HEAD", "OPTIONS"])
def api_labor_cost():
    """人力成本分析（短路径）。独立于主看板 KPI 周期，仅按报表月份；异常时返回 200+success:false。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力成本模块，请联系管理员"}), 403
    return _labor_safe_response(_api_labor_cost_impl, {"report_month": None, "leaders": [], "fulltime": [], "summary": {}, "message": "人力成本服务暂时异常"})


@labor_api_bp.route("/labor_cost_analysis", methods=["GET", "POST", "HEAD", "OPTIONS"])
def api_labor_cost_analysis():
    """人力成本分析（长路径，兼容旧地址）。独立于主看板，异常时返回 200+success:false。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力成本模块，请联系管理员"}), 403
    return _labor_safe_response(_api_labor_cost_impl, {"report_month": None, "leaders": [], "fulltime": [], "summary": {}, "message": "人力成本服务暂时异常"})


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


@labor_api_bp.route("/labor_cost_refresh_analysis", methods=["POST", "OPTIONS"])
def api_labor_cost_refresh_analysis():
    """从 t_htma_labor_cost 汇总刷新 t_htma_labor_cost_analysis，供 OpenClaw 或定时任务调用。"""
    if request.method == "OPTIONS":
        return "", 204
    try:
        conn = get_conn()
        n = refresh_labor_cost_analysis(conn)
        conn.close()
        return jsonify({"success": True, "months_refreshed": n})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@labor_api_bp.route("/labor_cost_clear", methods=["POST", "OPTIONS"])
def api_labor_cost_clear():
    """清空人力明细与汇总表（仅当用户明确确认时执行）。部署脚本不会清空数据，需在此手工触发。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权操作人力模块"}), 403
    confirm = (request.form.get("confirm") or request.args.get("confirm") or "").strip()
    try:
        j = request.get_json(silent=True) or {}
        if not confirm:
            confirm = (j.get("confirm") or "").strip()
    except Exception:
        pass
    if confirm != "yes":
        return jsonify({"success": False, "message": "请传 confirm=yes 确认清空（将删除 t_htma_labor_cost 与 t_htma_labor_cost_analysis 全部数据）"}), 400
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE t_htma_labor_cost")
        cur.execute("TRUNCATE TABLE t_htma_labor_cost_analysis")
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "已清空人力明细与汇总表，可重新导入 Excel"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500



def _labor_analysis_get_cost(row):
    """单条人力记录的成本金额。"""
    return float(row.get("total_cost") or row.get("company_cost") or 0)


@labor_analysis_api_bp.route("/categories", methods=["GET", "OPTIONS"])
def api_labor_analysis_categories():
    """返回销售日报中的大类+中类（供配置映射，与 t_htma_sale 一致）。结构：categories 平铺大类；categories_tree 为大类下挂中类列表。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    try:
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT DISTINCT
                    COALESCE(TRIM(category_large_code), '') AS category_large_code,
                    COALESCE(TRIM(category_large), '') AS category_large,
                    COALESCE(TRIM(category_mid_code), '') AS category_mid_code,
                    COALESCE(TRIM(category_mid), '') AS category_mid
                FROM t_htma_sale
                WHERE (COALESCE(TRIM(category_large), '') != '' OR COALESCE(TRIM(category_large_code), '') != '')
                ORDER BY category_large_code, category_large, category_mid_code, category_mid
            """)
            rows = cur.fetchall()
        except Exception:
            try:
                cur.execute("""
                    SELECT DISTINCT
                        COALESCE(TRIM(category_large), '') AS category_large_code,
                        COALESCE(TRIM(category_large), '') AS category_large,
                        '' AS category_mid_code, '' AS category_mid
                    FROM t_htma_sale
                    WHERE (category_large IS NOT NULL AND TRIM(category_large) != '')
                    ORDER BY category_large
                """)
                rows = cur.fetchall()
            except Exception:
                try:
                    cur.execute("""
                        SELECT DISTINCT COALESCE(TRIM(category), '') AS category_large_code,
                               COALESCE(TRIM(category), '') AS category_large,
                               '' AS category_mid_code, '' AS category_mid
                        FROM t_htma_sale
                        WHERE (category IS NOT NULL AND TRIM(category) != '')
                        ORDER BY 1
                    """)
                    rows = cur.fetchall()
                except Exception:
                    rows = []
        conn.close()
        # 大类去重 + 每个大类下中类列表
        large_seen = set()
        categories = []
        categories_tree = []
        for r in rows:
            lcode = (r.get("category_large_code") or "").strip()
            lname = (r.get("category_large") or "").strip()
            if not lname and lcode:
                lname = lcode
            if not lname:
                continue
            mcode = (r.get("category_mid_code") or "").strip()
            mname = (r.get("category_mid") or "").strip()
            if not mname and mcode:
                mname = mcode
            key = (lcode, lname)
            if key not in large_seen:
                large_seen.add(key)
                categories.append({"category_large_code": lcode, "category_large": lname})
                categories_tree.append({
                    "category_large_code": lcode,
                    "category_large": lname,
                    "mids": []
                })
            # 找到对应大类节点并追加中类（去重）
            for node in categories_tree:
                if (node["category_large_code"], node["category_large"]) == (lcode, lname):
                    if (mcode or mname) and not any(x.get("category_mid") == mname and x.get("category_mid_code") == mcode for x in node["mids"]):
                        node["mids"].append({"category_mid_code": mcode, "category_mid": mname or "-"})
                    break
        return jsonify({"success": True, "categories": categories, "categories_tree": categories_tree})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@labor_analysis_api_bp.route("/labor_positions", methods=["GET", "POST", "HEAD", "OPTIONS"])
def api_labor_analysis_labor_positions():
    """拉取所有人力成本汇总岗位列表，以组长表为准（组长/leader 优先，与薪资表、组长表岗位一致）。GET/POST 均返回同一列表。"""
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "HEAD":
        return "", 200
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    try:
        conn = get_conn()
        cur = conn.cursor()
        # 组长(leader) 优先，再全职、兼职等；岗位名去重，与 t_htma_labor_cost.position_name 一致
        try:
            cur.execute("""
                SELECT DISTINCT COALESCE(TRIM(position_name), '') AS position_name,
                       COALESCE(TRIM(position_type), '') AS position_type
                FROM t_htma_labor_cost
                WHERE (position_name IS NOT NULL AND TRIM(position_name) != '')
                ORDER BY FIELD(position_type, 'leader', 'fulltime', 'parttime', 'hourly', 'cleaner', 'management'),
                         position_name
            """)
            rows = cur.fetchall()
        except Exception:
            try:
                cur.execute("""
                    SELECT DISTINCT COALESCE(TRIM(position_name), '') AS position_name,
                           COALESCE(TRIM(position_type), '') AS position_type
                    FROM t_htma_labor_cost
                    WHERE (position_name IS NOT NULL AND TRIM(position_name) != '')
                    ORDER BY position_type, position_name
                """)
                rows = cur.fetchall()
            except Exception:
                rows = []
        conn.close()
        type_label = {"leader": "组长", "fulltime": "全职", "parttime": "兼职", "hourly": "小时工", "cleaner": "保洁", "management": "管理岗"}
        positions = []
        seen = set()
        for r in rows:
            name = (r.get("position_name") or "").strip()
            if not name:
                continue
            if name in seen:
                continue
            seen.add(name)
            ptype = (r.get("position_type") or "").strip().lower()
            positions.append({
                "position_name": name,
                "position_type": ptype,
                "position_type_label": type_label.get(ptype, ptype or "其他"),
            })
        return jsonify({"success": True, "positions": positions})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@labor_analysis_api_bp.route("/mapping", methods=["GET", "POST", "OPTIONS"])
def api_labor_analysis_mapping():
    """获取或保存 销售类目–人力岗位 映射（含生效日期）。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    try:
        conn = get_conn()
        cur = conn.cursor()
        if request.method == "GET":
            try:
                cur.execute("""
                    SELECT id, sales_category, sales_category_mid, sales_category_large_code, sales_category_mid_code,
                           cost_type, labor_position_name, match_type,
                           effective_from, effective_to, sort_order, created_at, updated_at
                    FROM t_htma_labor_category_mapping
                    ORDER BY cost_type, sort_order, id
                """)
                rows = cur.fetchall()
            except Exception:
                try:
                    cur.execute("""
                        SELECT id, sales_category, sales_category_mid, cost_type, labor_position_name, match_type,
                               effective_from, effective_to, sort_order, created_at, updated_at
                        FROM t_htma_labor_category_mapping
                        ORDER BY cost_type, sort_order, id
                    """)
                    rows = cur.fetchall()
                except Exception:
                    try:
                        cur.execute("""
                            SELECT id, sales_category, cost_type, labor_position_name, match_type,
                                   effective_from, effective_to, sort_order, created_at, updated_at
                            FROM t_htma_labor_category_mapping
                            ORDER BY cost_type, sort_order, id
                        """)
                        rows = cur.fetchall()
                    except Exception:
                        rows = []
            conn.close()
            items = []
            for r in rows:
                r = r or {}
                items.append({
                    "id": r.get("id"),
                    "sales_category": r.get("sales_category") or "",
                    "sales_category_mid": r.get("sales_category_mid") or "",
                    "sales_category_large_code": r.get("sales_category_large_code") or "",
                    "sales_category_mid_code": r.get("sales_category_mid_code") or "",
                    "cost_type": r.get("cost_type") or "",
                    "labor_position_name": r.get("labor_position_name") or "",
                    "match_type": r.get("match_type") or "prefix",
                    "effective_from": r.get("effective_from").strftime("%Y-%m-%d") if r.get("effective_from") else None,
                    "effective_to": r.get("effective_to").strftime("%Y-%m-%d") if r.get("effective_to") else None,
                    "sort_order": r.get("sort_order", 0),
                })
            return jsonify({"success": True, "items": items})
        # POST: save one or list
        data = request.get_json(silent=True) or {}
        items = data.get("items")
        if not items:
            items = [data] if data.get("labor_position_name") or data.get("sales_category") or data.get("sales_category_large_code") else []
        for it in items:
            sid = it.get("id")
            sales_category = (it.get("sales_category") or "").strip() or ""
            sales_category_mid = (it.get("sales_category_mid") or "").strip() or ""
            sales_category_large_code = (it.get("sales_category_large_code") or "").strip() or ""
            sales_category_mid_code = (it.get("sales_category_mid_code") or "").strip() or ""
            cost_type = (it.get("cost_type") or "operational").strip().lower()
            if cost_type not in ("operational", "management"):
                cost_type = "operational"
            labor_position_name = (it.get("labor_position_name") or "").strip()
            match_type = (it.get("match_type") or "prefix").strip().lower() or "prefix"
            if match_type not in ("exact", "prefix"):
                match_type = "prefix"
            effective_from = (it.get("effective_from") or "").strip() or None
            effective_to = (it.get("effective_to") or "").strip() or None
            sort_order = int(it.get("sort_order", 0))
            if not labor_position_name and not sales_category and not sales_category_large_code:
                continue
            try:
                if sid:
                    cur.execute("""
                        UPDATE t_htma_labor_category_mapping
                        SET sales_category=%s, sales_category_mid=%s, sales_category_large_code=%s, sales_category_mid_code=%s,
                            cost_type=%s, labor_position_name=%s, match_type=%s,
                            effective_from=%s, effective_to=%s, sort_order=%s, updated_at=NOW()
                        WHERE id=%s
                    """, (sales_category, sales_category_mid, sales_category_large_code, sales_category_mid_code,
                          cost_type, labor_position_name, match_type,
                          effective_from or None, effective_to or None, sort_order, sid))
                else:
                    cur.execute("""
                        INSERT INTO t_htma_labor_category_mapping
                        (sales_category, sales_category_mid, sales_category_large_code, sales_category_mid_code,
                         cost_type, labor_position_name, match_type, effective_from, effective_to, sort_order)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (sales_category, sales_category_mid, sales_category_large_code, sales_category_mid_code,
                          cost_type, labor_position_name, match_type, effective_from or None, effective_to or None, sort_order))
            except Exception:
                if sid:
                    cur.execute("""
                        UPDATE t_htma_labor_category_mapping
                        SET sales_category=%s, sales_category_mid=%s, cost_type=%s, labor_position_name=%s, match_type=%s,
                            effective_from=%s, effective_to=%s, sort_order=%s, updated_at=NOW()
                        WHERE id=%s
                    """, (sales_category, sales_category_mid, cost_type, labor_position_name, match_type,
                          effective_from or None, effective_to or None, sort_order, sid))
                else:
                    cur.execute("""
                        INSERT INTO t_htma_labor_category_mapping
                        (sales_category, sales_category_mid, cost_type, labor_position_name, match_type, effective_from, effective_to, sort_order)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (sales_category, sales_category_mid, cost_type, labor_position_name, match_type, effective_from or None, effective_to or None, sort_order))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "已保存"})
    except Exception as e:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return jsonify({"success": False, "message": str(e)}), 500


def _labor_analysis_overview(conn, start_date, end_date, store_id=None):
    """经营/管理总成本、总人数（全量不去重）、销售、毛利、人效。store_id 非空时销售汇总限定该店。"""
    weights = _labor_analysis_month_weights(start_date, end_date)
    if not weights:
        return {"operational_cost": 0, "management_cost": 0, "total_cost": 0, "total_headcount": 0,
                "total_sale": 0, "total_profit": 0, "sales_per_cost": 0, "profit_per_cost": 0,
                "sales_per_capita": 0, "profit_per_capita": 0, "profit_cost_ratio": 0}
    cur = conn.cursor()
    # 销售
    try:
        if store_id:
            cur.execute("""
                SELECT COALESCE(SUM(sale_amount),0) AS total_sale, COALESCE(SUM(gross_profit),0) AS total_profit
                FROM t_htma_sale WHERE data_date BETWEEN %s AND %s AND store_id = %s
            """, (start_date, end_date, store_id))
        else:
            cur.execute("""
                SELECT COALESCE(SUM(sale_amount),0) AS total_sale, COALESCE(SUM(gross_profit),0) AS total_profit
                FROM t_htma_sale WHERE data_date BETWEEN %s AND %s
            """, (start_date, end_date))
        row = cur.fetchone()
        total_sale = float(row.get("total_sale") or 0)
        total_profit = float(row.get("total_profit") or 0)
    except Exception:
        total_sale = total_profit = 0
    operational_cost = 0.0
    management_cost = 0.0
    operational_head = 0.0
    management_head = 0.0
    for ym, weight in weights:
        mapping = _labor_analysis_mapping_effective_for_month(conn, ym)
        op_positions = set()
        mgr_positions = set()
        for m in mapping:
            cost_type = (m.get("cost_type") or "").strip().lower()
            lab = (m.get("labor_position_name") or "").strip()
            if cost_type == "management":
                mgr_positions.add((lab, m.get("match_type") or "prefix"))
            else:
                op_positions.add((lab, m.get("match_type") or "prefix"))
        try:
            cur.execute("""
                SELECT position_name, position_type, person_name,
                       COALESCE(total_cost, company_cost) AS cost
                FROM t_htma_labor_cost WHERE report_month = %s
            """, (ym,))
            labor_rows = cur.fetchall()
        except Exception:
            labor_rows = []
        # 经营 vs 管理：仅按映射表拆分。无任何映射时全部计入经营；有映射时，仅命中「管理」的计入管理，其余（含未在映射表中的岗位）默认归经营（与设计文档一致）
        no_mapping = not op_positions and not mgr_positions
        for r in labor_rows:
            pos = (r.get("position_name") or "").strip()
            cost = float(r.get("cost") or 0) * weight
            matched_mgr = any(_labor_analysis_position_matches_mapping(pos, lab, mt) for lab, mt in mgr_positions)
            matched_op = any(_labor_analysis_position_matches_mapping(pos, lab, mt) for lab, mt in op_positions)
            if matched_mgr:
                management_cost += cost
                management_head += weight
            else:
                # 命中经营 或 无映射 或 未在映射表中：均计入经营
                operational_cost += cost
                operational_head += weight
    total_cost = operational_cost + management_cost
    total_headcount = operational_head + management_head
    total_sale = total_sale
    total_profit = total_profit
    sales_per_cost = total_sale / total_cost if total_cost else 0
    profit_per_cost = total_profit / total_cost if total_cost else 0
    sales_per_capita = total_sale / total_headcount if total_headcount else 0
    profit_per_capita = total_profit / total_headcount if total_headcount else 0
    profit_cost_ratio = total_profit / total_cost if total_cost else 0
    return {
        "operational_cost": round(operational_cost, 2),
        "management_cost": round(management_cost, 2),
        "total_cost": round(total_cost, 2),
        "total_headcount": round(total_headcount, 2),
        "total_sale": round(total_sale, 2),
        "total_profit": round(total_profit, 2),
        "sales_per_cost": round(sales_per_cost, 4),
        "profit_per_cost": round(profit_per_cost, 4),
        "sales_per_capita": round(sales_per_capita, 2),
        "profit_per_capita": round(profit_per_capita, 2),
        "profit_cost_ratio": round(profit_cost_ratio, 4),
    }


@labor_analysis_api_bp.route("/overview", methods=["GET", "OPTIONS"])
def api_labor_analysis_overview():
    """人力分析总览：经营/管理成本、人数（全量）、销售、毛利、人效。参数 start_date, end_date。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    start_date = (request.args.get("start_date") or "").strip()[:10]
    end_date = (request.args.get("end_date") or "").strip()[:10]
    if not start_date or not end_date:
        return jsonify({"success": False, "message": "请提供 start_date 与 end_date"}), 400
    try:
        conn = get_conn()
        data = _labor_analysis_overview(conn, start_date, end_date)
        conn.close()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


def _labor_analysis_by_category(conn, start_date, end_date, store_id=None):
    """按经营类目：人力成本、人数、销售、毛利、人效。以销售日报大类为准（按大类代码匹配），全部展示；未配置映射的类目人力为0。store_id 非空时销售侧限定该店。"""
    weights = _labor_analysis_month_weights(start_date, end_date)
    cur = conn.cursor()
    # 销售日报中所有大类：按大类代码分组（与看板一致），无代码时用名称
    try:
        if store_id:
            cur.execute("""
                SELECT COALESCE(NULLIF(TRIM(category_large_code), ''), TRIM(category_large)) AS code,
                       COALESCE(MAX(TRIM(category_large)), '') AS cat,
                       COALESCE(SUM(sale_amount),0) AS s, COALESCE(SUM(gross_profit),0) AS p
                FROM t_htma_sale
                WHERE data_date BETWEEN %s AND %s AND store_id = %s
                  AND (COALESCE(TRIM(category_large_code), '') != '' OR (category_large IS NOT NULL AND TRIM(category_large) != ''))
                GROUP BY COALESCE(NULLIF(TRIM(category_large_code), ''), TRIM(category_large))
                ORDER BY code
            """, (start_date, end_date, store_id))
        else:
            cur.execute("""
                SELECT COALESCE(NULLIF(TRIM(category_large_code), ''), TRIM(category_large)) AS code,
                       COALESCE(MAX(TRIM(category_large)), '') AS cat,
                       COALESCE(SUM(sale_amount),0) AS s, COALESCE(SUM(gross_profit),0) AS p
                FROM t_htma_sale
                WHERE data_date BETWEEN %s AND %s AND (COALESCE(TRIM(category_large_code), '') != '' OR (category_large IS NOT NULL AND TRIM(category_large) != ''))
                GROUP BY COALESCE(NULLIF(TRIM(category_large_code), ''), TRIM(category_large))
                ORDER BY code
            """, (start_date, end_date))
        sales_rows = cur.fetchall()
        sales_by_code = {r.get("code") or "": (float(r.get("s") or 0), float(r.get("p") or 0)) for r in sales_rows}
        code_to_name = {r.get("code") or "": (r.get("cat") or "") for r in sales_rows}
    except Exception:
        sales_by_code = {}
        code_to_name = {}
    # 经营类目及其对应岗位：按大类代码匹配（优先），无代码时按名称兼容旧数据
    cat_positions = {}
    for ym, _ in weights:
        for m in _labor_analysis_mapping_effective_for_month(conn, ym):
            if (m.get("cost_type") or "").strip().lower() != "operational":
                continue
            large_code = (m.get("sales_category_large_code") or "").strip()
            cat_name = (m.get("sales_category") or "").strip()
            key = large_code if large_code else cat_name
            if not key:
                continue
            if key not in cat_positions:
                cat_positions[key] = set()
            cat_positions[key].add(((m.get("labor_position_name") or "").strip(), m.get("match_type") or "prefix"))
    # 以销售大类为全集，无映射的类目人力为 0
    out = []
    for code in sorted(sales_by_code.keys()):
        positions = cat_positions.get(code, set()) or cat_positions.get(code_to_name.get(code, ""), set())
        cost_total = 0.0
        headcount = 0.0
        by_type = {"leader": {"cost": 0, "count": 0}, "fulltime": {"cost": 0, "count": 0}, "parttime": {"cost": 0, "count": 0}, "other": {"cost": 0, "count": 0}}
        for ym, weight in weights:
            mapping = _labor_analysis_mapping_effective_for_month(conn, ym)
            op_set = set()
            for m in mapping:
                if (m.get("cost_type") or "").strip().lower() != "operational":
                    continue
                large_code_m = (m.get("sales_category_large_code") or "").strip()
                cat_name_m = (m.get("sales_category") or "").strip()
                if large_code_m and large_code_m != code:
                    continue
                if not large_code_m and cat_name_m != (code_to_name.get(code) or ""):
                    continue
                op_set.add(((m.get("labor_position_name") or "").strip(), m.get("match_type") or "prefix"))
            try:
                cur.execute("""
                    SELECT position_name, position_type, COALESCE(total_cost, company_cost) AS cost
                    FROM t_htma_labor_cost WHERE report_month = %s
                """, (ym,))
                rows = cur.fetchall()
            except Exception:
                rows = []
            for r in rows:
                pos = (r.get("position_name") or "").strip()
                if not any(_labor_analysis_position_matches_mapping(pos, lab, mt) for lab, mt in op_set):
                    continue
                c = float(r.get("cost") or 0) * weight
                cost_total += c
                headcount += weight
                pt = (r.get("position_type") or "").strip().lower()
                if pt in by_type:
                    by_type[pt]["cost"] += c
                    by_type[pt]["count"] += weight
                else:
                    by_type["other"]["cost"] += c
                    by_type["other"]["count"] += weight
        s, p = sales_by_code.get(code, (0, 0))
        margin_pct = round(p / s * 100, 2) if s > 0 else 0.0
        labor_cost_per_sale = round(cost_total / s, 6) if s > 0 else None
        labor_cost_per_profit = round(cost_total / p, 6) if p > 0 else None
        out.append({
            "category_large_code": code,
            "category": code_to_name.get(code, "") or code,
            "labor_cost": round(cost_total, 2),
            "headcount": round(headcount, 2),
            "sale": round(s, 2),
            "profit": round(p, 2),
            "margin_pct": margin_pct,
            "labor_cost_per_sale": labor_cost_per_sale,
            "labor_cost_per_profit": labor_cost_per_profit,
            "sales_per_cost": round(s / cost_total, 4) if cost_total else 0,
            "profit_per_cost": round(p / cost_total, 4) if cost_total else 0,
            "sales_per_capita": round(s / headcount, 2) if headcount else 0,
            "profit_cost_ratio": round(p / cost_total, 4) if cost_total else 0,
            "by_position_type": {k: {"cost": round(v["cost"], 2), "count": round(v["count"], 2)} for k, v in by_type.items()},
        })
    return out


@labor_analysis_api_bp.route("/by_category", methods=["GET", "OPTIONS"])
def api_labor_analysis_by_category():
    """按经营类目返回人力成本、人数、销售、毛利、人效及组长/全职/兼职分项。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    start_date = (request.args.get("start_date") or "").strip()[:10]
    end_date = (request.args.get("end_date") or "").strip()[:10]
    if not start_date or not end_date:
        return jsonify({"success": False, "message": "请提供 start_date 与 end_date"}), 400
    try:
        conn = get_conn()
        data = _labor_analysis_by_category(conn, start_date, end_date)
        conn.close()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


def _labor_analysis_management(conn, start_date, end_date):
    """管理人力：按岗位拆开展示，每岗位可下沉到具体人名及分摊成本。"""
    weights = _labor_analysis_month_weights(start_date, end_date)
    cur = conn.cursor()
    # 管理岗位列表（映射中 cost_type=management）
    mgr_positions = set()
    for ym, _ in weights:
        for m in _labor_analysis_mapping_effective_for_month(conn, ym):
            if (m.get("cost_type") or "").strip().lower() != "management":
                continue
            mgr_positions.add(((m.get("labor_position_name") or "").strip(), m.get("match_type") or "prefix"))
    if not mgr_positions:
        return {"total_cost": 0, "total_headcount": 0, "by_position": [], "persons": []}
    by_position = {}
    persons = []
    for ym, weight in weights:
        try:
            cur.execute("""
                SELECT position_name, person_name, COALESCE(total_cost, company_cost) AS cost
                FROM t_htma_labor_cost WHERE report_month = %s
            """, (ym,))
            rows = cur.fetchall()
        except Exception:
            rows = []
        for r in rows:
            pos = (r.get("position_name") or "").strip()
            if not any(_labor_analysis_position_matches_mapping(pos, lab, mt) for lab, mt in mgr_positions):
                continue
            cost = float(r.get("cost") or 0) * weight
            pname = _labor_person_display(r.get("person_name") or "")
            if pos not in by_position:
                by_position[pos] = {"position_name": pos, "cost": 0.0, "headcount": 0.0, "persons": []}
            by_position[pos]["cost"] += cost
            by_position[pos]["headcount"] += weight
            by_position[pos]["persons"].append({"person_name": pname, "prorated_cost": round(cost, 2)})
            persons.append({"position_name": pos, "person_name": pname, "prorated_cost": round(cost, 2)})
    total_cost = sum(p["cost"] for p in by_position.values())
    total_headcount = sum(p["headcount"] for p in by_position.values())
    by_position_list = []
    for pos_name, p in by_position.items():
        by_position_list.append({
            "position_name": pos_name,
            "cost": round(p["cost"], 2),
            "headcount": round(p["headcount"], 2),
            "persons": p["persons"],
        })
    return {
        "total_cost": round(total_cost, 2),
        "total_headcount": round(total_headcount, 2),
        "by_position": by_position_list,
        "persons": persons,
    }


@labor_analysis_api_bp.route("/management", methods=["GET", "OPTIONS"])
def api_labor_analysis_management():
    """管理人力：按岗位拆分，可下沉到具体人名。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    start_date = (request.args.get("start_date") or "").strip()[:10]
    end_date = (request.args.get("end_date") or "").strip()[:10]
    if not start_date or not end_date:
        return jsonify({"success": False, "message": "请提供 start_date 与 end_date"}), 400
    try:
        conn = get_conn()
        data = _labor_analysis_management(conn, start_date, end_date)
        conn.close()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@labor_analysis_api_bp.route("/mapping_health", methods=["GET", "OPTIONS"])
def api_labor_analysis_mapping_health():
    """有大类销售但未配置经营岗位映射的列表。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    start_d = (request.args.get("start_date") or "").strip()[:10]
    end_d = (request.args.get("end_date") or "").strip()[:10]
    if not start_d or not end_d:
        return jsonify({"success": False, "message": "请提供 start_date 与 end_date"}), 400
    M = _app()
    store_id = (M.STORE_ID if M else "沈阳超级仓")
    conn = get_conn()
    try:
        unmapped = get_unmapped_categories(conn, start_d, end_d, store_id=store_id)
    finally:
        conn.close()
    return jsonify({"success": True, "unmapped": unmapped})


@labor_api_bp.route("/four_quadrant", methods=["GET", "OPTIONS"])
def api_four_quadrant():
    """毛利率 × 人力强度（人力/毛利），毛利≤0 的类目不纳入。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("labor"):
        return jsonify({"success": False, "message": "无权访问人力模块"}), 403
    start_d = (request.args.get("start_date") or "").strip()[:10]
    end_d = (request.args.get("end_date") or "").strip()[:10]
    if not start_d or not end_d:
        return jsonify({"success": False, "message": "请提供 start_date 与 end_date"}), 400
    conn = get_conn()
    try:
        rows = _labor_analysis_by_category(conn, start_d, end_d)
    finally:
        conn.close()
    points = []
    for r in rows or []:
        sale = float(r.get("sale") or 0)
        profit = float(r.get("profit") or 0)
        labor = float(r.get("labor_cost") or 0)
        if profit <= 0:
            continue
        m_pct = float(r.get("margin_pct") or (profit / sale * 100 if sale > 0 else 0))
        intensity = labor / profit
        points.append({
            "category_large": r.get("category") or r.get("category_large_code") or "",
            "category_large_code": r.get("category_large_code") or "",
            "margin_pct": round(m_pct, 2),
            "labor_intensity": round(intensity, 4),
            "sale": round(sale, 2),
            "labor_cost": round(labor, 2),
            "profit": round(profit, 2),
        })
    mx = statistics.median([p["margin_pct"] for p in points]) if len(points) >= 1 else 0
    my = statistics.median([p["labor_intensity"] for p in points]) if len(points) >= 1 else 0
    return jsonify({
        "success": True,
        "median_margin_pct": round(mx, 2),
        "median_labor_intensity": round(my, 4),
        "points": points,
    })


# 供 routes_category 等模块调用（与历史 app._labor_analysis_by_category 等价）
labor_analysis_by_category = _labor_analysis_by_category


def register_labor_blueprints(app):
    app.register_blueprint(labor_api_bp)
    app.register_blueprint(labor_analysis_api_bp)
