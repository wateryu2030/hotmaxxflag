#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动化验证：飞书绑定门店与 /api/auth/me 的 dashboard_store_id 一致，
且 KPI / 毛利汇总 / 品类排行 / 低库存 使用同一门店口径（HTTP 200 + 结构合理）。

用法（项目根）:
  .venv/bin/python3 scripts/verify_web_session_store_apis.py

数据来源（按优先级）:
  1) 库表 t_htma_wechat_user 中同时存在 feishu_open_id + store_id 的真实绑定
  2) HTMA_VERIFY_FEISHU_OPEN_ID + HTMA_VERIFY_STORE_ID：模拟该飞书用户绑定门店（不改库）
  3) HTMA_VERIFY_AUTO=1：从 t_htma_sale 取任意有数据的 store_id，用固定测试 open_id
     ou_htma_verify_script + mock 绑定（不改库；需已配置飞书应用以启用鉴权）

环境:
  HTMA_DISABLE_APSCHEDULER=1  本脚本已默认设置
  勿设置 HTMA_UNITTEST_DISABLE_AUTH=1（否则不走登录门店逻辑）
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HTMA = os.path.join(_ROOT, "htma_dashboard")
if _HTMA not in sys.path:
    sys.path.insert(0, _HTMA)

os.chdir(_HTMA)
for _k in ("HTMA_UNITTEST_DISABLE_AUTH",):
    os.environ.pop(_k, None)
os.environ.setdefault("HTMA_DISABLE_APSCHEDULER", "1")
os.environ.setdefault("HTMA_SKIP_MOBILE_JWT", "1")

