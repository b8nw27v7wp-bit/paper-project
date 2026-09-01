"""Workbench Redis cache helpers - cache:workbench/graph with 5m TTL, memory fallback.

Implements:
- cache:workbench:{trace_id} -> JSON list of SSE events (8事件, 带id/retry重放)
- cache:graph:{trace_id} -> JSON {nodes,edges,status}
Single-flight + graceful degrade if Redis unavailable (mirrors ratelimit.py pattern).
"""
from __future__ import annotations

import json
import time
from typing import Any

# 内存回退（TTL 5m）
_mem: dict[str, tuple[float, str]] = {}
_TTL = 300  # 5m

_redis_client = None
_redis_ok: bool | None = None
_redis_last_try: float = 0


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


def _mem_set(key: str, value: str, ttl: int = _TTL) -> None:
    _mem[key] = (time.time() + ttl, value)
    # 清理过期（懒惰）
    if len(_mem) > 512:
        now = time.time()
        for k, (exp, _) in list(_mem.items()):
            if exp < now:
                _mem.pop(k, None)


def _mem_get(key: str) -> str | None:
    v = _mem.get(key)
    if not v:
        return None
    exp, data = v
    if exp < time.time():
        _mem.pop(key, None)
        return None
    return data


# --- workbench cache ---

def workbench_key(trace_id: str) -> str:
    return f"cache:workbench:{trace_id}"


def graph_key(trace_id: str) -> str:
    return f"cache:graph:{trace_id}"


def set_workbench(trace_id: str, events: list[dict[str, Any]], ttl: int = _TTL) -> None:
    key = workbench_key(trace_id)
    payload = json.dumps(events, ensure_ascii=False)
    r = _get_redis()
    if r is not None:
        try:
            r.setex(key, ttl, payload)
            return
        except Exception:
            pass
    _mem_set(key, payload, ttl)


def get_workbench(trace_id: str) -> list[dict[str, Any]] | None:
    key = workbench_key(trace_id)
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
    try:
        return json.loads(raw)
    except Exception:
        return None


def set_graph(trace_id: str, graph: dict[str, Any], ttl: int = _TTL) -> None:
    key = graph_key(trace_id)
    payload = json.dumps(graph, ensure_ascii=False)
    r = _get_redis()
    if r is not None:
        try:
            r.setex(key, ttl, payload)
            return
        except Exception:
            pass
    _mem_set(key, payload, ttl)


def get_graph(trace_id: str) -> dict[str, Any] | None:
    key = graph_key(trace_id)
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
    try:
        return json.loads(raw)
    except Exception:
        return None
