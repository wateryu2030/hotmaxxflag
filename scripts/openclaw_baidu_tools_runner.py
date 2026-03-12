#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 网关 /tools/invoke 桥接：被 baidu-price-tools 插件调用。
优先使用百度 Skill：1) 若配置 OPENCLAW_BAIDU_SKILL_GATEWAY_URL 则请求该网关；2) 否则 clawhub run；
3) 均不可用时回退到百度优选 MCP。clawhub 上已无 baidu-preferred，推荐用方式 1 配置「百度 Skill 专用网关」。

用法:
  python scripts/openclaw_baidu_tools_runner.py get_price_comparison '商品名'
  python scripts/openclaw_baidu_tools_runner.py search_products '商品名'
输出: 单行 JSON 到 stdout；错误时 exit 1。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Optional, Tuple

_script_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.abspath(os.path.join(_script_dir, ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))
except ImportError:
    pass

BAIDU_SKILL_SLUG = os.environ.get("BAIDU_SKILL_SLUG", "baidu-preferred")
SKILL_TIMEOUT = int(os.environ.get("BAIDU_SKILL_RUNNER_TIMEOUT", "45"))

# 百度 Skill 专用网关：clawhub 上已无 baidu-preferred 时，配置此处可优先走该网关（如手机/其他端已可用的 OpenClaw 网关）
BAIDU_SKILL_GATEWAY_URL = (os.environ.get("OPENCLAW_BAIDU_SKILL_GATEWAY_URL") or "").strip().rstrip("/")
BAIDU_SKILL_GATEWAY_TOKEN = (os.environ.get("OPENCLAW_BAIDU_SKILL_GATEWAY_TOKEN") or os.environ.get("OPENCLAW_GATEWAY_TOKEN") or "").strip()


def _call_baidu_skill_gateway(action: str, query: str) -> Tuple[Optional[dict], Optional[list], str]:
    """若配置了 OPENCLAW_BAIDU_SKILL_GATEWAY_URL，请求该网关 /tools/invoke。返回 (data_dict 或 None, products_list 或 None, error_msg)。"""
    if not BAIDU_SKILL_GATEWAY_URL or not query.strip():
        return None, None, ""
    try:
        import urllib.request
        import urllib.error
        payload = {"tool": action, "args": {"query": query.strip()}}
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{BAIDU_SKILL_GATEWAY_URL}/tools/invoke",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {BAIDU_SKILL_GATEWAY_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=min(SKILL_TIMEOUT, 40)) as r:
            out = json.loads(r.read().decode())
        if not out.get("ok"):
            err = out.get("error", {})
            return None, None, (err.get("message") or str(out))[:300]
        result = out.get("result")
        if not isinstance(result, dict):
            return None, None, "网关返回格式异常"
        if action == "get_price_comparison":
            data = result.get("data") or result
            if isinstance(data, dict) and (data.get("京东") or data.get("淘宝") or data.get("百度") or data.get("百度优选") or data.get("拼多多") or data.get("唯品会")):
                return data, None, ""
            if isinstance(data, dict) and data:
                return data, None, ""
        if action == "search_products":
            products = result.get("products")
            if isinstance(products, list) and products:
                return None, products, ""
            data = result.get("data") or result
            if isinstance(data, dict):
                plist = []
                for plat, info in data.items():
                    if isinstance(info, dict) and info.get("price") is not None:
                        plist.append({"title": query.strip(), "price": float(info["price"]), "platform": plat})
                if plist:
                    return None, plist, ""
    except Exception as e:
        return None, None, str(e)[:300]
    return None, None, ""


def _run_clawhub_skill(action: str, query: str) -> Tuple[Optional[dict], str]:
    """调用 clawhub run 百度 Skill，返回 (解析后的 data 或 None, 错误信息)。"""
    query = (query or "").strip()
    if not query:
        return None, "query required"
    # clawhub run <slug> --query <query>；部分 skill 用 --query 或 -q
    cmd = ["clawhub", "run", BAIDU_SKILL_SLUG, "--query", query]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SKILL_TIMEOUT,
            cwd=_root,
            env=dict(os.environ),
        )
    except FileNotFoundError:
        return None, "未找到 clawhub，请确保已安装 OpenClaw/ClawHub 且 PATH 中含 clawhub"
    except subprocess.TimeoutExpired:
        return None, "百度 Skill 调用超时"
    except Exception as e:
        return None, str(e)[:300]
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    # 解析 stdout：可能整段 JSON，或最后一行 JSON，或文本中含价格
    for blob in (out, out.split("\n")[-1] if out else ""):
        blob = (blob or "").strip()
        if not blob:
            continue
        try:
            obj = json.loads(blob)
            if isinstance(obj, dict):
                if obj.get("data") and isinstance(obj["data"], dict):
                    return obj["data"], ""
                if obj.get("status") == "success" and obj.get("data"):
                    return obj["data"] if isinstance(obj["data"], dict) else None, ""
                # 兼容 { "京东": 1.0, "淘宝": 2.0 } 或 { "京东": {"price": 1}, ... }
                if any(k in obj for k in ("京东", "淘宝", "拼多多", "唯品会", "百度")):
                    data = {}
                    for k, v in obj.items():
                        if k in ("京东", "淘宝", "拼多多", "唯品会", "百度", "百度优选") and v is not None:
                            if isinstance(v, dict) and "price" in v:
                                data[k] = v
                            elif isinstance(v, (int, float)) and v > 0:
                                data[k] = {"price": float(v)}
                    if data:
                        return data, ""
        except (json.JSONDecodeError, TypeError):
            pass
    # 尝试从文本中抽取「平台: 价格」或 数字
    if out:
        price_match = re.search(r"[\d.]+\s*元|¥\s*([\d.]+)|(\d+\.\d{2})", out)
        if price_match:
            p = price_match.group(1) or price_match.group(2) or price_match.group(0).replace("元", "").strip()
            try:
                price = float(re.sub(r"[^\d.]", "", p))
                if price > 0:
                    return {"百度优选": {"price": price}}, ""
            except (TypeError, ValueError):
                pass
    return None, err or out or "百度 Skill 未返回可解析的价格"


