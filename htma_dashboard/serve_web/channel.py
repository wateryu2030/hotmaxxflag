# -*- coding: utf-8 -*-
"""serve_web/channel：渠道分析（红牌楼）API"""

from flask import Blueprint, jsonify, request, send_file
from datetime import date, datetime, timedelta
import io, csv, json, pymysql, pymysql.cursors

from core.db import get_conn
from core.context import _effective_store_id
from core.utils import safe_str, safe_float

channel_bp = Blueprint("channel", __name__)

@channel_bp.route("/api/channel/hongbeilou/logic", methods=["GET", "HEAD", "OPTIONS"])
def api_channel_hongbeilou_logic():
    """返回当前选品规则说明与环境探测（与预览/导出 SQL 一致），供前端展示。"""
    if request.method == "OPTIONS":
        return "", 204
    err = _hongbeilou_auth_error()
    if err:
        return err
    large = request.args.get("category_large_code", "").strip()
    mid = request.args.get("category_mid_code", "").strip()
    small = request.args.get("category_small_code", "").strip()
    try:
        share_ratio = float(request.args.get("share_ratio", "0.3") or 0.3)
    except ValueError:
        share_ratio = 0.3
    try:
        min_stock = float(request.args.get("min_stock", "0.01") or 0.01)
    except ValueError:
        min_stock = 0.01
    exclude_expired = request.args.get("exclude_expired", "1").strip() not in ("0", "false", "no")
    conn = get_conn()
    try:
        meta = build_selection_logic_meta(
            conn,
            _effective_store_id(),
            category_large_code=large,
            category_mid_code=mid,
            category_small_code=small,
            min_stock=min_stock,
            share_ratio=share_ratio,
            exclude_expired=exclude_expired,
        )
        return jsonify({"ok": True, "logic": meta})
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()}), 500
    finally:
        conn.close()


@channel_bp.route("/api/channel/hongbeilou/preview", methods=["GET", "HEAD", "OPTIONS"])
def api_channel_hongbeilou_preview():
    """红背篓选品预览：按大类/中类/小类筛选最新库存 SKU，含效期与共享额度建议。"""
    if request.method == "OPTIONS":
        return "", 204
    err = _hongbeilou_auth_error()
    if err:
        return err
    large = request.args.get("category_large_code", "").strip()
    mid = request.args.get("category_mid_code", "").strip()
    small = request.args.get("category_small_code", "").strip()
    try:
        share_ratio = float(request.args.get("share_ratio", "0.3") or 0.3)
    except ValueError:
        share_ratio = 0.3
    try:
        min_stock = float(request.args.get("min_stock", "0.01") or 0.01)
    except ValueError:
        min_stock = 0.01
    exclude_expired = request.args.get("exclude_expired", "1").strip() not in ("0", "false", "no")
    markup_raw = request.args.get("markup", "").strip()
    conn = get_conn()
    try:
        hb_sid = _effective_store_id()
        logic = build_selection_logic_meta(
            conn,
            hb_sid,
            category_large_code=large,
            category_mid_code=mid,
            category_small_code=small,
            min_stock=min_stock,
            share_ratio=share_ratio,
            exclude_expired=exclude_expired,
        )
        rows = query_catalog_rows(
            conn,
            hb_sid,
            category_large_code=large,
            category_mid_code=mid,
            category_small_code=small,
            min_stock=min_stock,
            share_ratio=share_ratio,
            exclude_expired=exclude_expired,
        )
        try:
            simple_rows, markup_eff = rows_to_simple_export(rows, markup_raw)
        except ValueError as ve:
            return jsonify({"ok": False, "error": str(ve)}), 400
        out = []
        for row in simple_rows:
            out.append({k: _hongbeilou_json_val(row.get(k)) for k in row})
        logic["result_count"] = len(out)
        logic["markup_ratio_effective"] = markup_eff
        return jsonify({"ok": True, "count": len(out), "rows": out, "logic": logic})
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()}), 500
    finally:
        conn.close()


