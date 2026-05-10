# -*- coding: utf-8 -*-
"""
简单内存缓存：key -> (value, expire_at)，用于 date_range / kpi 等只读接口。
"""
import time

_api_cache = {}
_CACHE_TTL = 60  # 秒


def _cache_get(key):
    if key not in _api_cache:
        return None
    val, expire = _api_cache[key]
    if time.time() > expire:
        del _api_cache[key]
        return None
    return val


def _cache_set(key, value, ttl=None):
    _api_cache[key] = (value, time.time() + (ttl or _CACHE_TTL))


def _cache_clear(key=None):
    """清除缓存。若 key 为 None 则清除全部缓存。"""
    if key is None:
        _api_cache.clear()
    else:
        _api_cache.pop(key, None)
