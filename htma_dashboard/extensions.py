# -*- coding: utf-8 -*-
"""
轻量 TTL 缓存（与 app._api_cache 思路一致，不依赖 flask-caching，避免 venv 多版本混用导致导入失败）。
接口：get(key) / set(key, value, timeout=秒)
"""
import os
import time

# /api/mobile 等视图用 Flask-Caching 时的 TTL（秒）。导入成功后会 clear，此处为「未触发导入」时的上限。
# 多 worker 时 clear 只影响当前进程，可设更小值或环境变量 HTMA_MOBILE_CACHE_SECONDS。
MOBILE_VIEW_CACHE_SECONDS = int(os.environ.get("HTMA_MOBILE_CACHE_SECONDS", "45"))


class SimpleTTLCache:
    __slots__ = ("_store", "default_timeout")

    def __init__(self, default_timeout=300):
        self._store = {}
        self.default_timeout = default_timeout

    def get(self, key):
        item = self._store.get(key)
        if not item:
            return None
        val, exp = item
        if time.time() > exp:
            try:
                del self._store[key]
            except KeyError:
                pass
            return None
        return val

    def set(self, key, value, timeout=None):
        ttl = timeout if timeout is not None else self.default_timeout
        self._store[key] = (value, time.time() + float(ttl))


cache = SimpleTTLCache(default_timeout=300)

# Flask-Caching（供 /api/mobile 部分路由 query_string 缓存，TTL 与 SimpleTTL 可并存）
try:
    from flask_caching import Cache

    flask_cache = Cache()
except Exception:  # pragma: no cover
    flask_cache = None


def init_flask_caching(app):
    if flask_cache is None:
        return
    app.config.setdefault("CACHE_TYPE", "SimpleCache")
    app.config.setdefault("CACHE_DEFAULT_TIMEOUT", MOBILE_VIEW_CACHE_SECONDS)
    flask_cache.init_app(
        app,
        config={
            "CACHE_TYPE": "SimpleCache",
            "DEFAULT_TIMEOUT": MOBILE_VIEW_CACHE_SECONDS,
        },
    )


def mobile_cached(f):
    """mobile 专用缓存装饰器，未装 flask_caching 时原样通过。"""
    if flask_cache is None:
        return f
    return flask_cache.cached(timeout=MOBILE_VIEW_CACHE_SECONDS, query_string=True)(f)


def invalidate_mobile_cache():
    """数据导入/刷新后调用，清空 Flask-Caching，使小程序等客户端立刻读到新聚合结果。"""
    if flask_cache is None:
        return
    try:
        flask_cache.clear()
    except Exception:
        pass

