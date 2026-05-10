# -*- coding: utf-8 -*-
"""比价 API — serve_web/price_compare：商品比价、能力说明、每日比价、比价结果查询"""

import json
import os
import subprocess
import sys
from datetime import datetime

from flask import Blueprint, jsonify, request

from core.context import _effective_store_id
from core.db import get_conn
from core.utils import safe_float, safe_int

price_bp = Blueprint("price", __name__)

# 百度 Skill / Runner 多平台能力说明（供前端展示）
PRICE_COMPARE_SUPPORTED_PLATFORMS = ["京东", "淘宝", "拼多多", "唯品会", "百度", "百度优选"]
PRICE_COMPARE_DATA_FORMAT_NOTE = (
    'Runner（scripts/openclaw_baidu_tools_runner.py）解析多平台格式：'
    '{"京东": {"price": 12.5}, "淘宝": {"price": 11}} 或数字简写 {"京东": 12.5, "淘宝": 11}。'
)


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


@price_bp.route("/api/price_compare_products", methods=["GET", "OPTIONS"])
def api_price_compare_products():
    """比价商品列表：从 t_htma_platform_products 读取，按大类、中类、小类分组。若表为空则先同步。"""
    if request.method == "OPTIONS":
        return "", 204
    try:
        from price_compare import load_platform_products_from_db, sync_platform_products, stage1_standardize
        days = int(request.args.get("days", 30))
        limit = int(request.args.get("limit", 300))
        sync_first = request.args.get("sync", "1") == "1"
        conn = get_conn()
        try:
            try:
                items = load_platform_products_from_db(conn, store_id=_effective_store_id(), limit=limit)
            except Exception:
                items = []
            if not items and sync_first:
                sync_platform_products(conn, store_id=_effective_store_id(), days=days, limit=limit)
                items = load_platform_products_from_db(conn, store_id=_effective_store_id(), limit=limit)
            if not items:
                items_raw = stage1_standardize(conn, store_id=_effective_store_id(), days=days, limit=limit)
                items = [{"sku_code": it.get("sku_code"), "raw_name": it.get("raw_name"), "spec": it.get("spec") or "", "barcode": it.get("barcode") or "", "brand_name": it.get("brand_name") or "", "category_large": it.get("category_large") or "未分类", "category_mid": it.get("category_mid") or "未分类", "category_small": it.get("category_small") or "未分类", "unit_price": round(float(it.get("unit_price") or 0), 2), "sale_qty": float(it.get("sale_qty") or 0), "sale_amount": round(float(it.get("sale_amount") or 0), 2)} for it in items_raw]
            groups = {}
            for it in items:
                large = (it.get("category_large") or "未分类").strip() or "未分类"
                mid = (it.get("category_mid") or "未分类").strip() or "未分类"
                small = (it.get("category_small") or "未分类").strip() or "未分类"
                if large not in groups:
                    groups[large] = {}
                if mid not in groups[large]:
                    groups[large][mid] = {}
                if small not in groups[large][mid]:
                    groups[large][mid][small] = []
                groups[large][mid][small].append({
                    "sku_code": it.get("sku_code", ""),
                    "raw_name": it.get("raw_name", ""),
                    "spec": it.get("spec", ""),
                    "barcode": it.get("barcode", ""),
                    "brand_name": it.get("brand_name", ""),
                    "unit_price": round(float(it.get("unit_price") or 0), 2),
                    "sale_qty": float(it.get("sale_qty") or 0),
                    "sale_amount": round(float(it.get("sale_amount") or 0), 2),
                })
            return jsonify({"success": True, "groups": groups, "total": len(items)})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "groups": {}, "total": 0, "error": str(e)}), 500


