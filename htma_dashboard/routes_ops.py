# -*- coding: utf-8 -*-
"""
运维管理面板路由：
- 统一任务面板（导入记录+预警+AI快评）
- 异常检测扫描
- 运维配置读写
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import Blueprint, g, jsonify, request, send_from_directory

from db_config import get_conn
from extensions import invalidate_mobile_cache

logger = logging.getLogger("htma.ops")

# ============================================================
# Blueprint
# ============================================================
ops_bp = Blueprint("ops", __name__, url_prefix="/api/ops")


def register_ops_routes(app):
    app.register_blueprint(ops_bp)


def _effective_store_id() -> str:
    """与首页 KPI 同店：用于运维条上的销售/库存新鲜度与库存摘要。"""
    mod = sys.modules.get("app") or sys.modules.get("__main__")
    if mod is not None and hasattr(mod, "_effective_store_id"):
        try:
            sid = mod._effective_store_id()
            if sid:
                return str(sid).strip()
        except Exception:
            pass
    return (os.environ.get("HTMA_STORE_ID") or "沈阳超级仓").strip() or "沈阳超级仓"


# 运维面板不校验飞书登录，本地直接可用
@ops_bp.before_request
def _ops_before_request():
    if request.method == "OPTIONS":
        return None
    # 本地运维接口，不做飞书登录拦截
    from flask import g
    g.wechat_jwt_payload = None
    return None


# ============================================================
# 统一任务面板（模块2）
# ============================================================
@ops_bp.route("/dashboard", methods=["GET", "OPTIONS"])
def api_ops_dashboard():
    """
    聚合面板数据：
    - 最近5次导入记录（时间、类型、行数）
    - 活跃预警（未确认）
    - 最新 AI 报告摘要
    - 库存水位摘要
    - 数据新鲜度（最新销售日期距今天数）
    """
    if request.method == "OPTIONS":
        return "", 204
    sid = _effective_store_id()
    conn = get_conn()
    try:
        cur = conn.cursor()
        out: Dict[str, Any] = {
            "last_imports": [],
            "active_alerts": [],
            "latest_ai_report": None,
            "inventory_summary": None,
            "data_freshness": None,
        }

        # 1. 最近导入记录（从 t_htma_sale 的 data_date 推断导入情况 + import_logic 留下的线索）
        # 实际项目中若能记录导入日志最好，现回退到查销售表最新日期
        cur.execute(
            "SELECT MAX(data_date) AS mx FROM t_htma_sale WHERE store_id = %s",
            (sid,),
        )
        r = cur.fetchone()
        sale_latest = str(r["mx"])[:10] if r and r.get("mx") else None

        cur.execute(
            "SELECT MAX(data_date) AS mx FROM t_htma_stock WHERE store_id = %s",
            (sid,),
        )
        r = cur.fetchone()
        stock_latest = str(r["mx"])[:10] if r and r.get("mx") else None

        # 从 daily_ai_reports 取最新报告日期
        cur.execute("SELECT MAX(report_date) AS mx FROM daily_ai_reports")
        r = cur.fetchone()
        ai_latest = str(r["mx"])[:10] if r and r.get("mx") else None

        # 从 t_htma_report_log 取最近报告记录
        cur.execute(
            "SELECT id, report_date, report_time, send_status FROM t_htma_report_log ORDER BY id DESC LIMIT 5"
        )
        for row in cur.fetchall() or []:
            status_map = {0: "未发送", 1: "已推送", -1: "失败"}
            out["last_imports"].append({
                "type": "report_push",
                "date": str(row.get("report_date") or "")[:10],
                "time": str(row.get("report_time") or ""),
                "status": status_map.get(row.get("send_status"), "未知"),
            })

        # 2. 活跃预警（alert_events 表）
        cur.execute("""
            SELECT id, type, level, title, summary, created_at
            FROM alert_events
            WHERE acked_at IS NULL
            ORDER BY created_at DESC
            LIMIT 20
        """)
        for row in cur.fetchall() or []:
            out["active_alerts"].append({
                "id": row["id"],
                "type": row.get("type", ""),
                "level": row.get("level", "info"),
                "title": row.get("title", ""),
                "summary": row.get("summary", ""),
                "created_at": str(row.get("created_at") or "")[:19],
            })

        # 3. 最新 AI 报告
        cur.execute("""
            SELECT report_date, content, created_at
            FROM daily_ai_reports
            ORDER BY report_date DESC, id DESC LIMIT 1
        """)
        r = cur.fetchone()
        if r:
            out["latest_ai_report"] = {
                "date": str(r.get("report_date") or "")[:10],
                "content": (r.get("content") or "")[:500],
                "created_at": str(r.get("created_at") or "")[:19],
            }

        # 4. 数据新鲜度
        from datetime import date as dt_date
        today = dt_date.today()
        freshness = {}
        if sale_latest:
            try:
                sale_d = dt_date.fromisoformat(sale_latest)
                freshness["sale_days_ago"] = (today - sale_d).days
                freshness["sale_latest_date"] = sale_latest
            except Exception:
                pass
        if stock_latest:
            try:
                stock_d = dt_date.fromisoformat(stock_latest)
                freshness["stock_days_ago"] = (today - stock_d).days
                freshness["stock_latest_date"] = stock_latest
            except Exception:
                pass
        if ai_latest:
            try:
                ai_d = dt_date.fromisoformat(ai_latest)
                freshness["ai_report_days_ago"] = (today - ai_d).days
                freshness["ai_report_latest_date"] = ai_latest
            except Exception:
                pass
        out["data_freshness"] = freshness if freshness else None

        # 5. 库存摘要（仅取最新日期）
        cur.execute("""
            SELECT COUNT(*) AS sku_count,
                   COALESCE(SUM(stock_qty), 0) AS total_qty,
                   COALESCE(SUM(COALESCE(stock_amount, 0)), 0) AS total_amount
            FROM t_htma_stock
            WHERE store_id = %s
              AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = %s)
        """, (sid, sid))
        r = cur.fetchone()
        if r:
            out["inventory_summary"] = {
                "sku_count": int(r.get("sku_count") or 0),
                "total_qty": float(r.get("total_qty") or 0),
                "total_amount": round(float(r.get("total_amount") or 0), 2),
            }

    except Exception as e:
        logger.exception("[ops_dashboard] error")
        return jsonify({"code": 2, "data": {}, "msg": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"code": 0, "data": out, "msg": ""})


# ============================================================
# 异常检测扫描（模块3）
# ============================================================
@ops_bp.route("/anomaly/scan", methods=["POST", "OPTIONS"])
def api_ops_anomaly_scan():
    """
    手动触发异常检测扫描，返回发现的异常事件。
    如果配置了飞书 Webhook，会自动推送。
    """
    if request.method == "OPTIONS":
        return "", 204
    from anomaly_detector import build_anomaly_push_message, scan_sale_anomaly

    events = scan_sale_anomaly()

    # 尝试推送飞书
    pushed = False
    msg = build_anomaly_push_message(events)
    if msg:
        try:
            feishu_webhook = os.environ.get("HTMA_FEISHU_ALERT_WEBHOOK", "").strip()
            if feishu_webhook:
                import requests
                resp = requests.post(
                    feishu_webhook,
                    json={"msg_type": "text", "content": {"text": msg}},
                    timeout=10,
                )
                if resp.status_code == 200:
                    pushed = True
        except Exception as e:
            logger.warning("[anomaly] feishu push failed: %s", e)

    return jsonify({
        "code": 0,
        "data": {
            "events": events,
            "event_count": len(events),
            "pushed_to_feishu": pushed,
        },
        "msg": "",
    })


# ============================================================
# 运维配置面板（模块4）
# ============================================================
@ops_bp.route("/config", methods=["GET", "POST", "OPTIONS"])
def api_ops_config():
    """
    GET: 读取运维配置（从 .env 中读关键运维参数）
    POST: 更新运维配置（写回 .env 文件）
    """
    if request.method == "OPTIONS":
        return "", 204

    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))

    # 运维可见配置项（白名单）
    OPS_CONFIG_KEYS = [
        "BACKEND_PORT",
        "MYSQL_HOST", "MYSQL_PORT", "MYSQL_DATABASE",
        "WECHAT_MINI_ENABLED",
        "HTMA_IMPORT_DOWNLOADS_DIR",
        "HTMA_FEISHU_ALERT_WEBHOOK",
        "HTMA_MOBILE_CACHE_SECONDS",
        "ANOMALY_SALE_DROP_PCT",
        "ANOMALY_SALE_DROP_DAYS",
        "ANOMALY_MARGIN_DROP_PCT",
    ]

    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            lines = []

        # 更新白名单内的配置
        updated_keys = set()
        for key in OPS_CONFIG_KEYS:
            if key in body:
                val = str(body[key]).strip()
                # 查找并替换
                found = False
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith(key + "=") or stripped.startswith("# " + key + "="):
                        lines[i] = f"{key}={val}\n"
                        found = True
                        break
                if not found:
                    lines.append(f"{key}={val}\n")
                updated_keys.add(key)

        # 特殊处理隐藏键（密码类不返回value）
        if "MYSQL_PASSWORD" in body:
            # 找到并替换
            for i, line in enumerate(lines):
                if line.strip().startswith("MYSQL_PASSWORD="):
                    lines[i] = f"MYSQL_PASSWORD={body['MYSQL_PASSWORD']}\n"
                    break
            updated_keys.add("MYSQL_PASSWORD")

        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            return jsonify({"code": 1, "data": {}, "msg": f"写入 .env 失败: {e}"}), 500

        return jsonify({"code": 0, "data": {"updated_keys": list(updated_keys)}, "msg": "配置已更新，重启看板后生效"})

    # GET: 读取配置
    config = {}
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if "=" in stripped and not stripped.startswith("#"):
                    k, v = stripped.split("=", 1)
                    k = k.strip()
                    if k in OPS_CONFIG_KEYS:
                        config[k] = v.strip()
    except Exception:
        pass

    return jsonify({"code": 0, "data": config, "msg": ""})


# ============================================================
# Web 页面
# ============================================================
@ops_bp.route("/panel", methods=["GET"])
def api_ops_panel():
    """运维面板 Web 页面"""
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), "static"),
        "ops_panel.html",
    )
