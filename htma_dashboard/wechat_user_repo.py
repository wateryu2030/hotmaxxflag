# -*- coding: utf-8 -*-
"""微信小程序用户表访问（PyMySQL）。"""
from typing import Any, Dict, Optional

from db_config import get_conn


def _row(cur) -> Optional[Dict[str, Any]]:
    r = cur.fetchone()
    return dict(r) if r else None


def get_by_openid(openid: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM t_htma_wechat_user WHERE openid = %s LIMIT 1", (openid,))
        return _row(cur)
    finally:
        conn.close()


def get_by_id(uid: int) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM t_htma_wechat_user WHERE id = %s LIMIT 1", (int(uid),))
        return _row(cur)
    finally:
        conn.close()


def get_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    if not phone:
        return None
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM t_htma_wechat_user WHERE phone = %s LIMIT 1", (phone,))
        return _row(cur)
    finally:
        conn.close()


def get_by_feishu_open_id(feishu_open_id: str) -> Optional[Dict[str, Any]]:
    """飞书 open_id 与小程序 bind_feishu 写入的字段一致，用于网页端与小程序同店展示。"""
    oid = (feishu_open_id or "").strip()
    if not oid:
        return None
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM t_htma_wechat_user WHERE feishu_open_id = %s LIMIT 1",
            (oid,),
        )
        return _row(cur)
    finally:
        conn.close()


def upsert_user_after_login(openid: str, unionid: Optional[str], session_key: Optional[str]) -> Dict[str, Any]:
    """存在则更新 session_key / unionid；不存在则插入。"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM t_htma_wechat_user WHERE openid = %s LIMIT 1", (openid,))
        row = _row(cur)
        if row:
            cur.execute(
                """
                UPDATE t_htma_wechat_user
                SET session_key = COALESCE(%s, session_key),
                    unionid = COALESCE(NULLIF(%s, ''), unionid),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (session_key or None, unionid or "", row["id"]),
            )
            conn.commit()
            cur.execute("SELECT * FROM t_htma_wechat_user WHERE id = %s", (row["id"],))
            return dict(cur.fetchone())
        cur.execute(
            """
            INSERT INTO t_htma_wechat_user (openid, unionid, session_key, role, store_id)
            VALUES (%s, %s, %s, 'operator', NULL)
            """,
            (openid, unionid or None, session_key or None),
        )
        conn.commit()
        uid = cur.lastrowid
        cur.execute("SELECT * FROM t_htma_wechat_user WHERE id = %s", (uid,))
        return dict(cur.fetchone())
    finally:
        conn.close()


def update_phone(uid: int, phone: str) -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE t_htma_wechat_user SET phone = %s, updated_at = NOW() WHERE id = %s",
            (phone, int(uid)),
        )
        conn.commit()
    finally:
        conn.close()


def update_feishu_open_id(uid: int, feishu_open_id: str) -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE t_htma_wechat_user SET feishu_open_id = %s, updated_at = NOW() WHERE id = %s",
            (feishu_open_id.strip(), int(uid)),
        )
        conn.commit()
    finally:
        conn.close()


def update_role_store(uid: int, role: str, store_id: Optional[str]) -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE t_htma_wechat_user SET role = %s, store_id = %s, updated_at = NOW() WHERE id = %s",
            (role, store_id, int(uid)),
        )
        conn.commit()
    finally:
        conn.close()


def list_users(limit: int = 200) -> list:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, openid, phone, nickname, role, store_id, feishu_open_id, created_at
            FROM t_htma_wechat_user ORDER BY id DESC LIMIT %s
            """,
            (int(limit),),
        )
        return [dict(r) for r in cur.fetchall() or []]
    finally:
        conn.close()