@price_bp.route("/api/price_compare/capability", methods=["GET"])
def api_price_compare_capability():
    """比价能力说明：支持的多平台与数据格式，供前端展示。可选 check_runner=1 探测当前数据来源。"""
    out = {
        "supported_platforms": PRICE_COMPARE_SUPPORTED_PLATFORMS,
        "data_format_note": PRICE_COMPARE_DATA_FORMAT_NOTE,
        "runner_script": "scripts/openclaw_baidu_tools_runner.py",
    }
    if request.args.get("check_runner") == "1":
        try:
            _root = os.path.dirname(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
            _runner = os.path.join(_root, "scripts", "openclaw_baidu_tools_runner.py")
            if os.path.isfile(_runner):
                r = subprocess.run(
                    [sys.executable, _runner, "get_price_comparison", "洽洽坚果"],
                    capture_output=True,
                    text=True,
                    timeout=25,
                    cwd=_root,
                    env=dict(os.environ),
                )
                for line in reversed((r.stdout or "").strip().split("\n")):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if isinstance(d, dict) and d.get("source"):
                            out["current_source"] = d["source"]
                            break
                    except Exception:
                        continue
        except Exception:
            pass
    return jsonify(out)


@price_bp.route("/api/price_compare", methods=["GET", "POST", "OPTIONS"])
def api_price_compare():
    """货盘价格对比分析 - 4 阶段闭环，返回完整报告。POST 时使用真实 API"""
    if request.method == "OPTIONS":
        return "", 204
    try:
        from price_compare import run_full_pipeline, format_report
        if request.method == "GET":
            days = int(request.args.get("days", 30))
            fetch_limit = request.args.get("fetch_limit", type=int)
            sku_codes = None
        else:
            data = (request.get_json(silent=True) or {}) if request.is_json else {}
            days = int(data.get("days", 30))
            fetch_limit = data.get("fetch_limit")
            sku_codes = data.get("sku_codes")  # 前端勾选的货号，仅对选中项比价
        if fetch_limit is None:
            try:
                v = os.environ.get("PRICE_COMPARE_FETCH_LIMIT", "")
                fetch_limit = int(v) if v else None
            except (TypeError, ValueError):
                fetch_limit = None
        use_mock = request.method == "GET"  # POST 时用真实 API
        conn = get_conn()
        try:
            result = run_full_pipeline(conn, store_id=_effective_store_id(), days=days, use_mock_fetcher=use_mock, fetch_limit=fetch_limit, sku_codes=sku_codes)
            report = format_report(result)
            items = result.get("items", [])
            # 构建表格数据，确保 items 字段始终存在（即使为空数组）
            table_rows = []
            if items and isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        table_rows.append({
                            "raw_name": str(it.get("raw_name") or it.get("std_name") or ""),
                            "spec": str(it.get("spec") or "-"),
                            "unit_price": it.get("unit_price"),
                            "jd_min_price": it.get("jd_min_price"),
                            "taobao_min_price": it.get("taobao_min_price"),
                            "competitor_min": it.get("competitor_min"),
                            "platform": str(it.get("platform") or "-"),
                            "advantage_pct": it.get("advantage_pct"),
                            "tier": str(it.get("tier") or "独家款"),
                            "price_source": it.get("price_source"),
                        })
            # 本次返回的平台与数据来源（供前端展示）
            platforms_returned = _platforms_returned_from_items(items)
            price_sources = list({it.get("price_source") for it in (items or []) if it.get("price_source")})
            # 确保 items 字段始终存在；返回竞品接口状态便于前端提示
            summary = result.get("portfolio", {}).get("summary", {}) if isinstance(result.get("portfolio"), dict) else {}
            exclusive = summary.get("exclusive", 0)
            total = summary.get("total", 0)
            response_data = {
                "success": True,
                "report": str(report) if report else "",
                "summary": summary,
                "items": table_rows,
                "use_real_fetcher": result.get("use_real_fetcher", False),
                "fetcher_error": result.get("fetcher_error"),
                "fetcher_platform": result.get("fetcher_platform", ""),
                "all_exclusive_hint": bool(total > 0 and exclusive == total and result.get("use_real_fetcher")),
                "supported_platforms": PRICE_COMPARE_SUPPORTED_PLATFORMS,
                "data_format_note": PRICE_COMPARE_DATA_FORMAT_NOTE,
                "platforms_returned": platforms_returned,
                "price_sources": price_sources,
            }
            return jsonify(response_data)
        finally:
            conn.close()
    except Exception as e:
        error_msg = str(e)
        return jsonify({"success": False, "report": "", "items": [], "error": error_msg}), 500


@price_bp.route("/api/price_compare_daily", methods=["POST", "OPTIONS"])
def api_price_compare_daily():
    """
    每日自动比价：按当日（或昨日）销售 TOP 商品比价，可选推送飞书。
    供用户主动触发或 OpenClaw/cron 调用。body: limit, fetch_limit, send_feishu, feishu_at_user_id
    """
    if request.method == "OPTIONS":
        return "", 204
    try:
        from price_compare import run_daily_top_compare, format_report
        from feishu_util import send_feishu
        data = (request.get_json(silent=True) or {}) if request.is_json else {}
        limit = int(data.get("limit", 50))
        fetch_limit = data.get("fetch_limit")
        if fetch_limit is not None:
            fetch_limit = int(fetch_limit)
        send_feishu_flag = data.get("send_feishu", False)
        at_user_id = data.get("feishu_at_user_id") or os.environ.get("FEISHU_AT_USER_ID", "ou_8db735f2")
        at_user_name = data.get("feishu_at_user_name") or os.environ.get("FEISHU_AT_USER_NAME", "余为军")
        conn = get_conn()
        try:
            result = run_daily_top_compare(
                conn, store_id=_effective_store_id(), data_date=None, limit=limit,
                use_mock_fetcher=False, save_to_db=True, fetch_limit=fetch_limit or limit,
            )
            report = format_report(result)
            items = result.get("items", [])
            feishu_sent = False
            feishu_ok = wecom_ok = dingtalk_ok = False
            if send_feishu_flag and items:
                try:
                    from notify_util import notify_all
                    results, _ = notify_all(report, title="好特卖商品比价报告",
                        feishu_at_user_id=at_user_id, feishu_at_user_name=at_user_name)
                    feishu_ok = results.get("feishu", (False,))[0]
                    wecom_ok = results.get("wecom", (False,))[0]
                    dingtalk_ok = results.get("dingtalk", (False,))[0]
                except Exception:
                    from feishu_util import send_feishu
                    feishu_ok, _ = send_feishu(
                        report, at_user_id=at_user_id, at_user_name=at_user_name, title="好特卖商品比价报告"
                    )
                feishu_sent = True
            table_rows = []
            for it in items:
                if isinstance(it, dict):
                    table_rows.append({
                        "raw_name": str(it.get("raw_name") or it.get("std_name") or ""),
                        "spec": str(it.get("spec") or "-"),
                        "unit_price": it.get("unit_price"),
                        "jd_min_price": it.get("jd_min_price"),
                        "taobao_min_price": it.get("taobao_min_price"),
                        "competitor_min": it.get("competitor_min"),
                        "platform": str(it.get("platform") or "-"),
                        "advantage_pct": it.get("advantage_pct"),
                        "tier": str(it.get("tier") or "独家款"),
                    })
            return jsonify({
                "success": True,
                "report": report,
                "data_date": result.get("data_date"),
                "items": table_rows,
                "summary": result.get("portfolio", {}).get("summary", {}),
                "feishu_sent": feishu_sent,
                "feishu_ok": feishu_ok,
                "wecom_ok": wecom_ok,
                "dingtalk_ok": dingtalk_ok,
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "report": "", "items": [], "error": str(e)}), 500


@price_bp.route("/api/price_compare_results", methods=["GET", "OPTIONS"])
def api_price_compare_results():
    """查询已保存的比价结果（实体化数据），支持按 run_at、tier 筛选"""
    if request.method == "OPTIONS":
        return "", 204
    run_at = request.args.get("run_at", "").strip()  # 如 2026-02-18
    tier = request.args.get("tier", "").strip()  # 高优势款/独家款/价格劣势款 等
    limit = min(int(request.args.get("limit", 200)), 500)
    conn = get_conn()
    store_id = _effective_store_id()
    try:
        with conn.cursor() as cur:
            conds, params = [], [store_id]
            if run_at:
                conds.append("DATE(run_at) = %s")
                params.append(run_at)
            if tier:
                conds.append("tier = %s")
                params.append(tier)
            where = " AND " + " AND ".join(conds) if conds else ""
            params.append(limit)
            try:
                cur.execute(f"""
                    SELECT run_at, sku_code, std_name, raw_name, spec, barcode, category,
                           unit_price, jd_min_price, jd_platform, taobao_min_price, taobao_platform,
                           competitor_min, advantage_pct, tier, platform
                    FROM t_htma_price_compare
                    WHERE store_id = %s {where}
                    ORDER BY run_at DESC, advantage_pct DESC
                    LIMIT %s
                """, params)
            except Exception:
                cur.execute(f"""
                    SELECT run_at, sku_code, std_name, category, unit_price,
                           competitor_min, advantage_pct, tier, platform
                    FROM t_htma_price_compare
                    WHERE store_id = %s {where}
                    ORDER BY run_at DESC, advantage_pct DESC
                    LIMIT %s
                """, params)
            rows = cur.fetchall()
        items = []
        for r in rows:
            run_at_val = r.get("run_at")
            run_at_str = run_at_val.isoformat() if run_at_val and hasattr(run_at_val, "isoformat") else str(run_at_val or "")
            items.append({
                "run_at": run_at_str,
                "sku_code": r.get("sku_code"),
                "std_name": r.get("std_name"),
                "raw_name": r.get("raw_name"),
                "spec": r.get("spec"),
                "barcode": r.get("barcode"),
                "category": r.get("category"),
                "unit_price": float(r["unit_price"]) if r.get("unit_price") is not None else None,
                "jd_min_price": float(r["jd_min_price"]) if r.get("jd_min_price") is not None else None,
                "jd_platform": r.get("jd_platform"),
                "taobao_min_price": float(r["taobao_min_price"]) if r.get("taobao_min_price") is not None else None,
                "taobao_platform": r.get("taobao_platform"),
                "competitor_min": float(r["competitor_min"]) if r.get("competitor_min") is not None else None,
                "advantage_pct": float(r["advantage_pct"]) if r.get("advantage_pct") is not None else None,
                "tier": r.get("tier"),
                "platform": r.get("platform"),
            })
        return jsonify({"success": True, "items": items, "total": len(items)})
    except Exception as e:
        return jsonify({"success": False, "items": [], "error": str(e)}), 500
    finally:
        conn.close()
