"""P3 性能优化：懒加载 / 缓存 / 指标（W24）"""
import time
import functools
from typing import Any, Callable
from collections import OrderedDict

# 进程内 LRU 缓存（优于 Redis 本地热缓存，命中 <5ms）
class LRUCache:
    def __init__(self, capacity: int = 256):
        self.capacity = capacity
        self.store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        if key not in self.store:
            self.misses += 1
            return None
        val, exp = self.store.pop(key)
        if exp and time.time() > exp:
            self.misses += 1
            return None
        self.store[key] = (val, exp)
        self.hits += 1
        return val

    def set(self, key: str, value: Any, ttl: int = 60) -> None:
        exp = time.time() + ttl if ttl else 0
        if key in self.store:
            self.store.pop(key)
        elif len(self.store) >= self.capacity:
            self.store.popitem(last=False)
        self.store[key] = (value, exp)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"hits": self.hits, "misses": self.misses, "hit_rate": round(self.hits/total, 3) if total else 0, "size": len(self.store)}


_global_cache = LRUCache(512)
_metrics: dict[str, list[float]] = {}


def cached(ttl: int = 30, key_prefix: str = "") -> Callable:
    """函数级缓存装饰器：懒加载 + TTL，适用于 stats/overview 等读多写少接口"""
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            k = f"{key_prefix}:{fn.__name__}:{args}:{sorted(kwargs.items())}"
            hit = _global_cache.get(k)
            if hit is not None:
                return hit
            res = fn(*args, **kwargs)
            _global_cache.set(k, res, ttl)
            return res
        return wrapped
    return deco


def timed(metric_name: str) -> Callable:
    """性能指标打点：P95/均值统计，供 /health + 大屏展示"""
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                dt = (time.perf_counter() - t0) * 1000
                lst = _metrics.setdefault(metric_name, [])
                lst.append(dt)
                if len(lst) > 200:
                    lst[:] = lst[-200:]
        return wrapped
    return deco


def get_metrics() -> dict:
    out: dict[str, Any] = {}
    for name, lst in _metrics.items():
        if not lst:
            continue
        s = sorted(lst)
        out[name] = {
            "count": len(s),
            "avg_ms": round(sum(s)/len(s), 2),
            "p50_ms": round(s[len(s)//2], 2),
            "p95_ms": round(s[int(len(s)*0.95) if len(s)>20 else -1], 2),
            "max_ms": round(s[-1], 2),
        }
    out["cache"] = _global_cache.stats()
    return out


# 懒加载 helpers：重型模块按需 import，避免冷启动 >2s
_lazy_loaded: set[str] = set()

def lazy_import(name: str, import_path: str) -> Any:
    """懒加载代理：首次调用时 import，后续复用"""
    cache_key = f"lazy:{name}"
    hit = _global_cache.get(cache_key)
    if hit is not None:
        return hit
    # 延迟导入
    import importlib
    mod = importlib.import_module(import_path)
    _global_cache.set(cache_key, mod, ttl=300)
    _lazy_loaded.add(name)
    return mod


def performance_headers(start: float) -> dict:
    dt = (time.perf_counter() - start) * 1000
    return {"X-Response-Time": f"{dt:.1f}ms", "X-Cache": "hit" if dt < 5 else "miss"}


# 供路由注入的中间件式辅助
def apply_performance(response, start: float) -> None:
    try:
        for k, v in performance_headers(start).items():
            response.headers[k] = v
    except Exception:
        pass