@channel_bp.route("/api/channel/hongbeilou/export", methods=["GET", "HEAD", "POST", "OPTIONS"])
def api_channel_hongbeilou_export():
    """红背篓选品导出 CSV（UTF-8 BOM，Excel 可开）。POST JSON 可带 sku_codes 仅导出所选。"""
    if request.method == "OPTIONS":
        return "", 204
    err = _hongbeilou_auth_error()
    if err:
        return err
    large, mid, small, share_ratio, min_stock, exclude_expired, markup_raw = _hongbeilou_read_export_params()
    sku_filter = _hongbeilou_read_sku_filter()
    conn = get_conn()
    try:
        rows = query_catalog_rows(
            conn,
            _effective_store_id(),
            category_large_code=large,
            category_mid_code=mid,
            category_small_code=small,
            min_stock=min_stock,
            share_ratio=share_ratio,
            exclude_expired=exclude_expired,
        )
    except Exception as e:
        conn.close()
        return jsonify({"ok": False, "error": str(e)}), 500
    conn.close()
    try:
        simple_rows, _mr = rows_to_simple_export(rows, markup_raw)
    except ValueError as ve:
        return jsonify({"ok": False, "error": str(ve)}), 400
    simple_rows = _hongbeilou_apply_sku_filter(simple_rows, sku_filter)
    from decimal import Decimal as _Dec
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["序号"] + [zh for _en, zh in EXPORT_SIMPLE_COLUMNS])
    for idx, r in enumerate(simple_rows, start=1):
        line = [idx]
        for key, _zh in EXPORT_SIMPLE_COLUMNS:
            v = r.get(key)
            if v is None:
                line.append("")
            elif isinstance(v, _Dec):
                line.append(float(v))
            elif hasattr(v, "isoformat"):
                line.append(v.isoformat())
            else:
                line.append(v)
        w.writerow(line)
    raw = "\ufeff" + buf.getvalue()
    fname = "hongbeilou_%s.csv" % (datetime.now().strftime("%Y%m%d_%H%M%S"),)
    return Response(
        raw.encode("utf-8"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="%s"' % fname},
    )


def _hongbeilou_disclaimer_lines():
    now = datetime.now()
    ts = now.strftime("%Y年%m月%d日 %H:%M")
    # 仅保留面向接收方的时效说明（供货价计算说明给操作者看，不出现在 PDF）
    return [
        "本选品单于%s生成，不代表其他时间有效。" % ts,
    ]


def _hongbeilou_read_watermark_flag():
    if request.method == "POST" and request.is_json:
        j = request.get_json(silent=True) or {}
        w = j.get("watermark", False)
        if isinstance(w, bool):
            return w
        return str(w).strip().lower() in ("1", "true", "yes", "on")
    return request.args.get("watermark", "").strip().lower() in ("1", "true", "yes", "on")


@channel_bp.route("/api/channel/hongbeilou/export_pdf", methods=["GET", "HEAD", "POST", "OPTIONS"])
def api_channel_hongbeilou_export_pdf():
    """红背篓选品导出 PDF；GET watermark=1 或 POST JSON watermark:true。POST 可带 sku_codes。列与 CSV 一致。"""
    if request.method == "OPTIONS":
        return "", 204
    err = _hongbeilou_auth_error()
    if err:
        return err
    large, mid, small, share_ratio, min_stock, exclude_expired, markup_raw = _hongbeilou_read_export_params()
    sku_filter = _hongbeilou_read_sku_filter()
    watermark = _hongbeilou_read_watermark_flag()
    conn = get_conn()
    try:
        rows = query_catalog_rows(
            conn,
            _effective_store_id(),
            category_large_code=large,
            category_mid_code=mid,
            category_small_code=small,
            min_stock=min_stock,
            share_ratio=share_ratio,
            exclude_expired=exclude_expired,
        )
    except Exception as e:
        conn.close()
        return jsonify({"ok": False, "error": str(e)}), 500
    conn.close()
    try:
        simple_rows, _mr = rows_to_simple_export(rows, markup_raw)
    except ValueError as ve:
        return jsonify({"ok": False, "error": str(ve)}), 400
    simple_rows = _hongbeilou_apply_sku_filter(simple_rows, sku_filter)
    try:
        from hongbeilou_pdf import render_hongbeilou_pdf_bytes
    except ImportError as e:
        return jsonify({"ok": False, "error": "缺少 PDF 依赖，请执行: pip install reportlab", "detail": str(e)}), 500
    disclaimer = _hongbeilou_disclaimer_lines()
    try:
        pdf_bytes = render_hongbeilou_pdf_bytes(
            simple_rows,
            EXPORT_SIMPLE_COLUMNS,
            title="供销社「红背篓」选品单",
            disclaimer_lines=disclaimer,
            watermark=watermark,
            watermark_text="宝赞商业＠振鸿",
        )
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()}), 500
    suffix = "_watermark" if watermark else ""
    fname = "hongbeilou_%s%s.pdf" % (datetime.now().strftime("%Y%m%d_%H%M%S"), suffix)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="%s"' % fname},
    )


@channel_bp.route("/api/channel/hongbeilou/batch", methods=["POST", "OPTIONS"])
def api_channel_hongbeilou_batch():
    """批量写入批次效期（需已建表 t_htma_sku_batch）。Body: {\"rows\":[{\"sku_code\",\"expiry_date\",\"qty\",...}]}"""
    if request.method == "OPTIONS":
        return "", 204
    err = _hongbeilou_auth_error()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    rows_in = body.get("rows")
    if not isinstance(rows_in, list) or not rows_in:
        return jsonify({"ok": False, "error": "请提供 rows 数组"}), 400
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if not table_exists(cur, "t_htma_sku_batch"):
                return jsonify({"ok": False, "error": "请先执行 scripts/25_create_sku_batch_table.sql 建表"}), 400
            n_ok = 0
            for row in rows_in:
                sku = (row.get("sku_code") or "").strip()
                exp = row.get("expiry_date")
                if not sku or not exp:
                    continue
                if isinstance(exp, str):
                    exp = exp[:10]
                qty = row.get("qty", 0)
                try:
                    qty = float(qty)
                except (TypeError, ValueError):
                    qty = 0
                batch_no = (row.get("batch_no") or "").strip() or None
                prod = row.get("production_date")
                if isinstance(prod, str) and prod:
                    prod = prod[:10]
                else:
                    prod = None
                remark = (row.get("remark") or "").strip() or None
                cur.execute(
                    """
                    INSERT INTO t_htma_sku_batch
                      (store_id, sku_code, batch_no, production_date, expiry_date, qty, remark)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (_effective_store_id(), sku, batch_no, prod, exp, qty, remark),
                )
                n_ok += 1
        conn.commit()
        return jsonify({"ok": True, "inserted": n_ok})
    except Exception as e:
        conn.rollback()
        import traceback
        return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()}), 500
    finally:
        conn.close()


