# -*- coding: utf-8 -*-
"""
异常检测引擎：监测经营数据突变，生成异常事件。
- 日销售额突变（环比前一日/同比上周同日）
- 毛利率骤降
- 预警+飞书推送
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from db_config import get_conn

logger = logging.getLogger("htma.anomaly")

# 阈值配置（可被环境变量覆盖）
ANOMALY_SALE_DROP_PCT = float(os.environ.get("ANOMALY_SALE_DROP_PCT", "25.0"))  # 日销售额环比跌超25%告警
ANOMALY_SALE_DROP_DAYS = int(os.environ.get("ANOMALY_SALE_DROP_DAYS", "7"))       # 同比上周同日跌超25%
ANOMALY_MARGIN_DROP_PCT = float(os.environ.get("ANOMALY_MARGIN_DROP_PCT", "30.0"))  # 毛利率跌超30%


def _get_yes_sales(cur, target_date: date) -> Optional[float]:
    """获取某日的总销售额（有数据则返回）"""
    cur.execute(
        "SELECT COALESCE(SUM(sale_amount), 0) AS sa FROM t_htma_sale WHERE data_date = %s",
        (target_date.isoformat(),),
    )
    r = cur.fetchone()
    if r:
        v = float(r.get("sa") or 0)
        return v if v > 0 else None
    return None


def _get_yes_summary_sales(cur, target_date: date) -> Optional[float]:
    """从每日预聚合表取（如果t_htma_sale没有数据就走这个fallback）"""
    cur.execute(
        "SELECT COALESCE(SUM(sale_amount), 0) AS sa FROM daily_category_stats WHERE data_date = %s",
        (target_date.isoformat(),),
    )
    r = cur.fetchone()
    if r:
        v = float(r.get("sa") or 0)
        return v if v > 0 else None
    return None


def scan_sale_anomaly(store_id: str = "沈阳超级仓") -> List[Dict[str, Any]]:
    """
    扫描日销售额异常。
    返回异常事件列表，每个事件格式与 alert_events 兼容。
    """
    events: List[Dict[str, Any]] = []
    conn = get_conn()
    try:
        cur = conn.cursor()
        # 找最新的有销日
        cur.execute(
            "SELECT MAX(data_date) AS mx FROM t_htma_sale WHERE 1=1"
        )
        r = cur.fetchone()
        if not r or not r.get("mx"):
            logger.info("[anomaly] t_htma_sale 无数据，跳过")
            return events
        latest = r["mx"]
        if hasattr(latest, "date"):
            latest_d = latest.date() if hasattr(latest, "date") else latest
        else:
            latest_d = date.fromisoformat(str(latest)[:10])

        # 检查最近5个有销日
        for offset in range(1, 6):
            target_d = latest_d - timedelta(days=offset)
            today_sales = _get_yes_sales(cur, target_d)
            if today_sales is None:
                today_sales = _get_yes_summary_sales(cur, target_d)
            if today_sales is None:
                continue

            # 环比前一日
            prev_d = target_d - timedelta(days=1)
            prev_sales = _get_yes_sales(cur, prev_d) or _get_yes_summary_sales(cur, prev_d)
            if prev_sales and prev_sales > 0:
                drop_pct = (prev_sales - today_sales) / prev_sales * 100
                if drop_pct >= ANOMALY_SALE_DROP_PCT:
                    events.append({
                        "type": "sale_drop_day",
                        "level": "warning",
                        "title": f"日销售额环比骤降 {drop_pct:.0f}%",
                        "summary": f"{target_d} 销售额 {today_sales:.0f} 元，较前一日 {prev_sales:.0f} 元下降 {drop_pct:.1f}%",
                        "date": target_d.isoformat(),
                        "metric": "total_sale_amount",
                        "current_value": round(today_sales, 2),
                        "previous_value": round(prev_sales, 2),
                        "change_pct": round(drop_pct, 2),
                    })

            # 同比上周同日
            week_ago = target_d - timedelta(days=7)
            week_sales = _get_yes_sales(cur, week_ago) or _get_yes_summary_sales(cur, week_ago)
            if week_sales and week_sales > 0:
                yoy_drop = (week_sales - today_sales) / week_sales * 100
                if yoy_drop >= ANOMALY_SALE_DROP_PCT:
                    events.append({
                        "type": "sale_drop_yoy",
                        "level": "info",
                        "title": f"日销售额同比上周同日下降 {yoy_drop:.0f}%",
                        "summary": f"{target_d} 销售额 {today_sales:.0f} 元，较上周同日 {week_sales:.0f} 元下降 {yoy_drop:.1f}%",
                        "date": target_d.isoformat(),
                        "metric": "total_sale_amount",
                        "current_value": round(today_sales, 2),
                        "previous_value": round(week_sales, 2),
                        "change_pct": round(yoy_drop, 2),
                    })
    finally:
        conn.close()
    return events


def build_anomaly_push_message(events: List[Dict[str, Any]]) -> Optional[str]:
    """将异常事件组拼成一条飞书推送文本"""
    if not events:
        return None
    lines = ["📊 好特卖经营异常检测", f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    for ev in events:
        icon = "🟠" if ev.get("level") == "warning" else "🔵"
        lines.append(f"{icon} {ev['title']}")
        lines.append(f"   {ev['summary']}")
        lines.append("")
    lines.append("---")
    lines.append("请登录看板查看详情：http://127.0.0.1:5002")
    return "\n".join(lines)
