#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
货盘比价 · OpenClaw 百度 Skill 自检脚本（模拟看板环境，调试直至通过）
用法：在项目根目录执行
  export PATH="$HOME/.npm-global/bin:/usr/local/bin:$PATH"
  python scripts/selfserve_price_compare_debug.py
或（推荐）：
  bash scripts/run_selfserve_price_compare_debug.sh
"""
import os
import sys
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTMA_DASHBOARD = os.path.join(PROJECT_ROOT, "htma_dashboard")


def ensure_path():
    """与 launchd 看板一致：保证 clawhub/openclaw 在 PATH 中"""
    paths_to_add = [
        os.path.expanduser("~/Library/pnpm"),
        os.path.expanduser("~/.npm-global/bin"),
    ]
    path = os.environ.get("PATH", "")
    for p in paths_to_add:
        if os.path.isdir(p) and p not in path:
            os.environ["PATH"] = f"{p}:{path}"
            print(f"[PATH] 已注入 {p}")
    if HTMA_DASHBOARD not in sys.path:
        sys.path.insert(0, HTMA_DASHBOARD)
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)


def step1_gateway_http():
    """步骤1：通过网关 HTTP POST /tools/invoke 调用比价（与看板一致）"""
    print("\n--- 步骤1: 网关 HTTP POST /tools/invoke get_price_comparison 洽洽坚果 ---")
    ensure_path()
    os.chdir(HTMA_DASHBOARD)
    try:
        from baidu_skill_compare import _call_baidu_skill_via_gateway
        res = _call_baidu_skill_via_gateway("洽洽坚果", timeout=25)
        print("网关返回:", res)
        if res.get("status") == "success" and res.get("data"):
            print("[OK] 步骤1 通过：网关返回比价数据")
            return True
        print("[FAIL] 步骤1:", res.get("message", res))
        return False
    except Exception as e:
        print(f"[FAIL] 步骤1: {e}")
        return False


def step2_call_baidu_skill():
    """步骤2：通过 baidu_skill_compare.call_baidu_skill 调用（与看板同模块）"""
    print("\n--- 步骤2: 在 htma_dashboard 下 import 并调用 call_baidu_skill ---")
    ensure_path()
    os.chdir(HTMA_DASHBOARD)
    try:
        from baidu_skill_compare import call_baidu_skill
        res = call_baidu_skill("洽洽坚果", max_price=100)
        print("call_baidu_skill 返回:", res)
        if res.get("status") == "success" and res.get("data"):
            print("[OK] 步骤2 通过")
            return True
        print("[FAIL] 步骤2:", res.get("message", res))
        return False
    except ImportError as e:
        print("[FAIL] 步骤2 ImportError:", e)
        return False
    except Exception as e:
        print(f"[FAIL] 步骤2: {e}")
        return False


def step3_item_fetcher():
    """步骤3：baidu_skill_item_fetcher 单条（与 run_full_pipeline 使用的接口一致）"""
    print("\n--- 步骤3: baidu_skill_item_fetcher 单条 ---")
    ensure_path()
    os.chdir(HTMA_DASHBOARD)
    try:
        from baidu_skill_compare import baidu_skill_item_fetcher
        item = {"raw_name": "洽洽坚果礼喜上眉梢1.45kg", "std_name": "洽洽坚果", "unit_price": 95.80}
        out = baidu_skill_item_fetcher(item)
        print("baidu_skill_item_fetcher 返回:", out)
        if out and (out.get("min_price") is not None or out.get("jd_min_price") is not None or out.get("taobao_min_price") is not None):
            print("[OK] 步骤3 通过：拿到竞品价")
            return True
        if out:
            print("[WARN] 步骤3：返回了结构但无竞品价，可能 Skill 未命中该商品")
        else:
            print("[FAIL] 步骤3：返回 None 或未拿到竞品价")
        return False
    except ImportError as e:
        print("[FAIL] 步骤3 ImportError:", e)
        return False
    except Exception as e:
        print(f"[FAIL] 步骤3: {e}")
        import traceback
        traceback.print_exc()
        return False


def step4_run_full_pipeline_mini():
    """步骤4：run_full_pipeline fetch_limit=2，确认走百度 Skill 且不报 OneBound"""
    print("\n--- 步骤4: run_full_pipeline(..., fetch_limit=2) 小规模比价 ---")
    ensure_path()
    os.chdir(HTMA_DASHBOARD)
    # 加载 .env
    env_file = os.path.join(PROJECT_ROOT, ".env")
    if os.path.isfile(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip("'\"").strip()
                    if k:
                        os.environ[k] = v
    try:
        from price_compare import run_full_pipeline
        try:
            import pymysql
        except ImportError:
            print("[SKIP] 步骤4：未安装 pymysql，跳过（看板环境会有）")
            return True
        conn = pymysql.connect(
            host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ.get("MYSQL_DATABASE", "htma_dashboard"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        result = run_full_pipeline(
            conn, store_id="沈阳超级仓", days=30,
            use_mock_fetcher=False, save_to_db=False, fetch_limit=2,
        )
        conn.close()
        platform = result.get("fetcher_platform", "")
        err = result.get("fetcher_error")
        items = result.get("items", [])
        print("fetcher_platform:", platform)
        print("fetcher_error:", err)
        print("items 条数:", len(items))
        if items:
            for i, it in enumerate(items[:2]):
                print(f"  项{i+1}: {it.get('raw_name')} 竞品最低={it.get('competitor_min')} tier={it.get('tier')}")
        if "百度" in platform and not err:
            print("[OK] 步骤4 通过：本次比价使用百度 Skill，且无 OneBound 报错")
            return True
        if err and "过期" in str(err):
            print("[FAIL] 步骤4：仍在使用万邦且 Key 过期，说明百度 Skill 未被选用（import 或 PATH 问题）")
        else:
            print("[WARN] 步骤4：fetcher_platform=%s fetcher_error=%s" % (platform, err))
        return False
    except ImportError as e:
        print("[FAIL] 步骤4 ImportError:", e)
        return False
    except Exception as e:
        print(f"[FAIL] 步骤4: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("货盘比价 · OpenClaw 百度 Skill 自检（模拟看板环境）")
    print("项目根:", PROJECT_ROOT)
    ensure_path()
    # 与 launchd 一致的工作目录：先项目根，再在步骤里 chdir 到 htma_dashboard 测试 import
    os.chdir(PROJECT_ROOT)

    ok1 = step1_gateway_http()
    ok2 = step2_call_baidu_skill()
    ok3 = step3_item_fetcher()
    ok4 = step4_run_full_pipeline_mini()

    print("\n======== 汇总 ========")
    print("步骤1 (网关 HTTP):", "通过" if ok1 else "失败")
    print("步骤2 (call_baidu_skill):", "通过" if ok2 else "失败")
    print("步骤3 (item_fetcher):", "通过" if ok3 else "失败")
    print("步骤4 (run_full_pipeline):", "通过" if ok4 else "失败")
    if ok1 and ok2 and ok3 and ok4:
        print("全部通过，看板货盘比价应能使用百度 Skill。")
        return 0
    print("请根据上述失败步骤排查（PATH、OpenClaw 网关、baidu-preferred 启用、MySQL）。")
    # 显示带实际 token 的控制台地址（与 baidu_skill_compare 一致）
    try:
        from baidu_skill_compare import GATEWAY_URL, GATEWAY_TOKEN
        console_url = f"{GATEWAY_URL}/#token={GATEWAY_TOKEN}"
    except Exception:
        console_url = "http://127.0.0.1:18789/#token=123456"
    print("\n【当前环境限制】npm 版 ClawHub 无 run 子命令；网关 /tools/invoke 未暴露 get_price_comparison。")
    print("可选：1) 在 OpenClaw 网页 Chat (" + console_url + ") 中说「请用百度优选比价洽洽坚果」；")
    print("      2) 配置 .env 中 ONEBOUND_KEY/ONEBOUND_SECRET 使用万邦比价。详见 docs/百度Skill比价环境说明.md")
    return 1


if __name__ == "__main__":
    sys.exit(main())