_env = os.path.join(_ROOT, ".env")
if os.path.isfile(_env):
    with open(_env, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

SYNTHETIC_FEISHU_OID = "ou_htma_verify_script"


def _truthy(x: str | None) -> bool:
    return (x or "").strip().lower() in ("1", "true", "yes", "on")


def _pick_bound_feishu_user(cur) -> tuple[str, str] | None:
    try:
        cur.execute(
            """
            SELECT feishu_open_id, store_id
            FROM t_htma_wechat_user
            WHERE TRIM(COALESCE(feishu_open_id, '')) != ''
              AND TRIM(COALESCE(store_id, '')) != ''
            LIMIT 1
            """
        )
    except Exception:
        return None
    row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        oid = (row.get("feishu_open_id") or "").strip()
        sid = (row.get("store_id") or "").strip()
    else:
        oid = (row[0] or "").strip()
        sid = (row[1] or "").strip()
    if oid and sid:
        return oid, sid
    return None


def _pick_any_sale_store_id(cur) -> str | None:
    try:
        cur.execute(
            "SELECT DISTINCT store_id FROM t_htma_sale WHERE TRIM(COALESCE(store_id,'')) != '' LIMIT 1"
        )
        row = cur.fetchone()
    except Exception:
        return None
    if not row:
        return None
    s = (row.get("store_id") if isinstance(row, dict) else row[0]) or ""
    s = str(s).strip()
    return s or None


def _install_feishu_bind_mock(*, synthetic_store: str | None, manual_oid: str, manual_sid: str) -> None:
    """在 import app 之前安装，使指定 open_id 解析为给定门店。"""
    import wechat_user_repo as wur

    _orig = wur.get_by_feishu_open_id
    mo, ms = (manual_oid or "").strip(), (manual_sid or "").strip()
    ss = (synthetic_store or "").strip()

    def _wrap(oid: str):
        o = (oid or "").strip()
        if mo and ms and o == mo:
            return {"feishu_open_id": o, "store_id": ms}
        if ss and o == SYNTHETIC_FEISHU_OID:
            return {"feishu_open_id": o, "store_id": ss}
        return _orig(oid)

    wur.get_by_feishu_open_id = _wrap  # type: ignore[assignment]


def main() -> int:
    from db_config import get_conn

    bound: tuple[str, str] | None = None
    auto_store: str | None = None
    conn = get_conn()
    try:
        cur = conn.cursor()
        bound = _pick_bound_feishu_user(cur)
        if not bound and _truthy(os.environ.get("HTMA_VERIFY_AUTO")):
            auto_store = _pick_any_sale_store_id(cur)
    finally:
        conn.close()

    manual_oid = (os.environ.get("HTMA_VERIFY_FEISHU_OPEN_ID") or "").strip()
    manual_sid = (os.environ.get("HTMA_VERIFY_STORE_ID") or "").strip()

    use_oid: str | None = None
    expect_store: str | None = None

    if bound:
        use_oid, expect_store = bound
    elif manual_oid and manual_sid:
        _install_feishu_bind_mock(synthetic_store=None, manual_oid=manual_oid, manual_sid=manual_sid)
        use_oid, expect_store = manual_oid, manual_sid
    elif auto_store:
        _install_feishu_bind_mock(synthetic_store=auto_store, manual_oid="", manual_sid="")
        use_oid, expect_store = SYNTHETIC_FEISHU_OID, auto_store

    sys.modules.pop("app", None)
    import app as app_mod  # noqa: E402

    app = app_mod.app

    def smoke_no_session():
        c = app.test_client()
        h = c.get("/api/health")
        assert h.status_code == 200, h.data
        me = c.get("/api/auth/me")
        assert me.status_code == 401, "未登录应 401"

    smoke_no_session()

    if not use_oid or not expect_store:
        print("[OK] /api/health、/api/auth/me(401) 已通过。")
        print(
            "[SKIP] 无绑定用户且未启用模拟：请任选其一 —"
            " (1) 在 t_htma_wechat_user 写入 feishu_open_id+store_id；"
            " (2) HTMA_VERIFY_AUTO=1（需 sale 表有 store_id）；"
            " (3) HTMA_VERIFY_FEISHU_OPEN_ID + HTMA_VERIFY_STORE_ID"
        )
        return 0

    c = app.test_client()
    with c.session_transaction() as sess:
        sess["open_id"] = use_oid
        sess["user_id"] = use_oid
        sess["user_name"] = "verify_script"
        for k in ("_feishu_bind_cache_oid", "_feishu_bind_done", "web_bound_store_id"):
            sess.pop(k, None)

    me = c.get("/api/auth/me")
    if me.status_code != 200:
        print("[FAIL] /api/auth/me HTTP", me.status_code, me.get_json() or me.data[:500])
        print("      若始终 401，请确认 .env 已配置 FEISHU_APP_ID / FEISHU_APP_SECRET（启用登录）。")
        return 1
    mj = me.get_json() or {}
    dash = (mj.get("dashboard_store_id") or "").strip()
    if dash != expect_store:
        print("[FAIL] dashboard_store_id 与预期不一致:", repr(dash), "!= 预期:", repr(expect_store))
        return 1
    print("[OK] dashboard_store_id == 预期门店:", repr(dash))

    paths = [
        "/api/kpi?period=recent30",
        "/api/profit_summary?period=recent30",
        "/api/category_rank?period=recent30",
        "/api/inv_alert",
        "/api/data_status",
    ]
    for path in paths:
        r = c.get(path)
        if r.status_code != 200:
            print("[FAIL]", path, "HTTP", r.status_code, (r.get_json() if r.is_json else r.data[:300]))
            return 1
        j = r.get_json()
        if path.startswith("/api/kpi") and not isinstance(j, dict):
            print("[FAIL] KPI 非 dict")
            return 1
        if path.startswith("/api/profit_summary") and not isinstance(j, list):
            print("[FAIL] profit_summary 非 list")
            return 1
        if path.startswith("/api/category_rank") and not isinstance(j, list):
            print("[FAIL] category_rank 非 list")
            return 1
        if path.startswith("/api/inv_alert") and not isinstance(j, dict):
            print("[FAIL] inv_alert 非 dict")
            return 1
        print(" [OK]", path.split("?")[0])

    print("[OK] 毛利/品类/库存/数据状态 与 KPI 同会话下均为 200，门店口径与 /api/auth/me 一致。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("[FAIL]", e)
        raise SystemExit(1)
