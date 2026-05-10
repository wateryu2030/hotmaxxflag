# -*- coding: utf-8 -*-
"""serve_web/profit_share：利润分成 API（规则、排除品类、计算、结果预览）"""

from flask import Blueprint, jsonify, request, session
from datetime import date, datetime, timedelta
from decimal import Decimal
import json, re, pymysql, pymysql.cursors

from core.db import get_conn
from core.context import _effective_store_id
from core.utils import safe_float, safe_str

profit_share_bp = Blueprint("profit_share", __name__)

def _profit_share_forbidden():
    return jsonify({"error": "无权限"}), 403
@profit_share_bp.route("/api/profit_share/rule", methods=["GET"])
def api_profit_share_rule_get():
    """获取分账规则：当前启用规则 + 全部规则列表"""
    if _auth_enabled() and not _has_module_access("profit_share"):
        return _profit_share_forbidden()
    try:
        conn = get_conn()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT * FROM t_profit_share_rule ORDER BY effective_start DESC")
        all_rules = cur.fetchall()
        for r in all_rules:
            if r.get("effective_end"):
                r["effective_end"] = r["effective_end"].strftime("%Y-%m-%d") if hasattr(r["effective_end"], "strftime") else str(r["effective_end"])
            if r.get("effective_start"):
                r["effective_start"] = r["effective_start"].strftime("%Y-%m-%d") if hasattr(r["effective_start"], "strftime") else str(r["effective_start"])
        active = next((r for r in all_rules if r.get("is_active")), None)
        conn.close()
        return jsonify({"active_rule": active, "all_rules": all_rules})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@profit_share_bp.route("/api/profit_share/rule", methods=["POST"])
def api_profit_share_rule_post():
    """新增或更新分账规则；若 is_active=1 则将其它规则设为禁用"""
    if _auth_enabled() and not _has_module_access("profit_share"):
        return _profit_share_forbidden()
    try:
        j = request.get_json(silent=True) or {}
        rid = j.get("id")
        stage_name = (j.get("stage_name") or "").strip()
        share_rate_merchant = j.get("share_rate_merchant")
        share_rate_platform = j.get("share_rate_platform")
        effective_start = (j.get("effective_start") or "").strip()[:10]
        effective_end = (j.get("effective_end") or "").strip()[:10] or None
        is_active = 1 if j.get("is_active") in (True, 1, "1") else 0
        if not stage_name or share_rate_merchant is None or share_rate_platform is None or not effective_start:
            return jsonify({"error": "缺少必填：stage_name, share_rate_merchant, share_rate_platform, effective_start"}), 400
        conn = get_conn()
        cur = conn.cursor()
        if is_active:
            cur.execute("UPDATE t_profit_share_rule SET is_active = 0")
        if rid:
            cur.execute("""
                UPDATE t_profit_share_rule SET stage_name=%s, share_rate_merchant=%s, share_rate_platform=%s,
                effective_start=%s, effective_end=%s, is_active=%s WHERE id=%s
            """, (stage_name, share_rate_merchant, share_rate_platform, effective_start, effective_end, is_active, rid))
        else:
            cur.execute("""
                INSERT INTO t_profit_share_rule (stage_name, share_rate_merchant, share_rate_platform, effective_start, effective_end, is_active)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (stage_name, share_rate_merchant, share_rate_platform, effective_start, effective_end, is_active))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@profit_share_bp.route("/api/profit_share/rule/<int:rule_id>", methods=["DELETE"])
def api_profit_share_rule_delete(rule_id):
    if _auth_enabled() and not _has_module_access("profit_share"):
        return _profit_share_forbidden()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM t_profit_share_rule WHERE id = %s", (rule_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@profit_share_bp.route("/api/profit_share/exclude_categories", methods=["GET"])
def api_profit_share_exclude_get():
    if _auth_enabled() and not _has_module_access("profit_share"):
        return _profit_share_forbidden()
    try:
        conn = get_conn()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT * FROM t_profit_share_exclude_category ORDER BY id")
        rows = cur.fetchall()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@profit_share_bp.route("/api/profit_share/exclude_categories", methods=["POST"])
def api_profit_share_exclude_post():
    if _auth_enabled() and not _has_module_access("profit_share"):
        return _profit_share_forbidden()
    try:
        j = request.get_json(silent=True) or {}
        large_code = (j.get("category_large_code") or "").strip() or None
        large_name = (j.get("category_large_name") or "").strip() or None
        mid_code = (j.get("category_mid_code") or "").strip() or None
        mid_name = (j.get("category_mid_name") or "").strip() or None
        if not large_code:
            return jsonify({"error": "请提供 category_large_code"}), 400
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO t_profit_share_exclude_category (category_large_code, category_large_name, category_mid_code, category_mid_name)
            VALUES (%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE category_large_name=VALUES(category_large_name), category_mid_name=VALUES(category_mid_name)
        """, (large_code, large_name, mid_code, mid_name))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@profit_share_bp.route("/api/profit_share/exclude_categories/<int:exclude_id>", methods=["DELETE"])
