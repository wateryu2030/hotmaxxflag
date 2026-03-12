# -*- coding: utf-8 -*-
"""
百度优选 Skill 调用封装：跨平台比价（淘宝/京东/唯品会等）。
优先通过 OpenClaw 网关 HTTP API 调用（npm 版 clawhub 无 run 子命令）；可选 .env OPENCLAW_GATEWAY_URL、OPENCLAW_GATEWAY_TOKEN。
支持精确匹配 + 模糊匹配回退（精确无结果时从搜索列表中选最相似商品比价）。
"""
import difflib
import json
import os
import subprocess
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List, Tuple

# OpenClaw 仪表盘安装的 Skill 为 baidu-preferred（clawhub 上已无该 skill，见 docs/百度Skill优先-无clawhub方案.md）
BAIDU_SKILL_SLUG = os.environ.get("BAIDU_SKILL_SLUG", "baidu-preferred")
GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789").rstrip("/")
# 百度 Skill 专用网关：配置后优先请求该网关（如手机/其他端已可用的 OpenClaw），不再依赖 clawhub install
BAIDU_SKILL_GATEWAY_URL = (os.environ.get("OPENCLAW_BAIDU_SKILL_GATEWAY_URL") or "").strip().rstrip("/")
BAIDU_SKILL_GATEWAY_TOKEN = (os.environ.get("OPENCLAW_BAIDU_SKILL_GATEWAY_TOKEN") or os.environ.get("OPENCLAW_GATEWAY_TOKEN") or "").strip()
# 精确无结果时是否启用模糊搜索（从搜索列表中选最相似商品比价），默认 True
BAIDU_SKILL_FUZZY_MATCH = os.environ.get("BAIDU_SKILL_FUZZY_MATCH", "true").strip().lower() in ("1", "true", "yes")
# 模糊匹配相似度阈值，低于该值视为无匹配；默认 0.35 更模糊以尽量命中百度 Skill
BAIDU_SKILL_FUZZY_THRESHOLD = float(os.environ.get("BAIDU_SKILL_FUZZY_THRESHOLD", "0.35"))


