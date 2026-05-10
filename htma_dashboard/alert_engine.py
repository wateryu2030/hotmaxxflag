# -*- coding: utf-8 -*-
"""规则引擎：扫描经营数据并写入 alert_events（库存类规则预留）。"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from db_config import get_conn

from routes_mobile import _has_daily_category_stats_table  # noqa: WPS433


def _env_float(name: str, default: float) -> float:
    try:
        return float((os.environ.get(name) or str(default)).strip())
    except Exception:
        return float(default)


def _table_exists(cur, name: str) -> bool:
    try:
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s LIMIT 1",
            (name,),
        )
        return cur.fetchone() is not None
    except Exception:
        return False


def check_inventory_risks(cur, store_id: str, sq: str, sp: Tuple) -> List[Dict[str, Any]]:
    """预留：库存风险扫描；接入 daily_inventory_snapshot 后实现。"""
    return []


def _low_margin_large_category_rows(
    cur, s: str, e: str, sq: str, sp: List[Any], margin_thr: float, share_thr: float
) -> List[Dict[str, Any]]:
    cur.execute(
        "SELECT COALESCE(SUM(sale_amount),0) AS t FROM daily_category_stats WHERE data_date BETWEEN %s AND %s " + sq,
        (s, e) + tuple(sp),
    )
    tot_sa = float((cur.fetchone() or {}).get("t") or 0.0) or 0.0
    if tot_sa <= 0:
        return []
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
        (s, e) + tuple(sp),
    )
    out: List[Dict[str, Any]] = []
    for row in cur.fetchall() or []:
        sa = float(row.get("sa") or 0)
        gp = float(row.get("gp") or 0)
        if sa <= 0:
            continue
        m_pct = gp / sa * 100.0
        sh_pct = (sa / tot_sa * 100.0) if tot_sa > 0 else 0.0
        if m_pct < margin_thr and sh_pct > share_thr:
            out.append(
                {
                    "category_large_code": row.get("category_large_code") or "",
                    "category_large": row.get("category_large") or "",
                    "margin_pct": round(m_pct, 2),
                    "share_pct": round(sh_pct, 2),
                    "sale_amount": round(sa, 2),
                }
            )
    return out


def _insert_alert_if_new(
    cur,
    *,
    store_id: str,
    dedupe_key: str,
    typ: str,
    level: str,
    title: str,
    summary: str,
    payload: Dict[str, Any],
) -> bool:
    """同日同 dedupe_key 不重复插入。返回是否新插入。"""
    cur.execute(
        "SELECT id FROM alert_events WHERE dedupe_key=%s AND DATE(created_at)=CURDATE() LIMIT 1",
        (dedupe_key,),
    )
    if cur.fetchone():
        return False
    cur.execute(
        """
        INSERT INTO alert_events (type, level, title, summary, payload_json, store_id, dedupe_key)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            typ,
            level,
            title,
            summary,
            json.dumps(payload, ensure_ascii=False),
            store_id or "",
            dedupe_key,
        ),
    )
    return True


def check_all_rules(
    store_id: Optional[str] = None,
    days: int = 30,
) -> Dict[str, Any]:
    """
    扫描规则并写入 alert_events。
    store_id 默认读环境变量 HTMA_STORE_ID，否则「沈阳超级仓」。
    """
    sid = (store_id or os.environ.get("HTMA_STORE_ID") or "沈阳超级仓").strip()
    margin_thr = _env_float("HTMA_ALERT_ENGINE_LOW_MARGIN_PCT", 10.0)
    share_thr = _env_float("HTMA_ALERT_ENGINE_LARGE_SHARE_PCT", 5.0)
    end = date.today()
    start = end - timedelta(days=max(1, int(days)) - 1)
    s, e = start.isoformat(), end.isoformat()
    sq, sp = (" AND store_id = %s ", [sid]) if sid else ("", [])
    inserted = 0
    inv_scanned = 0
    conn = get_conn()
    try:
        cur = conn.cursor()
        if not _table_exists(cur, "alert_events"):
            return {"ok": False, "message": "alert_events 表不存在，请先执行 scripts/33_alert_events_daily_ai_reports.sql", "inserted": 0}
        if not _has_daily_category_stats_table(cur):
            return {"ok": False, "message": "daily_category_stats 表不存在", "inserted": 0}
        rows = _low_margin_large_category_rows(cur, s, e, sq, list(sp), margin_thr, share_thr)
        for r in rows:
            code = (r.get("category_large_code") or "").strip()
            name = (r.get("category_large") or code or "大类").strip()
            dedupe = f"low_margin_large|{sid}|{code}|{s}|{e}"
            title = "低毛利大类（规则引擎）"
            summary = f"{name} 毛利率 {r.get('margin_pct')}% ，销额占比 {r.get('share_pct')}%"
            payload = {
                "category_large_code": code,
                "category_large": name,
                "margin_pct": r.get("margin_pct"),
                "share_pct": r.get("share_pct"),
                "sale_amount": r.get("sale_amount"),
                "range": {"start_date": s, "end_date": e},
            }
            if _insert_alert_if_new(
                cur,
                store_id=sid,
                dedupe_key=dedupe[:190],
                typ="low_margin_large",
                level="critical" if r.get("margin_pct", 0) < margin_thr * 0.5 else "warning",
                title=title,
                summary=summary,
                payload=payload,
            ):
                inserted += 1
        inv = check_inventory_risks(cur, sid, sq, tuple(sp))
        inv_scanned = len(inv)
        conn.commit()
        return {
            "ok": True,
            "store_id": sid,
            "range": {"start_date": s, "end_date": e},
            "inserted": inserted,
            "inventory_candidates": inv_scanned,
            "rules": ["low_margin_large", "inventory_risk_stub"],
        }
    except Exception as ex:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "message": str(ex), "inserted": inserted}
    finally:
        conn.close()