def _fallback_youxuan_price(query: str) -> Optional[dict]:
    """clawhub run 不可用时回退：百度优选 MCP 单商品最低价 -> { 百度优选: { price } }。"""
    try:
        from htma_dashboard.baidu_fetcher import baidu_youxuan_price_fetcher
        r = baidu_youxuan_price_fetcher(query)
        if r is not None and r.get("min_price") is not None:
            return {"百度优选": {"price": float(r["min_price"])}}
    except Exception:
        pass
    return None


def _fallback_youxuan_search(query: str) -> list:
    """clawhub run 不可用时回退：百度优选 MCP 商品列表 -> [{title, price, platform}]。"""
    try:
        from htma_dashboard.baidu_fetcher import baidu_youxuan_search_items
        return baidu_youxuan_search_items(query, page_size=20) or []
    except Exception:
        return []


def run_get_price_comparison(query: str) -> dict:
    """优先百度 Skill 专用网关 → clawhub run → 百度优选 MCP。返回带 source 字段便于排查。"""
    query = (query or "").strip()
    if not query:
        return {"error": "query required"}
    if BAIDU_SKILL_GATEWAY_URL:
        data, _, _ = _call_baidu_skill_gateway("get_price_comparison", query)
        if data:
            return {"data": data, "source": "baidu_skill"}
    data, err = _run_clawhub_skill("get_price_comparison", query)
    if data:
        return {"data": data, "source": "baidu_skill"}
    data = _fallback_youxuan_price(query)
    if data:
        return {"data": data, "source": "baidu_youxuan_mcp"}
    return {"error": err or "no price data", "data": {}, "source": "none"}


def run_search_products(query: str) -> dict:
    """优先百度 Skill 专用网关 → clawhub run → 百度优选 MCP。返回带 source 字段。"""
    query = (query or "").strip()
    if not query:
        return {"error": "query required", "products": []}
    if BAIDU_SKILL_GATEWAY_URL:
        _, products, _ = _call_baidu_skill_gateway("search_products", query)
        if products:
            return {"products": products[:20], "source": "baidu_skill"}
    data, err = _run_clawhub_skill("search_products", query)
    if data:
        products = []
        for plat, info in data.items():
            if isinstance(info, dict) and info.get("price") is not None:
                try:
                    products.append({"title": query, "price": float(info["price"]), "platform": plat})
                except (TypeError, ValueError):
                    pass
        if products:
            return {"products": products[:20], "source": "baidu_skill"}
    data, _ = _run_clawhub_skill("get_price_comparison", query)
    if data:
        products = []
        for plat, info in (data or {}).items():
            if isinstance(info, dict) and info.get("price") is not None:
                try:
                    products.append({"title": query, "price": float(info["price"]), "platform": plat})
                except (TypeError, ValueError):
                    pass
        if products:
            return {"products": products[:20], "source": "baidu_skill"}
    products = _fallback_youxuan_search(query)
    if products:
        return {"products": products[:20], "source": "baidu_youxuan_mcp"}
    return {"products": [], "error": err or "百度 Skill/MCP 未返回列表", "source": "none"}


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: get_price_comparison|search_products <query>"}), flush=True)
        sys.exit(1)
    action = (sys.argv[1] or "").strip().lower()
    query = (sys.argv[2] or "").strip()
    if action == "get_price_comparison":
        result = run_get_price_comparison(query)
    elif action == "search_products":
        result = run_search_products(query)
    else:
        result = {"error": f"unknown action: {action}"}
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if result.get("error") and not result.get("data") and not result.get("products"):
        sys.exit(1)


if __name__ == "__main__":
    main()
