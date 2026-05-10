# -*- coding: utf-8 -*-
"""serve_web/tax：税率分析与税务发票 API"""

from flask import Blueprint, Response, jsonify, request, send_file
from datetime import date, datetime, timedelta
import io, csv, os, pymysql, pymysql.cursors

from core.db import get_conn
from core.context import _effective_store_id
from core.utils import safe_float, safe_str
from query_layer import query_filters_from_request as _ql_query_filters

tax_bp = Blueprint("tax", __name__)


def _query_filters():
    """兼容 app.py 的 _query_filters 包装。"""
    date_cond, date_params, params, category_cond, _ = _ql_query_filters()
    if params and params[0] is None:
        sid = _effective_store_id()
        params = (sid,) + tuple(params[1:])
    return date_cond, date_params, params, category_cond, _

def _get_tax_burden_data():
    """税率计算数据：按税率汇总 销售额、不含税、税额。返回 dict 或抛出异常。"""
    date_cond, _, params, category_cond, _ = _query_filters()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT 1 FROM t_htma_tax_burden LIMIT 1")
            except Exception:
                return {
                    "total_sale_amount": 0, "total_tax_amount": 0, "tax_rate_pct": 0,
                    "by_tax_rate": [], "date_range": "",
                    "message": "请先导入税率负担表并执行 scripts/12_create_tax_burden_table.sql",
                }
            # 按税率汇总：每行取匹配到的税率，计算税额；再在 Python 里按税率分组得 销售额、不含税、税额
            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(TRIM(s.category_large), ''), NULLIF(TRIM(s.category_mid), ''), NULLIF(TRIM(s.category_small), ''), NULLIF(TRIM(s.category), ''), '未分类') AS category_display,
                    SUM(s.sale_amount) AS sale_amount,
                    COALESCE(
                        (SELECT tb.tax_rate FROM t_htma_category c JOIN t_htma_tax_burden tb ON tb.code = c.category_small_code WHERE TRIM(COALESCE(c.category_small,'')) != '' AND c.category_small = COALESCE(s.category_small, s.category) LIMIT 1),
                        (SELECT tb.tax_rate FROM t_htma_category c JOIN t_htma_tax_burden tb ON tb.code = c.category_mid_code WHERE TRIM(COALESCE(c.category_mid,'')) != '' AND c.category_mid = COALESCE(s.category_mid, s.category) LIMIT 1),
                        (SELECT tb.tax_rate FROM t_htma_category c JOIN t_htma_tax_burden tb ON tb.code = c.category_large_code WHERE TRIM(COALESCE(c.category_large,'')) != '' AND c.category_large = COALESCE(s.category_large, s.category) LIMIT 1),
                        0
                    ) AS tax_rate
                FROM t_htma_sale s
                WHERE s.store_id = %s AND {date_cond}{category_cond}
                GROUP BY category_display, tax_rate
                ORDER BY sale_amount DESC
            """, params)
            rows = cur.fetchall()
        # 按税率分组汇总，并保留各税率下的品类明细（销售额、不含税、税额）
        rate_map = {}
        for r in rows:
            sale_amt = float(r["sale_amount"] or 0)
            rate = float(r["tax_rate"] or 0)
            key = round(rate, 4)
            if key not in rate_map:
                rate_map[key] = {"sale_amount": 0, "tax_amount": 0, "categories": []}
            # 税额 = 销售额 - 销售额/(1+税率)
            if rate >= 0 and rate < 1:
                excl = sale_amt / (1 + rate)
                tax_row = round(sale_amt - excl, 2)
            else:
                tax_row = round(sale_amt * rate, 2)
            rate_map[key]["sale_amount"] += sale_amt
            rate_map[key]["tax_amount"] += tax_row
            rate_map[key]["categories"].append({
                "category": (r["category_display"] or "未分类").strip(),
                "sale_amount": round(sale_amt, 2),
                "amount_excluding_tax": round(sale_amt - tax_row, 2),
                "tax_amount": tax_row,
            })
        by_tax_rate = []
        total_sale = 0.0
        total_tax = 0.0
        for rate in sorted(rate_map.keys(), reverse=True):
            sale_amt = round(rate_map[rate]["sale_amount"], 2)
            tax_amt = round(rate_map[rate]["tax_amount"], 2)
            excl_amt = round(sale_amt - tax_amt, 2)
            total_sale += sale_amt
            total_tax += tax_amt
            # 品类明细按税额从高到低排序
            cats = sorted(rate_map[rate]["categories"], key=lambda x: -(x["tax_amount"] or 0))
            by_tax_rate.append({
                "tax_rate": rate,
                "tax_rate_pct": round(rate * 100, 2),
                "sale_amount": sale_amt,
                "amount_excluding_tax": excl_amt,
                "tax_amount": tax_amt,
                "by_category": cats,
            })
        tax_rate_pct = round((total_tax / total_sale * 100), 2) if total_sale else 0
        start_d = request.args.get("start_date", "").strip()
        end_d = request.args.get("end_date", "").strip()
        period = request.args.get("period", "recent30")
        date_range = f"{start_d} ~ {end_d}" if (start_d and end_d) else {"day": "今日", "week": "本周", "month": "本月", "recent30": "近30天"}.get(period, "近30天")
        return {
            "total_sale_amount": round(total_sale, 2),
            "total_tax_amount": round(total_tax, 2),
            "tax_rate_pct": tax_rate_pct,
            "by_tax_rate": by_tax_rate,
            "date_range": date_range,
        }
    except Exception as e:
        raise
    finally:
        conn.close()
@tax_bp.route("/api/tax_burden_summary", methods=["GET", "HEAD", "OPTIONS"])
def api_tax_burden_summary():
    """税率计算：按税率汇总 销售额、不含税、税额。GET 返回 JSON；OPTIONS 返回 204 避免 405。"""
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "HEAD":
        return "", 200
    try:
        data = _get_tax_burden_data()
        return jsonify(data)
    except Exception as e:
        return jsonify({"total_sale_amount": 0, "total_tax_amount": 0, "tax_rate_pct": 0, "by_tax_rate": [], "date_range": "", "error": str(e)}), 500
@tax_bp.route("/api/tax_burden_export", methods=["GET"])
def api_tax_burden_export():
    """导出税率汇总：format=csv 返回 Excel 可打开的 CSV；format=pdf 返回 HTML 供打印为 PDF。"""
    fmt = request.args.get("format", "csv").strip().lower()
    try:
        data = _get_tax_burden_data()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    if data.get("message") and not data.get("by_tax_rate"):
        return jsonify({"success": False, "message": data.get("message")}), 400
    by_tax_rate = data.get("by_tax_rate") or []
    date_range = data.get("date_range", "")
    total_sale = data.get("total_sale_amount", 0)
    total_tax = data.get("total_tax_amount", 0)
    total_excl = round(total_sale - total_tax, 2)

    if fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        buf.write("\ufeff")
        w = csv.writer(buf)
        w.writerow(["税率", "销售额", "不含税", "税额"])
        for row in by_tax_rate:
            w.writerow([
                str(row.get("tax_rate_pct", 0)) + "%",
                row.get("sale_amount", 0),
                row.get("amount_excluding_tax", 0),
                row.get("tax_amount", 0),
            ])
        w.writerow(["合计", total_sale, total_excl, total_tax])
        fname = f"税率负担汇总_{date_range.replace(' ', '').replace('~', '-')}.csv"
        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"},
        )
    if fmt == "pdf" or fmt == "html":
        def _num(x):
            if x is None:
                return "0.00"
            try:
                return "{:,.2f}".format(float(x))
            except (TypeError, ValueError):
                return "0.00"
        rows_html = "".join(
            "<tr><td>{}%</td><td class='num'>{}</td><td class='num'>{}</td><td class='num'>{}</td></tr>".format(
                row.get("tax_rate_pct", 0), _num(row.get("sale_amount")), _num(row.get("amount_excluding_tax")), _num(row.get("tax_amount"))
            )
            for row in by_tax_rate
        )
        safe_date_range = str(date_range).replace("<", "&lt;").replace(">", "&gt;") if date_range else ""
        export_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        html = (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>税率负担汇总</title>"
            "<style>body{font-family:system-ui,sans-serif;margin:24px;} table{border-collapse:collapse;width:100%;} th,td{border:1px solid #333;padding:8px;text-align:left;} th{background:#eee;} .num{text-align:right;} @media print{body{margin:12px;}}</style></head><body>"
            "<h2>税率负担汇总（" + safe_date_range + "）</h2>"
            "<table><thead><tr><th>税率</th><th class=\"num\">销售额</th><th class=\"num\">不含税</th><th class=\"num\">税额</th></tr></thead><tbody>"
            + rows_html +
            "<tr><th>合计</th><td class=\"num\">" + _num(total_sale) + "</td><td class=\"num\">" + _num(total_excl) + "</td><td class=\"num\">" + _num(total_tax) + "</td></tr>"
            "</tbody></table><p style=\"margin-top:16px;color:#666;\">导出时间：" + export_time + " · 使用浏览器「打印」→「另存为 PDF」保存为 PDF。</p></body></html>"
        )
        if fmt == "pdf":
            return Response(html, mimetype="text/html; charset=utf-8", headers={"Content-Disposition": "inline; filename=tax_summary.html"})
        return Response(html, mimetype="text/html; charset=utf-8")
@tax_bp.route("/api/tax_analysis/import_invoice", methods=["POST", "OPTIONS"])
def api_tax_analysis_import_invoice():
    """上传当月发票 Excel，解析后写入 t_htma_invoice_detail。表单: period_month=YYYY-MM, file=Excel"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("tax_analysis"):
        return _tax_analysis_forbidden()
    period = (request.form.get("period_month") or "").strip()
    if not period or len(period) < 6:
        return jsonify({"success": False, "message": "请选择账期月份（YYYY-MM）"}), 400
    try:
        y, m = int(period[:4]), int(period[5:7])
        period_date = date(y, m, 1)
    except Exception:
        return jsonify({"success": False, "message": "账期月份格式错误，应为 YYYY-MM"}), 400
    if "file" not in request.files or not request.files["file"].filename:
        return jsonify({"success": False, "message": "请选择发票 Excel 文件"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith((".xls", ".xlsx")):
        return jsonify({"success": False, "message": "仅支持 .xls / .xlsx 文件"}), 400
    store_id = (request.form.get("store_id") or "沈阳超级仓").strip()
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.filename)[1]) as tmp:
            f.save(tmp.name)
            try:
                rows = _parse_invoice_excel(tmp.name, store_id)
            except Exception as e:
                return jsonify({"success": False, "message": "解析 Excel 失败: " + str(e)}), 400
            finally:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass
    except Exception as e:
        return jsonify({"success": False, "message": "保存文件失败: " + str(e)}), 500
    if not rows:
        return jsonify({"success": False, "message": "未解析到有效发票明细行，请检查表头是否含「三级类别名称」「开票金额」"}), 400
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='t_htma_invoice_detail' LIMIT 1"
        )
        if not cur.fetchone():
            return jsonify({"success": False, "message": "表 t_htma_invoice_detail 不存在，请先执行 scripts/24_create_invoice_tables.sql"}), 500
        inserted = 0
        for r in rows:
            cur.execute(
                """INSERT INTO t_htma_invoice_detail
                   (period_month, category_small_code, category_small_name, tax_class_code, tax_rate, sale_qty, invoice_amount, store_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                   tax_class_code = VALUES(tax_class_code), tax_rate = VALUES(tax_rate), sale_qty = VALUES(sale_qty), invoice_amount = VALUES(invoice_amount), updated_at = CURRENT_TIMESTAMP""",
                (
                    period_date,
                    r.get("category_small_code"),
                    r["category_small_name"],
                    r.get("tax_class_code"),
                    r.get("tax_rate", 0.13),
                    r.get("sale_qty", 0),
                    r.get("invoice_amount", 0),
                    store_id,
                ),
            )
            inserted += 1
        conn.commit()
        return jsonify({"success": True, "message": "导入成功", "rows": inserted})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass
