#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
好特卖项目调用 OpenClaw 全局网关的百度比价工具（示例）。
使用前请在 .env 中配置 OPENCLAW_GATEWAY_URL 和 OPENCLAW_GATEWAY_TOKEN，或直接传参。

用法:
  python scripts/call_openclaw_baidu_price.py 洽洽坚果
  python scripts/call_openclaw_baidu_price.py "伊利宫酪奶皮子酸奶"
"""
import json
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))
except ImportError:
    pass

GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789").rstrip("/")
GATEWAY_TOKEN = os.environ.get(
    "OPENCLAW_GATEWAY_TOKEN",
    "b5d0ea99b2800962dba51d60cb60b766a3f516bda4c49877",
)


def get_price_comparison(query: str, timeout: int = 30) -> dict:
    import urllib.request
    req = urllib.request.Request(
        f"{GATEWAY_URL}/tools/invoke",
        data=json.dumps({"tool": "get_price_comparison", "args": {"query": query}}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {GATEWAY_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    if not out.get("ok"):
        return {"ok": False, "error": out.get("error", {})}
    return {"ok": True, "result": out.get("result", {})}


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else "洽洽坚果"
    if not query:
        print("用法: python scripts/call_openclaw_baidu_price.py <商品名>", file=sys.stderr)
        sys.exit(1)
    try:
        result = get_price_comparison(query)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("ok") else 1)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