def _get_gateway_token() -> str:
    """优先使用环境变量，否则从 ~/.openclaw/openclaw.json 读取 gateway.auth.token"""
    t = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "").strip()
    if t:
        return t
    try:
        path = os.path.expanduser("~/.openclaw/openclaw.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return ((cfg.get("gateway") or {}).get("auth") or {}).get("token") or "123456"
    except Exception:
        pass
    return "123456"


GATEWAY_TOKEN = _get_gateway_token()


def _call_baidu_skill_via_baidu_gateway(query: str, timeout: int) -> Dict[str, Any]:
    """若配置了 OPENCLAW_BAIDU_SKILL_GATEWAY_URL，优先请求该网关（百度 Skill 专用）。"""
    if not BAIDU_SKILL_GATEWAY_URL or not query.strip():
        return {"status": "error", "message": ""}
    url = BAIDU_SKILL_GATEWAY_URL.rstrip("/")
    token = BAIDU_SKILL_GATEWAY_TOKEN or "123456"
    for tool_name in ("get_price_comparison", "search_products"):
        for payload in (
            {"tool": tool_name, "action": "json", "args": {"query": query.strip()}},
            {"tool": tool_name, "params": {"query": query.strip()}},
        ):
            try:
                body = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"{url}/tools/invoke",
                    data=body,
                    method="POST",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    out = json.loads(r.read().decode())
                if not out.get("ok"):
                    err = out.get("error", {})
                    if err.get("type") == "not_found":
                        break
                    return {"status": "error", "message": (err.get("message") or str(out))[:500]}
                result = out.get("result")
                if isinstance(result, dict) and (result.get("data") or result.get("jd") or result.get("taobao")):
                    return {"status": "success", "data": result.get("data") or result}
                if isinstance(result, dict) and result:
                    return {"status": "success", "data": result}
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break
                return {"status": "error", "message": f"HTTP {e.code}: {e.reason}"[:500]}
            except urllib.error.URLError as e:
                return {"status": "error", "message": f"百度 Skill 网关不可达: {e.reason}"[:500]}
            except (json.JSONDecodeError, Exception) as e:
                continue
    return {"status": "error", "message": "百度 Skill 网关未返回可解析比价"}


def _call_baidu_skill_via_gateway(query: str, timeout: int) -> Dict[str, Any]:
    """通过网关 POST /tools/invoke 调用比价（tool 名尝试 get_price_comparison / search_products）。"""
    for tool_name in ("get_price_comparison", "search_products"):
        for payload in (
            {"tool": tool_name, "action": "json", "args": {"query": query}},
            {"tool": tool_name, "params": {"query": query}},
        ):
            try:
                body = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"{GATEWAY_URL}/tools/invoke",
                    data=body,
                    method="POST",
                    headers={
                        "Authorization": f"Bearer {GATEWAY_TOKEN}",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    out = json.loads(r.read().decode())
                if not out.get("ok"):
                    err = out.get("error", {})
                    if err.get("type") == "not_found":
                        break  # 换下一个 tool
                    return {"status": "error", "message": (err.get("message") or str(out))[:500]}
                result = out.get("result")
                if isinstance(result, dict) and (result.get("data") or result.get("jd") or result.get("taobao")):
                    data = result.get("data") or result
                    return {"status": "success", "data": data}
                if isinstance(result, dict):
                    return {"status": "success", "data": result}
                return {"status": "error", "message": "网关返回格式无法解析"}
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break
                return {"status": "error", "message": f"HTTP {e.code}: {e.reason}"[:500]}
            except urllib.error.URLError as e:
                return {"status": "error", "message": f"网关不可达: {e.reason}"[:500]}
            except (json.JSONDecodeError, Exception) as e:
                if tool_name == "search_products" and payload.get("params"):
                    return {"status": "error", "message": str(e)[:500]}
                continue
    return {"status": "error", "message": "网关未找到可用比价 tool（get_price_comparison/search_products）"}


def _project_root() -> str:
    """项目根目录（与 openclaw_baidu_tools_runner 一致）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _call_runner_subprocess(query: str, timeout: int = 30) -> Dict[str, Any]:
    """
    与 ClawHub/Chat 同路径：直接执行 scripts/openclaw_baidu_tools_runner.py get_price_comparison，
    即网关 baidu-price-tools 插件调用的同一脚本，不依赖网关是否暴露 tool。
    """
    query = (query or "").strip()
    if not query:
        return {"status": "error", "message": "query 为空"}
    root = _project_root()
    runner = os.path.join(root, "scripts", "openclaw_baidu_tools_runner.py")
    if not os.path.isfile(runner):
        return {"status": "error", "message": f"未找到 runner 脚本: {runner}"}
    try:
        import sys as _sys
        result = subprocess.run(
            [_sys.executable or "python3", runner, "get_price_comparison", query],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=root,
            env=dict(os.environ),
        )
        out = (result.stdout or "").strip()
        for line in reversed(out.split("\n")):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict) and data.get("data"):
                    out = {
                        "status": "success",
                        "data": data["data"],
                        "match_type": "baidu_skill_runner",
                        "original_query": query,
                    }
                    if data.get("source"):
                        out["price_source"] = data["source"]
                    return out
                if data.get("error") and not data.get("data"):
                    return {"status": "error", "message": (data.get("error") or "runner 无价格数据")[:500]}
            except json.JSONDecodeError:
                continue
        return {"status": "error", "message": (result.stderr or out or "runner 无有效输出")[:500]}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "百度 Skill runner 调用超时"}
    except Exception as e:
        return {"status": "error", "message": str(e)[:500]}


def _call_local_fetchers(query: str) -> Dict[str, Any]:
    """
    网关不可用时，直接使用项目内多数据源（与 openclaw_baidu_tools_runner 一致）：
    百度优选 MCP、OneBound 京东/淘宝、聚合数据、蚂蚁星球 京东/拼多多。
    返回与 _call_baidu_skill_via_gateway 一致的格式，便于 call_baidu_skill 复用。
    """
    query = (query or "").strip()
    if not query:
        return {"status": "error", "message": "query 为空"}
    try:
        from htma_dashboard import baidu_fetcher
    except ImportError:
        try:
            import baidu_fetcher  # noqa: F401
        except ImportError:
            return {"status": "error", "message": "未找到 baidu_fetcher"}
    data: Dict[str, Any] = {}
    # 1) 百度优选 MCP（BAIDU_YOUXUAN_TOKEN）
    youxuan = getattr(baidu_fetcher, "baidu_youxuan_price_fetcher", None)
    if youxuan:
        r = youxuan(query)
        if r and r.get("min_price") is not None:
            data["百度优选"] = {"price": r["min_price"]}
    # 2) OneBound 京东/淘宝
    jd_f = getattr(baidu_fetcher, "onebound_jd_price_fetcher", None)
    if jd_f:
        r = jd_f(query)
        if r and r.get("min_price") is not None:
            data["京东"] = data.get("京东") or {"price": r["min_price"]}
    tb_f = getattr(baidu_fetcher, "onebound_taobao_price_fetcher", None)
    if tb_f:
        r = tb_f(query)
        if r and r.get("min_price") is not None:
            data["淘宝"] = data.get("淘宝") or {"price": r["min_price"]}
    # 3) 聚合数据
    juhe = getattr(baidu_fetcher, "juhe_price_fetcher", None)
    if juhe:
        r = juhe(query)
        if r and r.get("min_price") is not None:
            data["聚合数据"] = {"price": r["min_price"]}
    # 4) 蚂蚁星球 京东/拼多多
    jd_hj = getattr(baidu_fetcher, "jd_haojingke_fetcher", None)
    if jd_hj and "京东" not in data:
        r = jd_hj(query)
        if r and r.get("min_price") is not None:
            data["京东"] = data.get("京东") or {"price": r["min_price"]}
    pdd_hj = getattr(baidu_fetcher, "pdd_haojingke_fetcher", None)
    if pdd_hj:
        r = pdd_hj(query)
        if r and r.get("min_price") is not None:
            data["拼多多"] = {"price": r["min_price"]}
    if not data:
        return {"status": "error", "message": "本地多数据源均无价格（可配置 BAIDU_YOUXUAN_TOKEN/ONEBOUND_KEY/JUHE_PRICE_KEY/PDD_HOJINGKE_APIKEY）"}
    return {"status": "success", "data": data, "match_type": "local_fetchers", "original_query": query}


def _call_search_products_raw(keyword: str, timeout: int = 15) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    调用网关 search_products，返回 (商品列表, 错误信息)。
    列表项可为 {"title": "", "price": ..., "platform": ...} 或兼容结构。
    """
    try:
        body = json.dumps({"tool": "search_products", "action": "json", "args": {"query": keyword}}).encode("utf-8")
        req = urllib.request.Request(
            f"{GATEWAY_URL}/tools/invoke",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {GATEWAY_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode())
        if not out.get("ok"):
            err = out.get("error", {})
            return None, (err.get("message") or str(out))[:300]
        result = out.get("result")
        if isinstance(result, list) and len(result) > 0:
            return result, None
        if isinstance(result, dict):
            products = result.get("products") or result.get("data") or result.get("items")
            if isinstance(products, list) and len(products) > 0:
                return products, None
        return None, "搜索返回无列表"
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return None, f"网关不可达: {e.reason}"
    except (json.JSONDecodeError, Exception) as e:
        return None, str(e)[:300]


def _extract_price_from_product(prod: Dict[str, Any]) -> Optional[float]:
    """从搜索返回的单条商品中提取价格（兼容多种字段名）。"""
    for key in ("price", "min_price", "low_price", "jd_price", "taobao_price"):
        v = prod.get(key)
        if v is not None:
            try:
                p = float(v)
                if p > 0:
                    return p
            except (TypeError, ValueError):
                continue
    # 嵌套结构
    for platform in ("jd", "京东", "taobao", "淘宝", "vip", "唯品会"):
        info = prod.get(platform)
        if isinstance(info, dict) and info.get("price") is not None:
            try:
                p = float(info["price"])
                if p > 0:
                    return p
            except (TypeError, ValueError):
                continue
    return None


def fuzzy_search_product(
    product_name: str,
    threshold: Optional[float] = None,
    timeout: int = 15,
) -> Optional[Dict[str, Any]]:
    """
    调用百度 Skill 的 search_products，从结果中选与 product_name 最相似的商品。
    :param product_name: 原始商品名称
    :param threshold: 相似度阈值，低于该值视为无匹配；默认用 BAIDU_SKILL_FUZZY_THRESHOLD
    :param timeout: 请求超时秒数
    :return: 最相似商品信息（含 title、price、platform、match_score 等），若无则返回 None
    """
    if not (product_name or "").strip():
        return None
    th = threshold if threshold is not None else BAIDU_SKILL_FUZZY_THRESHOLD
    products, err = _call_search_products_raw((product_name or "").strip(), timeout=timeout)
    if err or not products:
        return None
    best_match: Optional[Dict[str, Any]] = None
    best_score = 0.0
    query_norm = (product_name or "").strip()
    for prod in products:
        title = (prod.get("title") or prod.get("name") or prod.get("product_name") or "").strip()
        if not title:
            continue
        score = difflib.SequenceMatcher(None, query_norm, title).ratio()
        if score > best_score:
            best_score = score
            best_match = prod
    if best_match is None or best_score < th:
        return None
    price = _extract_price_from_product(best_match)
    title = best_match.get("title") or best_match.get("name") or best_match.get("product_name") or ""
    return {
        "title": title,
        "price": price,
        "platform": best_match.get("platform") or "百度优选",
        "match_score": round(best_score, 4),
        "match_type": "fuzzy",
        "original_query": product_name,
    }


def call_baidu_skill(
    product_name: str,
    brand: Optional[str] = None,
    max_price: Optional[float] = None,
    timeout: int = 30,
    enable_fuzzy: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    调用百度优选 Skill 进行跨平台比价。优先走网关 HTTP，其次 clawhub run（若存在）。
    支持精确无结果时模糊回退（enable_fuzzy 默认同 BAIDU_SKILL_FUZZY_MATCH）。
    返回示例：{"status": "success", "data": {...}, "match_type": "exact"|"fuzzy", "original_query": "..."}
    """
    use_fuzzy = enable_fuzzy if enable_fuzzy is not None else BAIDU_SKILL_FUZZY_MATCH
    query = product_name or ""
    if brand:
        query = f"{brand} {query}".strip()
    if max_price is not None and max_price > 0:
        query = f"{query}，价格不超过{int(max_price)}元"
    if not query.strip():
        return {"status": "error", "message": "商品名不能为空"}

    # 0) 若配置了百度 Skill 专用网关（如手机/其他端已可用的 OpenClaw），优先请求该网关
    if BAIDU_SKILL_GATEWAY_URL:
        res = _call_baidu_skill_via_baidu_gateway(query, timeout)
        if res.get("status") == "success" and res.get("data"):
            res["match_type"] = "exact"
            res["original_query"] = query
            return res

    # 1) 精确查询：本机网关 HTTP（与 Chat 同源，需网关加载 baidu-price-tools 且配置 projectRoot）
    res = _call_baidu_skill_via_gateway(query, timeout)
    if res.get("status") == "success" and res.get("data"):
        res["match_type"] = "exact"
        res["original_query"] = query
        return res
    err_msg = res.get("message", "")

    # 2) 网关不可用时：直接跑与 Chat 相同的 runner（scripts/openclaw_baidu_tools_runner.py），确保百度 Skill 调通
    res_runner = _call_runner_subprocess(query, timeout=min(timeout, 35))
    if res_runner.get("status") == "success" and res_runner.get("data"):
        res_runner["match_type"] = res_runner.get("match_type") or "baidu_skill_runner"
        res_runner["original_query"] = res_runner.get("original_query") or query
        return res_runner

    # 3) 模糊回退：搜索列表选最相似再取价（仍走网关 search_products）
    if use_fuzzy:
        fuzzy_prod = fuzzy_search_product(query, timeout=min(timeout, 15))
        if fuzzy_prod and fuzzy_prod.get("price") is not None:
            plat = (fuzzy_prod.get("platform") or "百度优选").strip()
            plat_key = "京东" if "京东" in plat or plat.lower() == "jd" else "淘宝" if "淘宝" in plat or plat.lower() == "taobao" else "唯品会" if "唯品" in plat else "百度优选"
            return {
                "status": "success",
                "data": {plat_key: {"price": fuzzy_prod["price"]}},
                "match_type": "fuzzy",
                "original_query": fuzzy_prod.get("original_query") or query,
            }
        if fuzzy_prod and fuzzy_prod.get("title"):
            if BAIDU_SKILL_GATEWAY_URL:
                res2 = _call_baidu_skill_via_baidu_gateway(fuzzy_prod["title"], timeout=min(timeout, 15))
                if res2.get("status") == "success" and res2.get("data"):
                    res2["match_type"] = "fuzzy"
                    res2["original_query"] = fuzzy_prod.get("original_query") or query
                    return res2
            res2 = _call_baidu_skill_via_gateway(fuzzy_prod["title"], timeout=min(timeout, 15))
            if res2.get("status") == "success" and res2.get("data"):
                res2["match_type"] = "fuzzy"
                res2["original_query"] = fuzzy_prod.get("original_query") or query
                return res2
            res2 = _call_runner_subprocess(fuzzy_prod["title"], timeout=min(timeout, 20))
            if res2.get("status") == "success" and res2.get("data"):
                res2["match_type"] = "fuzzy"
                res2["original_query"] = fuzzy_prod.get("original_query") or query
                return res2

    # 4) 回退：clawhub run（完整 OpenClaw 安装时可能有）
    try:
        result = subprocess.run(
            ["clawhub", "run", BAIDU_SKILL_SLUG, "--query", query],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=None,
        )
        if result.returncode == 0 and result.stdout:
            out = json.loads(result.stdout)
            if out.get("status") == "success":
                out["match_type"] = out.get("match_type") or "exact"
                out["original_query"] = out.get("original_query") or query
                return out
    except FileNotFoundError:
        pass  # 继续尝试本地多数据源
    except subprocess.TimeoutExpired:
        pass
    except json.JSONDecodeError:
        pass
    except Exception:
        pass

    # 仅用百度 Skill，不再回退到其它数据源
    return {"status": "error", "message": err_msg or "百度 Skill（网关/runner）未返回价格，请确认网关已加载 baidu-price-tools 且 projectRoot 已配置，或本机可执行 clawhub run（见 docs/百度Skill比价环境说明.md）"}


def batch_compare_products(
    product_list: List[Dict[str, Any]],
    delay_seconds: float = 1.0,
) -> Dict[str, Dict[str, Any]]:
    """
    批量比价。
    product_list: [{"sku_code": "xxx", "product_name": "xxx", "brand": "xxx"}, ...]
    返回: { sku_code: skill_result, ... }
    """
    import time
    results = {}
    for item in product_list:
        sku = item.get("sku_code") or ""
        name = item.get("product_name") or item.get("product_name") or ""
        if not name:
            results[sku] = {"status": "error", "message": "品名为空"}
            continue
        results[sku] = call_baidu_skill(
            name,
            brand=item.get("brand"),
            max_price=item.get("max_price"),
        )
        if delay_seconds > 0:
            time.sleep(delay_seconds)
    return results


def baidu_skill_item_fetcher(
    item: dict,
    enable_fuzzy: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """
    供货盘比价 pipeline 使用的 fetcher：接收 stage1 的 item，调用百度 Skill，返回与 baidu_fetcher 一致的格式。
    支持模糊匹配（enable_fuzzy 默认同 BAIDU_SKILL_FUZZY_MATCH）。
    返回: { min_price, platform, jd_min_price, ..., match_type, original_query } 或 None
    """
    if not item or not isinstance(item, dict):
        return None
    product_name = (item.get("raw_name") or item.get("std_name") or "").strip()
    if not product_name or len(product_name) < 2:
        return None
    brand = (item.get("brand_name") or "").strip() or None
    max_price = item.get("unit_price")
    if max_price is not None:
        try:
            max_price = float(max_price)
        except (TypeError, ValueError):
            max_price = None
    res = call_baidu_skill(product_name, brand=brand, max_price=max_price, enable_fuzzy=enable_fuzzy)
    if res.get("status") != "success" or not res.get("data"):
        return None
    data = res["data"]
    jd_price = None
    tb_price = None
    vip_price = None
    other_prices: List[Tuple[float, str]] = []  # 百度优选/拼多多/聚合数据等
    for platform, info in (data or {}).items():
        if not isinstance(info, dict):
            continue
        p = info.get("price")
        if p is not None:
            try:
                p = float(p)
            except (TypeError, ValueError):
                continue
            if p <= 0:
                continue
            platform_lower = (platform or "").strip().lower()
            plat_label = (platform or "").strip() or "其他"
            if platform_lower in ("jd", "京东"):
                jd_price = p
            elif platform_lower in ("taobao", "淘宝"):
                tb_price = p
            elif platform_lower in ("vip", "vipcom", "唯品会"):
                vip_price = p
            else:
                other_prices.append((p, plat_label))
    prices = [(p, "京东") for p in (jd_price,) if p is not None]
    prices += [(p, "淘宝") for p in (tb_price,) if p is not None]
    prices += [(p, "唯品会") for p in (vip_price,) if p is not None]
    prices += other_prices
    if not prices:
        return None
    best_price, best_platform = min(prices, key=lambda x: x[0])
    jd_min = jd_price
    tb_min = tb_price
    platforms = []
    if jd_min is not None:
        platforms.append(f"京东:{jd_min:.1f}")
    if tb_min is not None:
        platforms.append(f"淘宝:{tb_min:.1f}")
    if vip_price is not None:
        platforms.append(f"唯品会:{vip_price:.1f}")
    for p, label in other_prices:
        platforms.append(f"{label}:{p:.1f}")
    out = {
        "min_price": best_price,
        "platform": "、".join(platforms),
        "jd_min_price": jd_min,
        "jd_platform": "京东" if jd_min is not None else None,
        "taobao_min_price": tb_min,
        "taobao_platform": "淘宝" if tb_min is not None else None,
        "is_same_spec": True,
    }
    if res.get("match_type"):
        out["match_type"] = res["match_type"]
    if res.get("original_query"):
        out["original_query"] = res["original_query"]
    if res.get("price_source"):
        out["price_source"] = res["price_source"]
    return out
