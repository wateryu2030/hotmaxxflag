# -*- coding: utf-8 -*-
"""微信订阅：每日 9:00 检查告警；未配置模板 ID 时只打日志（预留 sendMessage 调用点）。"""
import logging
import os
import sys
from datetime import date, timedelta

_log = logging.getLogger("htma.wechat_scheduler")


def _app_mod():
    return sys.modules.get("app") or sys.modules.get("__main__")


def _send_subscribe_message_stub(openid: str, template_id: str, data: dict) -> None:
    """
    调用微信 subscribeMessage 发送。需 access_token 与已审核模板。
    无模板/未全量联调时仅记录日志。
    """
    try:
        from wechat_wxa import get_access_token  # type: ignore

        tok, err = get_access_token()
    except Exception:
        tok, err = None, "get_access_token failed"
    if err or not tok:
        _log.info("[wechat] skip send: %s (openid=%s...)", err or "no token", (openid or "")[:8])
        return
    _log.info(
        "[wechat] (mock) would POST message/subscribe/send openid=%s... template_id=%s data=%s",
        (openid or "")[:8],
        template_id,
        data,
    )


def run_daily_alert_check() -> None:
    """9:00 任务：对活跃订阅拉取（可选）每店告警，发送或打日志。"""
    today = date.today()
    s = (today - timedelta(days=29)).isoformat()
    e = today.isoformat()
    tpl = (os.environ.get("WECHAT_SUBSCRIBE_TEMPLATE_ID") or "").strip()
    try:
        from wechat_subscribe_repo import list_all_active
    except Exception as e:
        _log.warning("list_all_active import: %s", e)
        return
    act = list_all_active()
    if not act:
        _log.info("daily alert: no active subscriptions (table empty or not migrated)")
        return
    if not tpl:
        _log.info("daily alert: %d active subs; WECHAT_SUBSCRIBE_TEMPLATE_ID unset — mock only", len(act))
    try:
        from db_config import get_conn
    except Exception:
        _log.exception("get_conn")
        return
    _log.info("daily alert: date_range %s~%s, active_subs=%d", s, e, len(act))
    for row in act:
        openid = (row.get("openid") or "").strip()
        tid = (row.get("template_id") or tpl or "").strip()
        if not openid or not tid:
            continue
        if tpl:
            tid = tpl
        # 预留：此处可接 routes_mobile._alerts_list 的简化版
        _send_subscribe_message_stub(
            openid,
            tid,
            {"date3": {"value": e}, "thing1": {"value": "运营预警摘要"}},
        )


def start_background_scheduler():
    if (os.environ.get("HTMA_DISABLE_APSCHEDULER") or "").strip().lower() in ("1", "true", "yes", "on"):
        _log.info("APScheduler disabled (HTMA_DISABLE_APSCHEDULER)")
        return None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except Exception as e:
        _log.warning("APScheduler not available: %s", e)
        return None
    sched = BackgroundScheduler()
    sched.add_job(run_daily_alert_check, "cron", hour=9, minute=0, id="htma_wechat_daily_alert", replace_existing=True)
    try:
        sched.start()
    except Exception as e:
        _log.warning("scheduler start: %s", e)
        return None
    _log.info("APScheduler: daily 09:00 wechat alert job registered")
    return sched