def api_profit_share_exclude_delete(exclude_id):
    if _auth_enabled() and not _has_module_access("profit_share"):
        return _profit_share_forbidden()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM t_profit_share_exclude_category WHERE id = %s", (exclude_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def _profit_share_parse_period(j):
    """从请求体解析计算周期。支持 month (YYYY-MM) 或 start_date + end_date。返回 (start_d, end_d, period_label) 或 (None, None, None) 与 error。"""
    month = (j.get("month") or "").strip()
    start_s = (j.get("start_date") or "").strip()[:10]
    end_s = (j.get("end_date") or "").strip()[:10]
    if month and len(month) == 7 and month[4] == "-":
        try:
            year, mon = int(month[:4]), int(month[5:7])
            start_d = date(year, mon, 1)
            end_d = (start_d + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            return start_d, end_d, month, None
        except Exception as e:
            return None, None, None, "月份格式错误: " + str(e)
    if start_s and end_s:
        try:
            start_d = date(int(start_s[:4]), int(start_s[5:7]), int(start_s[8:10]))
            end_d = date(int(end_s[:4]), int(end_s[5:7]), int(end_s[8:10]))
            if start_d > end_d:
                return None, None, None, "开始日期不能晚于结束日期"
            return start_d, end_d, start_s + " ~ " + end_s, None
        except Exception as e:
            return None, None, None, "日期格式错误(需 YYYY-MM-DD): " + str(e)
    return None, None, None, "请提供 month(YYYY-MM) 或 start_date、end_date(YYYY-MM-DD)"
@profit_share_bp.route("/api/profit_share/calculate", methods=["POST"])
def api_profit_share_calculate():
    """分账计算：支持按月份或自定义时间段。取启用规则，从 t_htma_profit 聚合（排除配置的品类），写入结果表并返回汇总与明细（含全口径/排除/参与、分账表）。"""
    if _auth_enabled() and not _has_module_access("profit_share"):
        return _profit_share_forbidden()
    try:
        j = request.get_json(silent=True) or {}
        if not j and request.form:
            j = {k: v for k, v in request.form.items()}
        if not j and request.args:
            j = {k: v for k, v in request.args.items()}
        start_d, end_d, period_label, err = _profit_share_parse_period(j)
        if err:
            return jsonify({"error": err}), 400
        conn = get_conn()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        # 规则：时间段内至少有一天被规则覆盖即可（effective_start <= end_d AND (effective_end IS NULL OR effective_end >= start_d)）
        cur.execute("""
            SELECT * FROM t_profit_share_rule WHERE is_active = 1
            AND effective_start <= %s AND (effective_end IS NULL OR effective_end >= %s)
            ORDER BY effective_start DESC LIMIT 1
        """, (end_d, start_d))
        rule = cur.fetchone()
        if not rule:
            conn.close()
            return jsonify({
                "error": "所选时间段暂无生效的分账规则。请到「规则配置」中新增或编辑一条规则：生效开始日期不晚于 %s，生效结束日期不早于 %s（或留空表示长期有效），并启用该规则。" % (end_d, start_d),
                "detail": None,
            }), 400
        def _to_float(x):
            if x is None: return 0.0
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0.0
        rate_merchant = _to_float(rule.get("share_rate_merchant"))
        rate_platform = _to_float(rule.get("share_rate_platform"))
        rule_id = rule["id"]
        rule_name = (rule.get("stage_name") or "").strip() or ("规则#%s" % rule_id)
        cur.execute("SELECT category_large_code, category_large_name, category_mid_code, category_mid_name FROM t_profit_share_exclude_category")
        excludes = cur.fetchall()
        exclusion_parts = []
        for e in excludes:
            lname = e.get("category_large_name") or e.get("category_large_code") or ""
            mname = e.get("category_mid_name") or e.get("category_mid_code")
            if mname:
                exclusion_parts.append("中类「%s」（%s）" % (mname, lname))
            else:
                exclusion_parts.append("大类「%s」" % lname)
        exclusion_summary = "；".join(exclusion_parts) if exclusion_parts else "无"
        exclude_cond = ""
        if excludes:
            parts = []
            for e in excludes:
                lc = e.get("category_large_code") or ""
                mc = e.get("category_mid_code")
                if mc is None or (isinstance(mc, str) and not mc.strip()):
                    parts.append("(COALESCE(p.category_large_code,'') = %s)")
                else:
                    parts.append("(COALESCE(p.category_large_code,'') = %s AND COALESCE(p.category_mid_code,'') = %s)")
            if parts:
                exclude_cond = " AND NOT (" + " OR ".join(parts) + ")"
        params = [_effective_store_id(), start_d, end_d]
        cur.execute("""
            SELECT COALESCE(SUM(total_sale),0) AS sales_all, COALESCE(SUM(total_profit),0) AS profit_all
            FROM t_htma_profit WHERE store_id = %s AND data_date >= %s AND data_date <= %s
        """, (_effective_store_id(), start_d, end_d))
        row_all = cur.fetchone()
        total_sales_all = _to_float(row_all.get("sales_all") if row_all else 0)
        total_profit_all = _to_float(row_all.get("profit_all") if row_all else 0)
        for e in excludes:
            lc = e.get("category_large_code") or ""
            mc = e.get("category_mid_code")
            if mc is None or (isinstance(mc, str) and not mc.strip()):
                params.append(lc)
            else:
                params.append(lc)
                params.append(mc)
        try:
            sel = """
                SELECT COALESCE(p.category_large_code,'') AS category_large_code, COALESCE(p.category_large,'') AS category_large_name,
                       COALESCE(p.category_mid_code,'') AS category_mid_code, COALESCE(p.category_mid,'') AS category_mid_name,
                       SUM(p.total_sale) AS sales, SUM(p.total_profit) AS profit
                FROM t_htma_profit p
                WHERE p.store_id = %s AND p.data_date >= %s AND p.data_date <= %s
            """ + exclude_cond + """
                GROUP BY COALESCE(p.category_large_code,''), COALESCE(p.category_large,''), COALESCE(p.category_mid_code,''), COALESCE(p.category_mid,'')
            """
            cur.execute(sel, params)
        except Exception as col_err:
            if "Unknown column" in str(col_err) and "category_large" in str(col_err):
                sel = """
                    SELECT COALESCE(p.category,'') AS category_large_code, COALESCE(p.category,'') AS category_large_name,
                           '' AS category_mid_code, '' AS category_mid_name,
                           SUM(p.total_sale) AS sales, SUM(p.total_profit) AS profit
                    FROM t_htma_profit p
                    WHERE p.store_id = %s AND p.data_date >= %s AND p.data_date <= %s
                """ + (exclude_cond.replace("p.category_large_code", "p.category").replace("p.category_mid_code", "p.category") if exclude_cond else "") + """
                    GROUP BY COALESCE(p.category,'')
                """
                cur.execute(sel, params)
            else:
                conn.close()
                return jsonify({"error": "查询利润表失败", "detail": str(col_err)}), 500
        rows = cur.fetchall()
        total_sales = _to_float(sum((r.get("sales") or 0) for r in rows))
        total_profit = _to_float(sum((r.get("profit") or 0) for r in rows))
        excluded_sales = total_sales_all - total_sales
        excluded_profit = total_profit_all - total_profit
        total_cost = total_sales - total_profit
        # 分账仅按总毛利计算：加盟商=总毛利×加盟商%，平台=总毛利×平台%（严禁用销售额）
        tp = round(float(total_profit), 2)
        merchant_settle = round(tp * (rate_merchant / 100.0), 2)
        platform_amt = round(tp * (rate_platform / 100.0), 2)
        if merchant_settle + platform_amt > tp:
            platform_amt = round(tp - merchant_settle, 2)
        merchant_settle = min(merchant_settle, tp)
        platform_amt = min(platform_amt, tp)
        created_by = (session.get("user_name") or session.get("open_id") or session.get("user_id") or "")[:50]
        calc_month_col = period_label if len(period_label) <= 7 else period_label[:7]
        try:
            cur.execute("""
                INSERT INTO t_profit_share_result (calc_month, period_start, period_end, total_sales, total_cost, total_profit, share_rate_used, merchant_settle_amount, platform_amount, rule_id, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (calc_month_col, start_d, end_d, total_sales, total_cost, total_profit, rate_merchant, merchant_settle, platform_amt, rule_id, created_by))
        except Exception as ins_err:
            if "Unknown column" in str(ins_err) and "period_start" in str(ins_err):
                cur.execute("""
                    INSERT INTO t_profit_share_result (calc_month, total_sales, total_cost, total_profit, share_rate_used, merchant_settle_amount, platform_amount, rule_id, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (calc_month_col, total_sales, total_cost, total_profit, rate_merchant, merchant_settle, platform_amt, rule_id, created_by))
            else:
                raise
        conn.commit()
        result_id = cur.lastrowid
        details = []
        for r in rows:
            profit_val = float(r.get("profit") or 0)
            details.append({
                "category_large_name": r.get("category_large_name") or "",
                "category_mid_name": r.get("category_mid_name") or "",
                "sales": float(r.get("sales") or 0),
                "profit": profit_val,
                "merchant_share": round(profit_val * (rate_merchant / 100.0), 2),
                "excluded": False,
            })
        formula_note = "总销售额扣除销售成本后为总毛利，加盟商=总毛利×%s%%=%s元，平台=总毛利×%s%%=%s元" % (
            rate_merchant, merchant_settle, rate_platform, platform_amt,
        )
        conn.close()
        # 返回结构与前端 renderCalcResult 一致：total_sales/cost/profit, merchant_settle_amount, platform_amount, share_rate_*
        return jsonify({
            "result_id": result_id,
            "period_label": period_label,
            "period_start": start_d.isoformat(),
            "period_end": end_d.isoformat(),
            "calc_month": calc_month_col,
            "total_sales_all": round(total_sales_all, 2),
            "total_profit_all": round(total_profit_all, 2),
            "excluded_sales": round(excluded_sales, 2),
            "excluded_profit": round(excluded_profit, 2),
            "total_sales": round(total_sales, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": round(total_profit, 2),
            "exclusion_summary": exclusion_summary,
            "share_rate_merchant": rate_merchant,
            "share_rate_platform": rate_platform,
            "share_rate_used": rate_merchant,
            "rule_name": rule_name,
            "rule_id": rule_id,
            "merchant_settle_amount": merchant_settle,
            "platform_amount": platform_amt,
            "formula_note": formula_note,
            "details": details,
        })
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
@profit_share_bp.route("/api/profit_share/results", methods=["GET"])
def api_profit_share_results():
    """分页查询历史计算结果；支持 month 筛选"""
    if _auth_enabled() and not _has_module_access("profit_share"):
        return _profit_share_forbidden()
    try:
        month = (request.args.get("month") or "").strip()[:7]
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(50, max(10, int(request.args.get("page_size", 20))))
        conn = get_conn()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        where = "WHERE calc_month = %s" if month else ""
        params = [month] if month else []
        cur.execute("SELECT COUNT(*) AS total FROM t_profit_share_result " + where, params)
        total = cur.fetchone()["total"]
        cur.execute("""
            SELECT * FROM t_profit_share_result """ + where + """ ORDER BY id DESC LIMIT %s OFFSET %s
        """, params + [page_size, (page - 1) * page_size])
        rows = cur.fetchall()
        for r in rows:
            for k in ("total_sales", "total_cost", "total_profit", "merchant_settle_amount", "platform_amount", "share_rate_used"):
                if r.get(k) is not None and hasattr(r[k], "__float__"):
                    r[k] = float(r[k])
            if r.get("created_at") and hasattr(r["created_at"], "strftime"):
                r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
            if r.get("period_start") and hasattr(r["period_start"], "isoformat"):
                r["period_start"] = r["period_start"].isoformat()
            if r.get("period_end") and hasattr(r["period_end"], "isoformat"):
                r["period_end"] = r["period_end"].isoformat()
            r["period_label"] = r.get("period_start") and r.get("period_end") and (r["period_start"] + " ~ " + r["period_end"]) or r.get("calc_month") or ""
        conn.close()
        return jsonify({"total": total, "page": page, "page_size": page_size, "items": rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def _profit_share_result_period(row):
    """从结果行得到 start_d, end_d 用于明细查询。支持 period_start/period_end 或 calc_month。"""
    if row.get("period_start") and row.get("period_end"):
        s, e = row["period_start"], row["period_end"]
        if hasattr(s, "year"):
            return s, e
        try:
            return date(int(s[:4]), int(s[5:7]), int(s[8:10])), date(int(e[:4]), int(e[5:7]), int(e[8:10]))
        except Exception:
            pass
    calc_month = row.get("calc_month") or ""
    if len(calc_month) >= 7 and calc_month[4] == "-":
        year, mon = int(calc_month[:4]), int(calc_month[5:7])
        start_d = date(year, mon, 1)
        end_d = (start_d + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return start_d, end_d
    return None, None
@profit_share_bp.route("/api/profit_share/result/<int:result_id>", methods=["GET"])
def api_profit_share_result_detail(result_id):
    """某次计算详情；返回完整数据（含剔除因素、分成比例、计算说明）及按品类明细"""
    if _auth_enabled() and not _has_module_access("profit_share"):
        return _profit_share_forbidden()
    try:
        conn = get_conn()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT * FROM t_profit_share_result WHERE id = %s", (result_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "记录不存在"}), 404
        start_d, end_d = _profit_share_result_period(row)
        if start_d is None or end_d is None:
            conn.close()
            return jsonify({"error": "无法解析计算周期", "result": row}), 400
        cur.execute("""
            SELECT COALESCE(SUM(total_sale),0) AS sales_all, COALESCE(SUM(total_profit),0) AS profit_all
            FROM t_htma_profit WHERE store_id = %s AND data_date >= %s AND data_date <= %s
        """, (_effective_store_id(), start_d, end_d))
        row_all = cur.fetchone()
        total_sales_all = float(row_all.get("sales_all") or 0)
        total_profit_all = float(row_all.get("profit_all") or 0)
        ts_included = float(row.get("total_sales") or 0)
        tp_included = float(row.get("total_profit") or 0)
        row["total_sales_all"] = round(total_sales_all, 2)
        row["total_profit_all"] = round(total_profit_all, 2)
        row["excluded_sales"] = round(total_sales_all - ts_included, 2)
        row["excluded_profit"] = round(total_profit_all - tp_included, 2)
        cur.execute("SELECT category_large_code, category_mid_code FROM t_profit_share_exclude_category")
        excludes = cur.fetchall()
        exclude_cond = ""
        params = [_effective_store_id(), start_d, end_d]
        if excludes:
            parts = []
            for e in excludes:
                lc = e.get("category_large_code") or ""
                mc = e.get("category_mid_code")
                if mc is None or (isinstance(mc, str) and not mc.strip()):
                    parts.append("(COALESCE(p.category_large_code,'') = %s)")
                    params.append(lc)
                else:
                    parts.append("(COALESCE(p.category_large_code,'') = %s AND COALESCE(p.category_mid_code,'') = %s)")
                    params.append(lc)
                    params.append(mc)
            if parts:
                exclude_cond = " AND NOT (" + " OR ".join(parts) + ")"
        try:
            cur.execute("""
                SELECT COALESCE(p.category_large,'') AS category_large_name, COALESCE(p.category_mid,'') AS category_mid_name,
                       SUM(p.total_sale) AS sales, SUM(p.total_profit) AS profit
                FROM t_htma_profit p
                WHERE p.store_id = %s AND p.data_date >= %s AND p.data_date <= %s
            """ + exclude_cond + """
                GROUP BY COALESCE(p.category_large,''), COALESCE(p.category_mid,'')
            """, params)
        except Exception:
            cur.execute("""
                SELECT COALESCE(p.category,'') AS category_large_name, '' AS category_mid_name,
                       SUM(p.total_sale) AS sales, SUM(p.total_profit) AS profit
                FROM t_htma_profit p
                WHERE p.store_id = %s AND p.data_date >= %s AND p.data_date <= %s
                GROUP BY COALESCE(p.category,'')
            """, (_effective_store_id(), start_d, end_d))
        details = cur.fetchall()
        rate_m = float(row.get("share_rate_used") or 0)
        for d in details:
            d["sales"] = float(d.get("sales") or 0)
            d["profit"] = float(d.get("profit") or 0)
            d["merchant_share"] = round(d["profit"] * (rate_m / 100.0), 2)
            d["excluded"] = False
        for k in ("total_sales", "total_cost", "total_profit", "merchant_settle_amount", "platform_amount", "share_rate_used"):
            if row.get(k) is not None: row[k] = float(row[k])
        if row.get("created_at") and hasattr(row["created_at"], "strftime"):
            row["created_at"] = row["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("SELECT category_large_name, category_mid_name FROM t_profit_share_exclude_category")
        ex_list = cur.fetchall()
        exclusion_parts = []
        for e in ex_list:
            lname = e.get("category_large_name") or ""
            mname = e.get("category_mid_name") or ""
            if mname:
                exclusion_parts.append("中类「%s」（%s）" % (mname, lname))
            else:
                exclusion_parts.append("大类「%s」" % lname)
        row["exclusion_summary"] = "；".join(exclusion_parts) if exclusion_parts else "无"
        row["period_label"] = (row.get("period_start") and row.get("period_end")) and (str(row["period_start"]) + " ~ " + str(row["period_end"])) or (row.get("calc_month") or "")
        if row.get("period_start") and hasattr(row["period_start"], "isoformat"):
            row["period_start"] = row["period_start"].isoformat()
        if row.get("period_end") and hasattr(row["period_end"], "isoformat"):
            row["period_end"] = row["period_end"].isoformat()
        ts, tc, tp = float(row.get("total_sales") or 0), float(row.get("total_cost") or 0), float(row.get("total_profit") or 0)
        rate_p = 100.0 - rate_m
        row["share_rate_merchant"] = rate_m
        row["share_rate_platform"] = rate_p
        # 展示时一律按总毛利重新计算加盟商/平台金额，避免历史错误数据（如曾按销售额算）导致显示错误
        recalc_merchant = round(min(tp * (rate_m / 100.0), tp), 2)
        recalc_platform = round(min(tp * (rate_p / 100.0), tp), 2)
        row["merchant_settle_amount"] = recalc_merchant
        row["platform_amount"] = recalc_platform
        row["formula_note"] = "总销售额扣除销售成本后为总毛利，加盟商=总毛利×%s%%=%s元，平台=总毛利×%s%%=%s元" % (
            rate_m, recalc_merchant, rate_p, recalc_platform,
        )
        conn.close()
        return jsonify({"result": row, "details": details})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@profit_share_bp.route("/api/profit_share/category_options", methods=["GET"])
def api_profit_share_category_options():
    """获取大类/中类列表，供排除配置下拉使用（来自 t_htma_profit 或 t_htma_sale）"""
    if _auth_enabled() and not _has_module_access("profit_share"):
        return _profit_share_forbidden()
    try:
        conn = get_conn()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        try:
            cur.execute("""
                SELECT DISTINCT COALESCE(category_large_code,'') AS code, COALESCE(category_large,'') AS name
                FROM t_htma_profit WHERE store_id = %s AND COALESCE(category_large_code,'') != ''
                ORDER BY name
            """, (_effective_store_id(),))
            large = cur.fetchall()
            cur.execute("""
                SELECT COALESCE(category_large_code,'') AS large_code, COALESCE(category_mid_code,'') AS code, COALESCE(category_mid,'') AS name
                FROM t_htma_profit WHERE store_id = %s AND COALESCE(category_large_code,'') != ''
                GROUP BY category_large_code, category_mid_code, category_mid ORDER BY large_code, name
            """, (_effective_store_id(),))
            mid_rows = cur.fetchall()
        except Exception:
            cur.execute("SELECT DISTINCT COALESCE(category,'') AS code FROM t_htma_sale WHERE store_id = %s AND COALESCE(category,'') != '' ORDER BY code", (_effective_store_id(),))
            large = [{"code": r["code"], "name": r["code"]} for r in cur.fetchall()]
            mid_rows = []
        mid_by_large = {}
        for r in mid_rows:
            lc = r.get("large_code") or ""
            if lc not in mid_by_large:
                mid_by_large[lc] = []
            if r.get("code"):
                mid_by_large[lc].append({"code": r.get("code") or "", "name": r.get("name") or r.get("code") or ""})
        conn.close()
        return jsonify({"large": large, "midByLarge": mid_by_large})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@profit_share_bp.route("/api/profit_share/preview", methods=["GET"])
def api_profit_share_preview():
    """按月份+品类预览销售汇总（用于配置排除前查看影响）"""
    if _auth_enabled() and not _has_module_access("profit_share"):
        return _profit_share_forbidden()
    month = (request.args.get("month") or "").strip()[:7]
    large_code = (request.args.get("category_large_code") or "").strip()
    mid_code = (request.args.get("category_mid_code") or "").strip()
    if not month or len(month) != 7:
        return jsonify({"error": "请提供 month (YYYY-MM)"}), 400
    if not large_code:
        return jsonify({"error": "请提供 category_large_code"}), 400
    try:
        year, mon = month[:4], month[5:7]
        start_d = date(int(year), int(mon), 1)
        end_d = (start_d + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        conn = get_conn()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        if mid_code:
            cur.execute("""
                SELECT COALESCE(SUM(total_sale),0) AS sales, COALESCE(SUM(total_profit),0) AS profit
                FROM t_htma_profit WHERE store_id = %s AND data_date >= %s AND data_date <= %s
                AND COALESCE(category_large_code,'') = %s AND COALESCE(category_mid_code,'') = %s
            """, (_effective_store_id(), start_d, end_d, large_code, mid_code))
        else:
            cur.execute("""
                SELECT COALESCE(SUM(total_sale),0) AS sales, COALESCE(SUM(total_profit),0) AS profit
                FROM t_htma_profit WHERE store_id = %s AND data_date >= %s AND data_date <= %s
                AND COALESCE(category_large_code,'') = %s
            """, (_effective_store_id(), start_d, end_d, large_code))
        row = cur.fetchone()
        conn.close()
        return jsonify({
            "category_large_code": large_code,
            "category_mid_code": mid_code or None,
            "sales": float(row.get("sales") or 0),
            "profit": float(row.get("profit") or 0),
        })
    except Exception as col_err:
        if "Unknown column" in str(col_err):
            try:
                conn = get_conn()
                cur = conn.cursor(pymysql.cursors.DictCursor)
                cur.execute("""
                    SELECT COALESCE(SUM(total_sale),0) AS sales, COALESCE(SUM(total_profit),0) AS profit
                    FROM t_htma_profit WHERE store_id = %s AND data_date >= %s AND data_date <= %s
                    AND COALESCE(category,'') = %s
                """, (_effective_store_id(), start_d, end_d, large_code))
                row = cur.fetchone()
                conn.close()
                return jsonify({"category_large_code": large_code, "category_mid_code": mid_code or None, "sales": float(row.get("sales") or 0), "profit": float(row.get("profit") or 0)})
            except Exception:
                pass
        return jsonify({"error": str(col_err)}), 500