@tax_bp.route("/api/tax_analysis/invoice_months", methods=["GET"])
def api_tax_analysis_invoice_months():
    """已导入发票的账期列表，用于下拉选择。异常时返回 200 + 空列表，避免 500 导致前端报错。"""
    if _auth_enabled() and not _has_module_access("tax_analysis"):
        return _tax_analysis_forbidden()
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute(
            "SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='t_htma_invoice_detail' LIMIT 1"
        )
        if not cur.fetchone():
            return jsonify({"success": True, "months": []})
        cur.execute(
            "SELECT DISTINCT DATE_FORMAT(period_month, '%Y-%m') AS period FROM t_htma_invoice_detail ORDER BY period DESC LIMIT 24"
        )
        rows = cur.fetchall()
        months = []
        for row in rows:
            p = row.get("period") if isinstance(row, dict) else (row[0] if row else None)
            if p:
                months.append(p.strftime("%Y-%m") if hasattr(p, "strftime") else str(p))
        return jsonify({"success": True, "months": months})
    except Exception as e:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        return jsonify({"success": True, "months": [], "message": str(e)})
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
@tax_bp.route("/api/tax_analysis/invoice_detail", methods=["GET"])
def api_tax_analysis_invoice_detail():
    """已导入的发票明细列表（按 PDF 样式：项目名称、数量、金额、税率、税额）。period_month=YYYY-MM"""
    if _auth_enabled() and not _has_module_access("tax_analysis"):
        return _tax_analysis_forbidden()
    period = (request.args.get("period_month") or "").strip()
    if not period or len(period) < 6:
        return jsonify({"success": False, "message": "请传入 period_month=YYYY-MM"}), 400
    try:
        y, m = int(period[:4]), int(period[5:7])
        start_d = date(y, m, 1)
    except Exception:
        return jsonify({"success": False, "message": "period_month 格式错误"}), 400
    store_id = (request.args.get("store_id") or "沈阳超级仓").strip()
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute(
            "SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='t_htma_invoice_detail' LIMIT 1"
        )
        if not cur.fetchone():
            return jsonify({"success": True, "period_month": period, "rows": [], "summary": {}})
        cur.execute(
            """SELECT category_small_code, category_small_name, tax_class_code, tax_rate, sale_qty, invoice_amount
               FROM t_htma_invoice_detail WHERE store_id = %s AND period_month = %s ORDER BY category_small_name""",
            (store_id, start_d),
        )
        rows = []
        total_qty = 0
        total_amount = 0
        total_tax = 0
        for row in cur.fetchall():
            amt = float(row.get("invoice_amount") or 0)
            rate = float(row.get("tax_rate") or 0.13)
            qty = float(row.get("sale_qty") or 0)
            tax_amt = round(amt * rate / (1 + rate), 2) if rate > 0 else 0
            total_qty += qty
            total_amount += amt
            total_tax += tax_amt
            rows.append({
                "category_small_name": row.get("category_small_name") or "",
                "category_small_code": row.get("category_small_code"),
                "sale_qty": qty,
                "invoice_amount": amt,
                "tax_rate": rate,
                "tax_amount": tax_amt,
                "unit_price": round(amt / qty, 4) if qty > 0 else None,
            })
        return jsonify({
            "success": True,
            "period_month": period,
            "rows": rows,
            "summary": {
                "total_sale_qty": round(total_qty, 2),
                "total_invoice_amount": round(total_amount, 2),
                "total_tax_amount": round(total_tax, 2),
            },
        })
    except Exception as e:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        return jsonify({"success": False, "message": str(e), "rows": [], "summary": {}}), 500
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
@tax_bp.route("/api/tax_analysis/compare", methods=["GET"])
def api_tax_analysis_compare():
    """比对结果：系统销售额 vs 开票金额，按品类。period_month=YYYY-MM；可选 baseline_pct（合理开票率基准，默认80）、tolerance_pct（上下浮动%，默认5），开票占比在 [基准-浮动, 基准+浮动] 内视为合理（一致）。"""
    if _auth_enabled() and not _has_module_access("tax_analysis"):
        return _tax_analysis_forbidden()
    period = (request.args.get("period_month") or "").strip()
    if not period or len(period) < 6:
        return jsonify({"success": False, "message": "请传入 period_month=YYYY-MM"}), 400
    try:
        baseline_pct = float(request.args.get("baseline_pct") or "80")
        tolerance_pct = float(request.args.get("tolerance_pct") or "5")
    except (TypeError, ValueError):
        baseline_pct, tolerance_pct = 80.0, 5.0
    low_pct = baseline_pct - tolerance_pct
    high_pct = baseline_pct + tolerance_pct
    try:
        y, m = int(period[:4]), int(period[5:7])
        start_d = date(y, m, 1)
        if m == 12:
            end_d = date(y, 12, 31)
        else:
            end_d = date(y, m + 1, 1) - timedelta(days=1)
    except Exception:
        return jsonify({"success": False, "message": "period_month 格式错误"}), 400
    store_id = (request.args.get("store_id") or "沈阳超级仓").strip()
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute(
            "SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='t_htma_invoice_detail' LIMIT 1"
        )
        if not cur.fetchone():
            return jsonify({"success": True, "summary": {}, "detail": []})
        # 系统按品类汇总（优先 category_small，无则用 category）
        cur.execute(
            """SELECT COALESCE(NULLIF(TRIM(category_small), ''), category, '未分类') AS category_name,
                      SUM(sale_amount) AS system_sale_amount, SUM(sale_qty) AS system_sale_qty
               FROM t_htma_sale WHERE store_id = %s AND data_date >= %s AND data_date <= %s
               GROUP BY COALESCE(NULLIF(TRIM(category_small), ''), category, '未分类')""",
            (store_id, start_d, end_d),
        )
        system_by_cat = {row["category_name"]: row for row in cur.fetchall()}
        cur.execute(
            """SELECT category_small_code, category_small_name, tax_rate, sale_qty AS invoice_sale_qty, invoice_amount
               FROM t_htma_invoice_detail WHERE store_id = %s AND period_month = %s""",
            (store_id, start_d),
        )
        invoice_by_cat = {row["category_small_name"]: row for row in cur.fetchall()}
        all_cats = set(system_by_cat.keys()) | set(invoice_by_cat.keys())
        detail = []
        total_system = 0
        total_invoice = 0
        for cat in sorted(all_cats):
            sys_row = system_by_cat.get(cat, {})
            inv_row = invoice_by_cat.get(cat, {})
            sys_amt = float(sys_row.get("system_sale_amount") or 0)
            sys_qty = float(sys_row.get("system_sale_qty") or 0)
            inv_amt = float(inv_row.get("invoice_amount") or 0)
            inv_qty = float(inv_row.get("invoice_sale_qty") or 0)
            total_system += sys_amt
            total_invoice += inv_amt
            diff = round(sys_amt - inv_amt, 2)
            pct = round(100 * inv_amt / sys_amt, 2) if sys_amt > 0 else (100 if inv_amt > 0 else None)
            if sys_amt > 0 and inv_amt == 0:
                flag = "漏开"
            elif sys_amt > 0 and inv_amt > 0:
                if low_pct <= pct <= high_pct:
                    flag = "一致"
                elif sys_amt > inv_amt:
                    flag = "少开"
                elif abs(diff) / sys_amt > 0.001:
                    flag = "不一致"
                else:
                    flag = "一致"
            elif sys_amt > 0 and abs(diff) / sys_amt > 0.001:
                flag = "不一致"
            else:
                flag = "一致"
            detail.append({
                "category_small_name": cat,
                "category_small_code": inv_row.get("category_small_code"),
                "system_sale_amount": sys_amt,
                "system_sale_qty": sys_qty,
                "invoice_amount": inv_amt,
                "invoice_sale_qty": inv_qty,
                "amount_diff": diff,
                "invoice_pct": pct,
                "flag": flag,
            })
        summary = {
            "total_system_sale_amount": round(total_system, 2),
            "total_invoice_amount": round(total_invoice, 2),
            "total_amount_diff": round(total_system - total_invoice, 2),
            "invoice_pct": round(100 * total_invoice / total_system, 2) if total_system > 0 else None,
            "baseline_pct": baseline_pct,
            "tolerance_pct": tolerance_pct,
        }
        return jsonify({"success": True, "summary": summary, "detail": detail})
    except Exception as e:
        import traceback
        return jsonify({"success": False, "message": str(e), "traceback": traceback.format_exc()[-1500:]}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass
@tax_bp.route("/api/tax_analysis/tax_summary", methods=["GET"])
def api_tax_analysis_tax_summary():
    """实际税负测算：应有税负、已开票税负、税负缺口、已覆盖比例。period_month=YYYY-MM"""
    if _auth_enabled() and not _has_module_access("tax_analysis"):
        return _tax_analysis_forbidden()
    period = (request.args.get("period_month") or "").strip()
    if not period or len(period) < 6:
        return jsonify({"success": False, "message": "请传入 period_month=YYYY-MM"}), 400
    try:
        y, m = int(period[:4]), int(period[5:7])
        start_d = date(y, m, 1)
        if m == 12:
            end_d = date(y, 12, 31)
        else:
            end_d = date(y, m + 1, 1) - timedelta(days=1)
    except Exception:
        return jsonify({"success": False, "message": "period_month 格式错误"}), 400
    store_id = (request.args.get("store_id") or "沈阳超级仓").strip()
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        # 系统销售额按品类（与 compare 一致）
        cur.execute(
            """SELECT COALESCE(NULLIF(TRIM(category_small), ''), category, '未分类') AS category_name, SUM(sale_amount) AS system_sale_amount
               FROM t_htma_sale WHERE store_id = %s AND data_date >= %s AND data_date <= %s
               GROUP BY COALESCE(NULLIF(TRIM(category_small), ''), category, '未分类')""",
            (store_id, start_d, end_d),
        )
        system_by_cat = {row["category_name"]: row for row in cur.fetchall()}
        cur.execute(
            """SELECT category_small_name, tax_rate, invoice_amount FROM t_htma_invoice_detail WHERE store_id = %s AND period_month = %s""",
            (store_id, start_d),
        )
        invoice_rows = cur.fetchall()
        # 应有税负：按系统销售额 × 税率/(1+税率)。税率优先用发票明细，无则用 t_htma_tax_burden
        cur.execute("SELECT code, name, tax_rate FROM t_htma_tax_burden")
        tax_burden = {}
        for row in cur.fetchall():
            tax_burden[row["name"]] = float(row["tax_rate"] or 0)
        system_tax_total = 0
        for cat, row in system_by_cat.items():
            amt = float(row.get("system_sale_amount") or 0)
            rate = tax_burden.get(cat)
            if rate is None:
                rate = 0.13
            system_tax_total += amt * rate / (1 + rate)
        invoice_tax_total = 0
        for row in invoice_rows:
            amt = float(row.get("invoice_amount") or 0)
            rate = float(row.get("tax_rate") or 0.13)
            invoice_tax_total += amt * rate / (1 + rate)
        tax_gap = round(system_tax_total - invoice_tax_total, 2)
        coverage = round(100 * invoice_tax_total / system_tax_total, 2) if system_tax_total > 0 else None
        return jsonify({
            "success": True,
            "summary": {
                "system_tax_amount": round(system_tax_total, 2),
                "invoice_tax_amount": round(invoice_tax_total, 2),
                "tax_gap": tax_gap,
                "tax_coverage_pct": coverage,
            },
        })
    except Exception as e:
        import traceback
        return jsonify({"success": False, "message": str(e), "traceback": traceback.format_exc()[-1500:]}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass
@tax_bp.route("/api/tax_analysis/invoicing_ledger_export", methods=["GET"])
def api_tax_analysis_invoicing_ledger_export():
    """开票台账空白模板：三表（未开票收入计算、每日开票台账、每日收入汇总）。format=xlsx|pdf；可选 store_name 覆盖默认卖场名。"""
    if _auth_enabled() and not _has_module_access("tax_analysis"):
        return _tax_analysis_forbidden()
    fmt = (request.args.get("format") or "xlsx").strip().lower()
    store = (request.args.get("store_name") or os.environ.get("HTMA_INVOICING_LEDGER_STORE_NAME") or "").strip()
    from invoicing_ledger_export import build_invoicing_ledger_pdf, build_invoicing_ledger_xlsx

    if fmt == "pdf":
        data = build_invoicing_ledger_pdf(store or None)
        return Response(
            data,
            mimetype="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="invoicing_ledger_template.pdf"'},
        )
    data = build_invoicing_ledger_xlsx(store or None)
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="invoicing_ledger_template.xlsx"'},
    )
def _tax_full_invoice_tables_ready(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='t_htma_full_invoice_line_raw' LIMIT 1"
        )
        return cur.fetchone() is not None
@tax_bp.route("/api/tax_analysis/import_full_invoice", methods=["POST", "OPTIONS"])
def api_tax_analysis_import_full_invoice():
    """上传税务平台「全量发票查询导出」xlsx：须含「信息汇总表」「发票基础信息」。表单: period_month=YYYY-MM, file=Excel, store_id 可选。"""
    if request.method == "OPTIONS":
        return "", 204
    if _auth_enabled() and not _has_module_access("tax_analysis"):
        return _tax_analysis_forbidden()
    period = (request.form.get("period_month") or "").strip()
    store_id = (request.form.get("store_id") or "沈阳超级仓").strip()
    f = request.files.get("file")
    if not period or not f or not getattr(f, "filename", None):
        return jsonify({"success": False, "message": "请填写账期月份并选择 Excel 文件"}), 400
    if not str(f.filename).lower().endswith((".xlsx", ".xls")):
        return jsonify({"success": False, "message": "仅支持 .xlsx / .xls"}), 400
    conn = get_conn()
    if not _tax_full_invoice_tables_ready(conn):
        conn.close()
        return jsonify(
            {
                "success": False,
                "message": "数据库未创建全量发票表，请执行 scripts/26_full_invoice_raw_tables.sql 或重启看板",
            }
        ), 500
    suffix = os.path.splitext(f.filename)[1] or ".xlsx"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            f.save(tmp_path)
        from full_invoice_import import import_full_invoice_excel

        ok, msg, data = import_full_invoice_excel(tmp_path, period, store_id, conn, original_filename=f.filename)
        if not ok:
            return jsonify({"success": False, "message": msg}), 400
        return jsonify({"success": True, "message": msg, **data})
    except Exception as e:
        import traceback

        return jsonify({"success": False, "message": str(e), "traceback": traceback.format_exc()[-1200:]}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
@tax_bp.route("/api/tax_analysis/full_invoice_months", methods=["GET"])
def api_tax_analysis_full_invoice_months():
    """已导入全量发票的账期月份列表。"""
    if _auth_enabled() and not _has_module_access("tax_analysis"):
        return _tax_analysis_forbidden()
    conn = get_conn()
    try:
        if not _tax_full_invoice_tables_ready(conn):
            return jsonify({"success": True, "months": []})
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT DISTINCT DATE_FORMAT(period_month, '%Y-%m') AS m FROM t_htma_full_invoice_import_batch ORDER BY m DESC LIMIT 36"
            )
            months = [r["m"] for r in cur.fetchall() if r.get("m")]
        return jsonify({"success": True, "months": months})
    finally:
        try:
            conn.close()
        except Exception:
            pass
@tax_bp.route("/api/tax_analysis/uninvoiced_goods_analysis", methods=["GET"])
def api_tax_analysis_uninvoiced_goods_analysis():
    """当月系统销售 vs 全量发票明细（不含税）按归一化品名比对；依赖已导入全量发票与 t_htma_sale.product_name。"""
    if _auth_enabled() and not _has_module_access("tax_analysis"):
        return _tax_analysis_forbidden()
    period = (request.args.get("period_month") or "").strip()
    store_id = (request.args.get("store_id") or "沈阳超级仓").strip()
    if not period:
        return jsonify({"success": False, "message": "请传 period_month=YYYY-MM"}), 400
    conn = get_conn()
    try:
        if not _tax_full_invoice_tables_ready(conn):
            return jsonify({"success": False, "message": "请先导入全量发票或创建表结构"}), 400
        from full_invoice_import import compute_uninvoiced_goods_analysis

        out = compute_uninvoiced_goods_analysis(conn, period, store_id)
        return jsonify(out)
    finally:
        try:
            conn.close()
        except Exception:
            pass


# 本接口仅处理销售/库存/品类/毛利/税率，不读写人力、商品档案表；各模块数据隔离。
