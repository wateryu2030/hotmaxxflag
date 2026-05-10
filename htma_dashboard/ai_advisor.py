# -*- coding: utf-8 -*-
"""AI 经营快报：归因 + 预警 → LLM（无可用密钥时生成规则摘要）。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from analytics_utils import (
    compute_large_category_insights,
    daterange_prev_period,
    fetch_category_large_sales_aggregates,
    merge_category_large_sales_mom_attribution,
)
from db_config import get_conn

from routes_mobile import _has_daily_category_stats_table  # noqa: WPS433


def _table_exists(cur, name: str) -> bool:
    try:
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s LIMIT 1",
            (name,),
        )
        return cur.fetchone() is not None
    except Exception:
        return False


def _store_sql(store_id: str) -> tuple:
    sid = (store_id or "").strip()
    if not sid:
        return "", []
    return " AND store_id = %s ", [sid]


def _chat_url_from_base(base: str) -> str:
    b = (base or "").strip().rstrip("/")
    if not b:
        return ""
    return b if b.endswith("/chat/completions") else b + "/chat/completions"


def _post_openai_compatible_chat(url: str, api_key: str, model: str, prompt: str) -> Optional[str]:
    """OpenAI 兼容 POST /chat/completions，返回 assistant 文本或 None。"""
    key = (api_key or "").strip()
    if not key or not url:
        return None
    body = json.dumps(
        {
            "model": (model or "").strip() or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "你是资深零售经营顾问，输出简洁中文。"},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 600,
            "temperature": 0.35,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="replace"))
        choices = raw.get("choices") or []
        if not choices:
            return None
        msg = (choices[0].get("message") or {}).get("content") or ""
        return (msg or "").strip() or None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError):
        return None


def _try_deepseek(prompt: str) -> Tuple[Optional[str], str]:
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return None, ""
    base = (os.environ.get("HTMA_DEEPSEEK_API_BASE") or "https://api.deepseek.com/v1").strip().rstrip("/")
    model = (os.environ.get("DEEPSEEK_MODEL") or os.environ.get("HTMA_DEEPSEEK_MODEL") or "deepseek-chat").strip()
    url = _chat_url_from_base(base)
    out = _post_openai_compatible_chat(url, key, model, prompt)
    return out, "deepseek" if out else ""


def _try_doubao(prompt: str) -> Tuple[Optional[str], str]:
    key = (os.environ.get("DOUBAO_API_KEY") or os.environ.get("VOLCANO_ENGINE_API_KEY") or "").strip()
    if not key:
        return None, ""
    base = (os.environ.get("DOUBAO_API_BASE") or "https://ark.cn-beijing.volces.com/api/v3").strip().rstrip("/")
    model = (os.environ.get("DOUBAO_MODEL") or os.environ.get("HTMA_DOUBAO_MODEL") or "").strip()
    if not model:
        return None, ""
    url = _chat_url_from_base(base)
    out = _post_openai_compatible_chat(url, key, model, prompt)
    return out, "doubao" if out else ""


def _try_openai_explicit(prompt: str) -> Tuple[Optional[str], str]:
    base = (os.environ.get("HTMA_LLM_API_URL") or "").strip().rstrip("/")
    key = (os.environ.get("HTMA_LLM_API_KEY") or "").strip()
    model = (os.environ.get("HTMA_LLM_MODEL") or "").strip()
    if not key or not base:
        return None, ""
    url = _chat_url_from_base(base)
    out = _post_openai_compatible_chat(url, key, model or "gpt-4o-mini", prompt)
    return out, "openai_compat" if out else ""


def _try_openai_env(prompt: str) -> Tuple[Optional[str], str]:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None, ""
    base = (os.environ.get("OPENAI_API_BASE") or "https://api.openai.com/v1").strip().rstrip("/")
    model = (os.environ.get("OPENAI_MODEL") or os.environ.get("HTMA_OPENAI_MODEL") or "gpt-4o-mini").strip()
    url = _chat_url_from_base(base)
    out = _post_openai_compatible_chat(url, key, model, prompt)
    return out, "openai" if out else ""


def _call_llm(prompt: str) -> Tuple[Optional[str], str]:
    """
    按 HTMA_LLM_PROVIDER 调用 LLM，返回 (文本, 提供商标识)。
    - auto（默认）: DeepSeek → 豆包(火山方舟) → HTMA_LLM_* → OPENAI_*
    - deepseek / doubao / openai：仅尝试对应一路（openai 含 HTMA_LLM_* 与 OPENAI_API_KEY）
    """
    prov = (os.environ.get("HTMA_LLM_PROVIDER") or "auto").strip().lower()
    if prov in ("", "auto", "chain", "default"):
        for fn in (_try_deepseek, _try_doubao, _try_openai_explicit, _try_openai_env):
            text, tag = fn(prompt)
            if text:
                return text, tag
        return None, ""
    if prov == "deepseek":
        return _try_deepseek(prompt)
    if prov in ("doubao", "volcano", "ark"):
        return _try_doubao(prompt)
    if prov in ("openai", "compat", "gpt"):
        text, tag = _try_openai_explicit(prompt)
        if text:
            return text, tag
        return _try_openai_env(prompt)
    if prov == "openai_only":
        return _try_openai_env(prompt)
    if prov == "htma":
        return _try_openai_explicit(prompt)
    # 未知值回退为与 auto 相同的链式尝试
    for fn in (_try_deepseek, _try_doubao, _try_openai_explicit, _try_openai_env):
        text, tag = fn(prompt)
        if text:
            return text, tag
    return None, ""


def _stub_report(
    attribution: Dict[str, Any],
    alerts: List[Dict[str, Any]],
    insights: Optional[Dict[str, Any]] = None,
) -> str:
    dtot = attribution.get("delta_total")
    top = (attribution.get("by_category") or [])[:3]
    parts = [
        "【自动经营摘要】",
        f"近对比区间销售额净变动约 {dtot if dtot is not None else '—'}。",
    ]
    if top:
        parts.append(
            "大类贡献居前：" + "；".join(f"{t.get('category_large') or ''}(Δ{t.get('delta')})" for t in top if t) + "。"
        )
    ins = insights or {}
    slope = ins.get("sales_ma7_slope_pct")
    lows = ins.get("margin_zscore_low") or []
    if slope is not None:
        parts.append(f"全店近端7日均线销额动量约 {slope}%（相对前一7日均）。")
    if lows:
        topz = lows[0]
        parts.append(
            f"毛利率统计异常偏低：{topz.get('category_large') or ''} 最新日毛利率约 {topz.get('latest_margin_pct')}% "
            f"(Z≈{topz.get('zscore_margin')})，建议核查定价/损耗/组合。"
        )
    if alerts:
        parts.append(f"当前未处理预警 {len(alerts)} 条，请关注低毛利大类与库存结构。")
    parts.append("建议：①对 Z 负向突出大类做单品毛利穿透；②按 7 日均线方向调整档期与陈列；③跟踪日环比与周中周末差异。")
    text = "".join(parts)
    return text[:480]


def generate_daily_summary(
    store_id: Optional[str] = None,
    report_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    生成当日 AI 快报写入 daily_ai_reports。
    归因区间：report_date 前推 29 天共 30 天 vs 上一等长区间（与 Phase1 一致）。
    """
    sid = (store_id or os.environ.get("HTMA_STORE_ID") or "沈阳超级仓").strip()
    rd = report_date or date.today()
    end = rd
    start = rd - timedelta(days=29)
    d0, d1 = start, end
    ps, pe = daterange_prev_period(d0, d1)
    s_cur, e_cur = d0.isoformat(), d1.isoformat()
    s_prev, e_prev = ps.isoformat(), pe.isoformat()
    sq, sp = _store_sql(sid)
    conn = get_conn()
    try:
        cur = conn.cursor()
        if not _table_exists(cur, "daily_ai_reports"):
            return {"ok": False, "message": "daily_ai_reports 表不存在"}
        if not _has_daily_category_stats_table(cur):
            return {"ok": False, "message": "daily_category_stats 表不存在"}
        rows_prev = fetch_category_large_sales_aggregates(cur, s_prev, e_prev, sq, tuple(sp))
        rows_cur = fetch_category_large_sales_aggregates(cur, s_cur, e_cur, sq, tuple(sp))
        attribution = merge_category_large_sales_mom_attribution(rows_prev, rows_cur)
        alerts: List[Dict[str, Any]] = []
        if _table_exists(cur, "alert_events"):
            cur.execute(
                """
                SELECT id, type, level, title, summary, payload_json, created_at
                FROM alert_events
                WHERE store_id=%s AND acked_at IS NULL
                ORDER BY created_at DESC LIMIT 15
                """,
                (sid,),
            )
            for r in cur.fetchall() or []:
                pj = r.get("payload_json")
                if isinstance(pj, str):
                    try:
                        pj = json.loads(pj)
                    except Exception:
                        pj = {}
                alerts.append(
                    {
                        "id": r.get("id"),
                        "type": r.get("type"),
                        "level": r.get("level"),
                        "title": r.get("title"),
                        "summary": r.get("summary"),
                        "payload": pj or {},
                    }
                )
        ins_start = rd - timedelta(days=39)
        cur.execute(
            "SELECT data_date, category_large_code, MAX(category_large) AS category_large, "
            "SUM(sale_amount) AS sa, SUM(gross_profit) AS gp "
            "FROM daily_category_stats WHERE store_id=%s AND data_date BETWEEN %s AND %s "
            "GROUP BY data_date, category_large_code ORDER BY data_date, category_large_code",
            (sid, ins_start.isoformat(), rd.isoformat()),
        )
        insight_rows = list(cur.fetchall() or [])
        insights = compute_large_category_insights(
            insight_rows, z_threshold=2.0, min_hist_days=5, min_last_sales=500
        )
        insights_audit = {
            "sales_ma7_slope_pct": insights.get("sales_ma7_slope_pct"),
            "margin_zscore_low_n": len(insights.get("margin_zscore_low") or []),
            "source": "cursor_auto_evolve",
        }
        prompt = (
            "你是资深零售专家。请根据归因、预警与「算法信号」写 150 字以内经营快报。"
            "必须：①用至少 1 个具体数字（如环比%、Z 分、均线动量%）；②指出最优先处理的一大类及原因；"
            "③给 3 条可执行动作（定价/陈列/档期各至少一条逻辑链）。\n\n"
            "【销售额大类归因摘要】\n"
            + json.dumps(
                {
                    "prev_total": attribution.get("prev_total"),
                    "cur_total": attribution.get("cur_total"),
                    "delta_total": attribution.get("delta_total"),
                    "top_deltas": (attribution.get("by_category") or [])[:8],
                },
                ensure_ascii=False,
            )
            + "\n\n【算法信号：毛利率 Z-Score（最新日相对自身历史）与全店销额 7 日均线动量】\n"
            + json.dumps(
                {
                    "sales_ma7_slope_pct": insights.get("sales_ma7_slope_pct"),
                    "margin_zscore_low_top5": (insights.get("margin_zscore_low") or [])[:5],
                    "margin_zscore_high_top3": (insights.get("margin_zscore_high") or [])[:3],
                },
                ensure_ascii=False,
            )
            + "\n\n【未处理预警】\n"
            + json.dumps(alerts, ensure_ascii=False)
        )
        llm_text, llm_tag = _call_llm(prompt)
        text = (llm_text or "").strip() or _stub_report(attribution, alerts, insights)
        text = text[:2000]
        meta = {
            "attribution_range": {"current": {"start": s_cur, "end": e_cur}, "previous": {"start": s_prev, "end": e_prev}},
            "alerts_used": len(alerts),
            "llm_used": bool(llm_text),
            "llm_provider": llm_tag or None,
            "llm_provider_requested": (os.environ.get("HTMA_LLM_PROVIDER") or "auto").strip(),
            "insights_signals": insights_audit,
        }
        meta_json = json.dumps(meta, ensure_ascii=False)
        cur.execute(
            "SELECT id FROM daily_ai_reports WHERE store_id=%s AND report_date=%s LIMIT 1",
            (sid, rd.isoformat()),
        )
        ex = cur.fetchone()
        if ex:
            cur.execute(
                "UPDATE daily_ai_reports SET content=%s, meta_json=%s, created_at=CURRENT_TIMESTAMP WHERE id=%s",
                (text, meta_json, ex.get("id")),
            )
        else:
            cur.execute(
                "INSERT INTO daily_ai_reports (report_date, store_id, content, meta_json) VALUES (%s,%s,%s,%s)",
                (rd.isoformat(), sid, text, meta_json),
            )
        conn.commit()
        return {"ok": True, "report_date": rd.isoformat(), "store_id": sid, "chars": len(text)}
    except Exception as ex:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "message": str(ex)}
    finally:
        conn.close()
