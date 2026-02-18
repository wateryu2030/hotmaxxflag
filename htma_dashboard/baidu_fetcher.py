#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞品价格检索 - 百度生态接入
支持：百度 API 商城、聚合数据商品比价
配置方式：环境变量 .env 或系统环境
"""
import os

# 加载 .env（若存在，从项目根目录）
try:
    from dotenv import load_dotenv
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(os.path.join(_root, ".env"))
except ImportError:
    pass
import urllib.request
import urllib.parse
import json
from typing import Optional

# ========== 配置（环境变量） ==========
# 百度 API 商城 apikey：https://apis.baidu.com/ 购买商品条码/商品搜索类 API 后获取
BAIDU_APISTORE_KEY = os.environ.get("BAIDU_APISTORE_KEY", "")
# 聚合数据 商品比价 apikey：https://www.juhe.cn/docs/api/id/137 申请
JUHE_PRICE_KEY = os.environ.get("JUHE_PRICE_KEY", "")
# 聚合数据接口地址（若与默认不同，可在控制台查看后覆盖）
JUHE_PRICE_URL = os.environ.get("JUHE_PRICE_URL", "http://apis.juhe.cn/shopping/query")
# 百度智能云 AK/SK：https://console.bce.baidu.com/iam/#/iam/accesslist 创建
BAIDU_AK = os.environ.get("BAIDU_AK", "")
BAIDU_SK = os.environ.get("BAIDU_SK", "")

# OneBound 万邦（淘宝/京东关键词搜索，返回真实价格，聚合数据维护中时的最佳替代）
# 申请：https://console.open.onebound.cn/console/ 注册开通
ONEBOUND_KEY = os.environ.get("ONEBOUND_KEY", "")
ONEBOUND_SECRET = os.environ.get("ONEBOUND_SECRET", "")
# 对标平台：jd=京东（默认）, taobao=淘宝
ONEBOUND_PLATFORM = (os.environ.get("ONEBOUND_PLATFORM", "jd") or "jd").lower()

# 拼多多 蚂蚁星球（免费，需申请 apikey）
# 申请：https://www.haojingke.com/open-api/pdd 注册后申请 apikey
PDD_HOJINGKE_APIKEY = os.environ.get("PDD_HOJINGKE_APIKEY", "")


def _http_get(url: str, headers: Optional[dict] = None, timeout: int = 10) -> Optional[dict]:
    """发起 GET 请求，返回 JSON"""
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _http_post(url: str, data: Optional[bytes] = None, headers: Optional[dict] = None, timeout: int = 10) -> Optional[dict]:
    """发起 POST 请求，返回 JSON"""
    try:
        h = dict(headers or {})
        if data and "Content-Type" not in h:
            h["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data or None, headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def juhe_price_fetcher(std_name: str) -> Optional[dict]:
    """
    聚合数据 商品比价 API
    文档：https://www.juhe.cn/docs/api/id/137
    申请：https://www.juhe.cn/ 注册 → 申请接口 → 实名认证
    注意：该接口曾显示「维护中」，申请前请确认已恢复。具体请求地址以聚合数据控制台为准。
    """
    if not JUHE_PRICE_KEY:
        return None
    keyword = std_name[:30] if std_name else ""
    if not keyword:
        return None
    url = JUHE_PRICE_URL
    params = urllib.parse.urlencode({"key": JUHE_PRICE_KEY, "q": keyword})
    data = _http_get(f"{url}?{params}", timeout=8)
    if not data or data.get("error_code") != 0:
        return None
    result = data.get("result", {})
    if isinstance(result, dict):
        # 解析返回结构，取最低价
        list_data = result.get("list") or result.get("data") or []
        if isinstance(list_data, list) and list_data:
            prices = []
            for item in list_data:
                if isinstance(item, dict):
                    p = item.get("price") or item.get("Price") or item.get("marketprice")
                    if p is not None:
                        try:
                            prices.append(float(p))
                        except (TypeError, ValueError):
                            pass
            if prices:
                return {
                    "min_price": min(prices),
                    "platform": "聚合数据",
                    "is_same_spec": True,
                }
    return None


def _onebound_search(platform: str, keyword: str) -> Optional[dict]:
    """OneBound 关键词搜索，platform=taobao|jd"""
    if not ONEBOUND_KEY or not ONEBOUND_SECRET:
        return None
    keyword = (keyword or "")[:25].strip()
    if not keyword:
        return None
    base = "https://api-gw.onebound.cn"
    url = f"{base}/{platform}/item_search/"
    params = urllib.parse.urlencode({
        "key": ONEBOUND_KEY,
        "secret": ONEBOUND_SECRET,
        "q": keyword,
        "page": "1",
        "page_size": "10",
    })
    data = _http_get(f"{url}?{params}", timeout=12)
    if not data or str(data.get("error_code", "")) != "0000":
        return None
    items_obj = data.get("items") or {}
    item_list = items_obj.get("item") if isinstance(items_obj, dict) else []
    if not isinstance(item_list, list) or not item_list:
        return None
    prices = []
    for it in item_list:
        if isinstance(it, dict):
            p = it.get("price") or it.get("promotion_price") or it.get("orginal_price")
            if p is not None:
                try:
                    prices.append(float(str(p).replace(",", "")))
                except (TypeError, ValueError):
                    pass
    if prices:
        plat_label = "京东" if platform == "jd" else "淘宝"
        return {
            "min_price": min(prices),
            "platform": f"{plat_label}/OneBound",
            "is_same_spec": True,
        }
    return None


def onebound_taobao_price_fetcher(std_name: str) -> Optional[dict]:
    """
    OneBound 万邦 - 淘宝关键词搜索，返回真实价格
    文档：https://open.onebound.cn/help/api/taobao.item_search.html
    """
    return _onebound_search("taobao", std_name)


def onebound_jd_price_fetcher(std_name: str) -> Optional[dict]:
    """
    OneBound 万邦 - 京东关键词搜索，返回真实价格
    文档：https://open.onebound.cn/help/api/jd.item_search.html
    """
    return _onebound_search("jd", std_name)


def onebound_price_fetcher(std_name: str) -> Optional[dict]:
    """OneBound 万邦 - 按 ONEBOUND_PLATFORM 选择淘宝或京东"""
    if ONEBOUND_PLATFORM == "taobao":
        return onebound_taobao_price_fetcher(std_name)
    return onebound_jd_price_fetcher(std_name)


def baidu_apistore_barcode_fetcher(std_name: str, barcode: Optional[str] = None) -> Optional[dict]:
    """
    百度 API 商城 - 极速数据 商品条码查询
    文档：在 https://apis.baidu.com/ 搜索「商品条码」购买后查看
    注意：条码查询主要返回商品信息，价格需看具体 API 是否提供；
    若无条码则用商品名关键词，部分 API 支持关键词搜索。
    """
    if not BAIDU_APISTORE_KEY:
        return None
    # 极速数据 商品条码查询 典型格式（以实际购买 API 文档为准）
    # 若有条码：用条码查；若无条码：部分 API 支持关键词，此处仅作占位
    if barcode:
        url = "https://api.jisuapi.com/barcode2/query"
        params = urllib.parse.urlencode({"appkey": BAIDU_APISTORE_KEY, "barcode": barcode})
    else:
        # 部分百度 API 商城商品搜索接口（以实际文档为准）
        url = "https://api.jisuapi.com/shopping/search"
        params = urllib.parse.urlencode({"appkey": BAIDU_APISTORE_KEY, "keyword": (std_name or "")[:20]})
    data = _http_get(f"{url}?{params}", timeout=8)
    if not data or data.get("status") != "0":
        return None
    result = data.get("result") or data.get("data") or {}
    price = result.get("price") or result.get("marketprice")
    if price is not None:
        try:
            return {
                "min_price": float(price),
                "platform": "百度API商城",
                "is_same_spec": True,
            }
        except (TypeError, ValueError):
            pass
    return None


def jd_haojingke_fetcher(std_name: str) -> Optional[dict]:
    """
    京东 蚂蚁星球 - 关键词搜索商品，返回最低价
    文档：https://www.haojingke.com/index/api
    需在开发者中心完成「京东联盟设置」
    """
    if not PDD_HOJINGKE_APIKEY:
        return None
    keyword = (std_name or "")[:30].strip()
    if not keyword:
        return None
    url = "http://api-gw.haojingke.com/index.php/api/index/myapi"
    params = urllib.parse.urlencode({
        "type": "goodslist",
        "apikey": PDD_HOJINGKE_APIKEY,
        "keyword": keyword,
        "page": "1",
        "pageSize": "10",
        "sort": "1",  # 1=券后价升序
        "sortby": "asc",
    })
    data = _http_get(f"{url}?{params}", timeout=12)
    if not data or data.get("status_code") != 200:
        return None
    items = data.get("data") or []
    if not isinstance(items, list):
        return None
    prices = []
    for it in items:
        if isinstance(it, dict):
            p = it.get("wlPrice_after") or it.get("wlPrice")
            if p is not None:
                try:
                    prices.append(float(str(p).replace(",", "")))
                except (TypeError, ValueError):
                    pass
    if prices:
        return {
            "min_price": min(prices),
            "platform": "京东/蚂蚁星球",
            "is_same_spec": True,
        }
    return None


def haojingke_unified_fetcher(std_name: str, source_type: int = 0) -> Optional[dict]:
    """
    蚂蚁星球 三合一 API - 京东、拼多多、蘑菇街 全网商品搜索
    文档：https://www.haojingke.com/index/openapi
    source_type: 0全部 1京东 2拼多多 3蘑菇街
    """
    if not PDD_HOJINGKE_APIKEY:
        return None
    keyword = (std_name or "")[:30].strip()
    if not keyword:
        return None
    url = "http://api-gw.haojingke.com/index.php/api/platform/openapi"
    params = {
        "type": "goodslist",
        "apikey": PDD_HOJINGKE_APIKEY,
        "keyword": keyword,
        "page": "1",
        "pagesize": "10",
        "sort": "1",
        "sortby": "asc",
        "iscoupon": "0",  # 0=查不到时调官方接口
    }
    if source_type > 0:
        params["source_type"] = str(source_type)
    qs = urllib.parse.urlencode(params)
    data = _http_get(f"{url}?{qs}", timeout=12)
    if not data or data.get("status_code") != 200:
        return None
    items = data.get("data") or []
    if not isinstance(items, list):
        return None
    prices = []
    platforms = set()
    plat_map = {"1": "京东", "2": "拼多多", "3": "蘑菇街"}
    for it in items:
        if isinstance(it, dict):
            p = it.get("wlPrice_after") or it.get("wlPrice")
            if p is not None:
                try:
                    prices.append(float(str(p).replace(",", "")))
                    st = str(it.get("source_type", ""))
                    if st in plat_map:
                        platforms.add(plat_map[st])
                except (TypeError, ValueError):
                    pass
    if prices:
        plat_label = "、".join(sorted(platforms)) or "蚂蚁星球"
        return {
            "min_price": min(prices),
            "platform": f"{plat_label}/蚂蚁星球",
            "is_same_spec": True,
        }
    return None


def pdd_haojingke_fetcher(std_name: str) -> Optional[dict]:
    """
    拼多多 蚂蚁星球 - 关键词搜索商品，返回最低价
    文档：https://www.haojingke.com/open-api/pdd
    申请：注册后申请 apikey，免费使用
    """
    if not PDD_HOJINGKE_APIKEY:
        return None
    keyword = (std_name or "")[:30].strip()
    if not keyword:
        return None
    url = "http://api-gw.haojingke.com/index.php/v1/api/pdd/goodslist"
    params = urllib.parse.urlencode({
        "apikey": PDD_HOJINGKE_APIKEY,
        "keyword": keyword,
        "page": "1",
        "page_size": "10",
        "sort_type": "3",  # 按价格升序
    })
    data = _http_get(f"{url}?{params}", timeout=10)
    if not data or data.get("status_code") != 200:
        return None
    goods = (data.get("data") or {}).get("goods_list") or []
    prices = []
    for g in goods:
        if isinstance(g, dict):
            p = g.get("price_after") or g.get("price_pg") or g.get("price")
            if p is not None:
                try:
                    prices.append(float(p))
                except (TypeError, ValueError):
                    pass
    if prices:
        return {
            "min_price": min(prices),
            "platform": "拼多多/蚂蚁星球",
            "is_same_spec": True,
        }
    return None


def baidu_fetcher(std_name: str, barcode: Optional[str] = None) -> Optional[dict]:
    """
    统一入口：按优先级尝试各数据源
    1. OneBound 万邦（淘宝/京东，需开通）
    2. 京东 蚂蚁星球（需在开发者中心完成京东联盟设置）
    3. 拼多多 蚂蚁星球（免费，需 PDD_HOJINGKE_APIKEY）
    4. 聚合数据 商品比价（曾维护中）
    5. 百度 API 商城
    """
    r = onebound_price_fetcher(std_name)
    if r:
        return r
    r = haojingke_unified_fetcher(std_name)
    if r:
        return r
    r = jd_haojingke_fetcher(std_name)
    if r:
        return r
    r = pdd_haojingke_fetcher(std_name)
    if r:
        return r
    r = juhe_price_fetcher(std_name)
    if r:
        return r
    r = baidu_apistore_barcode_fetcher(std_name, barcode)
    if r:
        return r
    return None


def get_configured_fetcher():
    """
    返回已配置的 fetcher，若无可用的则返回 None
    优先级：OneBound > 京东蚂蚁星球 > 拼多多蚂蚁星球 > 聚合数据 > 百度 API 商城
    """
    if ONEBOUND_KEY and ONEBOUND_SECRET:
        return onebound_price_fetcher
    if PDD_HOJINGKE_APIKEY:
        return baidu_fetcher
    if JUHE_PRICE_KEY:
        return juhe_price_fetcher
    if BAIDU_APISTORE_KEY:
        return lambda name: baidu_apistore_barcode_fetcher(name, None)
    return None


def onebound_test_ok() -> tuple[bool, str]:
    """
    预检 OneBound 是否可用。返回 (可用, 错误信息)。
    4013=Key已超量/未开通，需在控制台开通对应平台的 item_search 接口。
    """
    if not ONEBOUND_KEY or not ONEBOUND_SECRET:
        return False, "未配置 ONEBOUND_KEY/SECRET"
    platform = ONEBOUND_PLATFORM if ONEBOUND_PLATFORM in ("jd", "taobao") else "jd"
    url = f"https://api-gw.onebound.cn/{platform}/item_search/"
    params = urllib.parse.urlencode({
        "key": ONEBOUND_KEY,
        "secret": ONEBOUND_SECRET,
        "q": "测试",
        "page": "1",
        "page_size": "5",
    })
    data = _http_get(f"{url}?{params}", timeout=10)
    if not data:
        return False, "OneBound 请求失败"
    ec = str(data.get("error_code", ""))
    if ec == "0000":
        return True, ""
    reason = data.get("reason") or data.get("error") or f"error_code={ec}"
    return False, reason
