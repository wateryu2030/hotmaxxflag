#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 自动检查：人力成本前端看不到数据 — 重点飞书验证与接口/数据检查。
检查项：.env 飞书配置、/api/auth/feishu_url、/api/labor_cost 与 labor_cost_status 鉴权、
DB 人力数据、生产环境 redirect_uri 与 Cookie 说明。
用法（项目根目录）：python scripts/openclaw_labor_feishu_check.py [生产base_url]
"""
import os
import sys
import json
import urllib.request
import urllib.error

def load_env():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
    if not os.path.isfile(env_path):
        return root, {}
    env = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return root, env

def http_get(url, timeout=10, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace") if e.fp else ""
    except Exception as e:
        return None, str(e)

def main():
    root, env = load_env()
    sys.path.insert(0, root)
    base_local = "http://127.0.0.1:5002"
    base_remote = (sys.argv[1] if len(sys.argv) > 1 else env.get("HTMA_PUBLIC_URL") or "").strip().rstrip("/")

    feishu_id = (env.get("FEISHU_APP_ID") or os.environ.get("FEISHU_APP_ID") or "").strip()
    feishu_secret = (env.get("FEISHU_APP_SECRET") or os.environ.get("FEISHU_APP_SECRET") or "").strip()
    public_url = (env.get("HTMA_PUBLIC_URL") or os.environ.get("HTMA_PUBLIC_URL") or "").strip().rstrip("/")

    print("=" * 60)
    print("OpenClaw：人力成本 + 飞书验证 自动检查")
    print("=" * 60)

    # 1. .env 飞书配置
    print("\n[1] .env 飞书配置")
    print("    FEISHU_APP_ID:     ", "已配置 " + feishu_id[:8] + "..." if feishu_id else "未配置")
    print("    FEISHU_APP_SECRET: ", "已配置" if feishu_secret else "未配置")
    print("    HTMA_PUBLIC_URL:   ", public_url or "未配置（生产必填，用于飞书回调与 Cookie）")
    if not feishu_id or not feishu_secret:
        print("    → 请填写 .env 中 FEISHU_APP_ID、FEISHU_APP_SECRET 并重启看板")

    # 2. 本地 /api/auth/feishu_url（不依赖登录）
    print("\n[2] 本地 /api/auth/feishu_url（获取飞书登录链接）")
    code, body = http_get(base_local + "/api/auth/feishu_url", timeout=5)
    local_down = bool(code is None and body and ("refused" in str(body).lower() or "61" in str(body)))
    if local_down:
        print("    本地看板未启动（Connection refused），已跳过。若需校验本地接口请先: npm run htma:run 或 bash scripts/openclaw_labor_modify_and_check.sh")
    elif code is None:
        print("    请求失败:", body)
    elif code == 200:
        try:
            d = json.loads(body)
            if d.get("success") and d.get("url"):
                print("    200 OK，飞书授权 URL 可获取")
                redirect_uri = public_url + "/api/auth/feishu_callback" if public_url else "(由服务端 request 决定)"
                print("    回调 redirect_uri 应为:", redirect_uri)
            else:
                print("    200 但无 url:", d.get("message", body[:200]))
        except Exception:
            print("    200 响应:", body[:300])
    elif code == 400:
        try:
            d = json.loads(body)
            print("    400 未配置或错误:", d.get("message", body[:200]))
        except Exception:
            print("    400", body[:200])
    else:
        print("    HTTP", code, body[:200] if body else "")

    # 3. 本地 /api/labor_cost（需登录）、/api/labor_cost_status（已放行未登录）
    print("\n[3] 本地人力成本接口（未带 Cookie）")
    if local_down:
        print("    （本地未启动，已跳过）")
    else:
        code_cost, _ = http_get(base_local + "/api/labor_cost", timeout=5)
        code_status, _ = http_get(base_local + "/api/labor_cost_status", timeout=5)
        if code_cost == 401:
            print("    /api/labor_cost: 401 需登录（正常）")
        else:
            print("    /api/labor_cost: HTTP %s" % (code_cost or "ERR"))
        if code_status == 200:
            print("    /api/labor_cost_status: 200 可读（未登录也可看「现有记录」）")
        elif code_status == 401:
            print("    /api/labor_cost_status: 401 需登录")
        else:
            print("    /api/labor_cost_status: HTTP %s" % (code_status or "ERR"))

    # 4. 数据库人力数据
    print("\n[4] 数据库人力成本数据（本机 MySQL）")
    try:
        from htma_dashboard.db_config import get_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT report_month, position_type, COUNT(*) AS cnt FROM t_htma_labor_cost GROUP BY report_month, position_type ORDER BY report_month DESC, position_type LIMIT 20")
        rows = cur.fetchall()
        if not rows:
            print("    明细表 t_htma_labor_cost: 无数据")
            print("    → 即使登录成功，组长/组员明细也来自明细表；当前无明细会导致 Tab 中两表为空。请重新导入人力成本 Excel 或运行 scripts/openclaw_labor_import_and_notify.py")
        else:
            for r in rows:
                print("    ", r[0], r[1], r[2], "条")
        cur.execute("SELECT report_month FROM t_htma_labor_cost_analysis ORDER BY report_month DESC LIMIT 5")
        months = [row[0] for row in cur.fetchall()]
        print("    汇总表最近月份:", months or "无")
        conn.close()
    except Exception as e:
        print("    无法连接或查询:", e)

    # 5. 飞书验证与前端看不到数据的排查清单
    print("\n[5] 飞书验证与「前端看不到数据」排查")
    print("    • 飞书开放平台「安全设置」→ 重定向 URL 必须包含且仅使用：")
    print("      ", (public_url or "https://你的生产域名") + "/api/auth/feishu_callback")
    print("    • 生产若为 HTTPS，.env 中 HTMA_PUBLIC_URL 需为 https:// 开头（看板会自动设 SESSION_COOKIE_SECURE）")
    print("    • 登录后仍 401：在浏览器 F12 → Network → 点「人力成本」Tab → 看 /api/labor_cost 请求是否带 Cookie；")
    print("      若不带 Cookie，多为同站策略或域名不一致（如从 http 跳转到 https 需同域）")
    print("    • 若返回 200 但表格为空：报表月份留空点「查询」会拉最近月份；导入后接口会自动刷新汇总表，请再打开人力成本 Tab 查看。")

    # 6. 生产环境快速探测
    if base_remote:
        print("\n[6] 生产环境", base_remote)
        code, _ = http_get(base_remote + "/api/auth/feishu_url", timeout=8)
        if code == 200:
            print("    /api/auth/feishu_url: 200")
        elif code == 400:
            print("    /api/auth/feishu_url: 400（未配置飞书或配置错误）")
        else:
            print("    /api/auth/feishu_url: HTTP %s（可能网络/代理未开）" % (code or "ERR"))
        code2, _ = http_get(base_remote + "/api/labor_cost", timeout=6)
        print("    /api/labor_cost（无 Cookie）: %s（401=需登录正常）" % (code2 if code2 else "请求失败"))

    print("\n" + "=" * 60)
    print("检查结束。若飞书已配置且 redirect_uri 正确，登录后仍看不到数据请按 [5] 逐项排查。")
    print("=" * 60)

if __name__ == "__main__":
    main()
