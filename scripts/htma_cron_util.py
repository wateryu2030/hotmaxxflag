#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定时任务共用：飞书 Webhook 通知 + 带重试的步骤执行。"""
from __future__ import annotations

import json
import os
import time
import traceback
import urllib.error
import urllib.request


def cron_webhook_url() -> str:
    for k in ("HTMA_CRON_WEBHOOK_URL", "FEISHU_WEBHOOK_URL"):
        u = (os.environ.get(k) or "").strip()
        if u:
            return u
    return ""


def cron_notify(msg: str, ok: bool = True) -> None:
    url = cron_webhook_url()
    if not url:
        print(msg)
        return
    body = json.dumps(
        {
            "msg_type": "text",
            "content": ("[HTMA Cron] " + ("OK " if ok else "FAIL ")) + msg[:3500],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=15).read()
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        import sys

        print("webhook_fail", ex, file=sys.stderr)


def cron_run_step(name: str, fn, retries: int = 2) -> None:
    import sys

    last = None
    for attempt in range(retries + 1):
        try:
            out = fn()
            print(name, out)
            if (os.environ.get("HTMA_CRON_NOTIFY_SUCCESS") or "").strip() in ("1", "true", "yes"):
                cron_notify(f"{name}: {out}", ok=True)
            return
        except Exception as ex:
            last = ex
            print(name, "attempt", attempt, ex, file=sys.stderr)
            time.sleep(min(8, 2**attempt))
    tb = traceback.format_exc()
    cron_notify(f"{name} 失败: {last}\n{tb}", ok=False)
    raise last
