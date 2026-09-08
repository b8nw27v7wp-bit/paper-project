"""Workbench Redis cache helpers - cache:workbench/graph with TTL, memory fallback.

Implements:
- cache:workbench:{user_id}:{trace_id} (user-bound) 及 legacy cache:workbench:{trace_id}
- cache:graph:{user_id}:{trace_id} (user-bound) 及 legacy cache:graph:{trace_id}
Single-flight + graceful degrade if Redis unavailable (mirrors ratelimit.py pattern).

User binding（防枚举）: set_* 传入 user_id 时写入 user 绑定 key（envelope 携带 _owner），
get_* 传入 user_id 时仅读绑定 key 并比对 owner，不一致/缺失返回 None，不回退 legacy。
Legacy 调用（仅 trace_id，不传 user_id）读写 legacy key，保持 plans.py 等旧调用方兼容。
TTL 默认取 settings.cache_ttl（默认 300s），可显式覆盖。
内存回退保留 512 上限 + LRU 淘汰 + 懒惰过期清理。
"""
from __future__ import annotations

import json
import time
from typing import Any

# 内存回退
_mem: dict[str, tuple[float, str]] = {}
_TTL = 300  # 5m（兼容旧默认值；实际默认取 settings.cache_ttl）
_MEM_CAPACITY = 512

_redis_client = None
_redis_ok: bool | None = None
_redis_last_try: float = 0


def _default_ttl() -> int:
    try:
        from app.core.config import get_settings

        return int(get_settings().cache_ttl)
    except Exception:
        return _TTL


def _get_redis():
    global _redis_client, _redis_ok, _redis_last_try
    if _redis_ok is False:
        if time.time() - _redis_last_try < 30:
            return None
        _redis_ok = None
    if _redis_ok is not None:
        return _redis_client if _redis_ok else None
    try:
        import redis  # type: ignore

        from app.core.config import get_settings

        s = get_settings()
        client = redis.from_url(s.redis_url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5)
        client.ping()
        _redis_client = client
        _redis_ok = True
        _redis_last_try = time.time()
        return client
    except Exception:
        _redis_ok = False
        _redis_client = None
        _redis_last_try = time.time()
        return None


def _mem_set(key: str, value: str, ttl: int | None = None) -> None:
    if ttl is None:
        ttl = _default_ttl()
    try:
        ttl = int(ttl)
    except Exception:
        ttl = _default_ttl()
    # 已存在则先删，保证插入顺序=最近使用在尾部（LRU）
    if key in _mem:
        _mem.pop(key, None)
    _mem[key] = (time.time() + ttl, value)
    # 容量上限：先清过期，再 LRU 淘汰最久未用
    if len(_mem) > _MEM_CAPACITY:
        now = time.time()
        for k, (exp, _) in list(_mem.items()):
            if exp < now:
                _mem.pop(k, None)
        while len(_mem) > _MEM_CAPACITY:
            oldest = next(iter(_mem))
            if oldest == key:
                break
            _mem.pop(oldest, None)


def _mem_get(key: str) -> str | None:
    v = _mem.get(key)
    if not v:
        return None
    exp, data = v
    if exp < time.time():
        _mem.pop(key, None)
        return None
    # LRU：命中则移到尾部
    _mem.pop(key, None)
    _mem[key] = (exp, data)
    return data


def _wrap(owner: int, data: Any) -> str:
    return json.dumps({"_owner": int(owner), "_data": data}, ensure_ascii=False)


def _unwrap(raw: str, user_id: int | None = None) -> Any | None:
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    if isinstance(obj, dict) and "_data" in obj and "_owner" in obj:
        if user_id is not None:
            try:
                if int(obj["_owner"]) != int(user_id):
                    return None
            except Exception:
                return None
        return obj["_data"]
    # legacy 裸 payload：无 owner；传入 user_id 的严格读视为不可判归属 -> 拒绝
    if user_id is not None:
        return None
    return obj


# --- workbench cache ---

def workbench_key(trace_id: str, user_id: int | None = None) -> str:
    if user_id is not None:
        return f"cache:workbench:{int(user_id)}:{trace_id}"
    return f"cache:workbench:{trace_id}"


def graph_key(trace_id: str, user_id: int | None = None) -> str:
    if user_id is not None:
        return f"cache:graph:{int(user_id)}:{trace_id}"
    return f"cache:graph:{trace_id}"


def _resolve_ttl(ttl: int | None) -> int:
    if ttl is None:
        return _default_ttl()
    try:
        return int(ttl)
    except Exception:
        return _default_ttl()


def set_workbench(trace_id: str, events: list[dict[str, Any]], ttl: int | None = None, user_id: int | None = None) -> None:
    ttl_v = _resolve_ttl(ttl)
    key = workbench_key(trace_id, user_id)
    payload = _wrap(int(user_id), events) if user_id is not None else json.dumps(events, ensure_ascii=False)
    r = _get_redis()
    if r is not None:
        try:
            r.setex(key, ttl_v, payload)
            return
        except Exception:
            pass
    _mem_set(key, payload, ttl_v)


def get_workbench(trace_id: str, user_id: int | None = None) -> list[dict[str, Any]] | None:
    key = workbench_key(trace_id, user_id)
    r = _get_redis()
    raw: str | None = None
    if r is not None:
        try:
            raw = r.get(key)  # type: ignore
        except Exception:
            raw = None
    if raw is None:
        raw = _mem_get(key)
    if raw is None:
        return None
    data = _unwrap(raw, user_id)
    return data if isinstance(data, list) else None


def set_graph(trace_id: str, graph: dict[str, Any], ttl: int | None = None, user_id: int | None = None) -> None:
    ttl_v = _resolve_ttl(ttl)
    key = graph_key(trace_id, user_id)
    payload = _wrap(int(user_id), graph) if user_id is not None else json.dumps(graph, ensure_ascii=False)
    r = _get_redis()
    if r is not None:
        try:
            r.setex(key, ttl_v, payload)
            return
        except Exception:
            pass
    _mem_set(key, payload, ttl_v)


def get_graph(trace_id: str, user_id: int | None = None) -> dict[str, Any] | None:
    key = graph_key(trace_id, user_id)
    r = _get_redis()
    raw: str | None = None
    if r is not None:
        try:
            raw = r.get(key)  # type: ignore
        except Exception:
            raw = None
    if raw is None:
        raw = _mem_get(key)
    if raw is None:
        return None
    data = _unwrap(raw, user_id)
    return data if isinstance(data, dict) else None
