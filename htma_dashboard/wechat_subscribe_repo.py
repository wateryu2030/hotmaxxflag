# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional

from db_config import get_conn


def upsert_subscription(user_id: int, template_id: str, openid: str, is_active: bool) -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO t_htma_wechat_subscription (user_id, template_id, openid, is_active)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE is_active = VALUES(is_active), openid = VALUES(openid), updated_at = NOW()
            """,
            (int(user_id), template_id.strip(), openid.strip(), 1 if is_active else 0),
        )
        conn.commit()
    finally:
        conn.close()


def list_active_by_template(template_id: str) -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.user_id, s.openid, s.template_id
            FROM t_htma_wechat_subscription s
            WHERE s.is_active = 1 AND s.template_id = %s
            """,
            (template_id.strip(),),
        )
        return [dict(r) for r in (cur.fetchall() or [])]
    except Exception:
        return []
    finally:
        conn.close()


def list_all_active() -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT user_id, openid, template_id FROM t_htma_wechat_subscription WHERE is_active = 1
            """
        )
        return [dict(r) for r in (cur.fetchall() or [])]
    except Exception:
        return []
    finally:
        conn.close()
