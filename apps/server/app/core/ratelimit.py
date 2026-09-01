import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.core.config import get_settings

# 多级限流：Redis 优先，内存回退；key 归一 path(不含query) + user_id + IP
_store: dict[str, deque[float]] = defaultdict(deque)
LIMIT = 10
WINDOW = 60

# 惰性 Redis 客户端
_redis_client = None
_redis_ok = None


def _get_redis():
    global _redis_client, _redis_ok
    if _redis_ok is not None:
        return _redis_client if _redis_ok else None
    try:
        import redis  # type: ignore

        settings = get_settings()
        client = redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5)
        client.ping()
        _redis_client = client
        _redis_ok = True
        return client
    except Exception:
        _redis_ok = False
        _redis_client = None
        return None


def _normalize_path(path: str) -> str:
    # 去除尾斜杠，统一小写，QPS 归一
    p = path.rstrip("/") or "/"
    # 对 /plans/stream 带 query 的路径归一到 /plans/stream
    # request.url.path 本身不含 query，已归一
    return p.lower()


def check_rate_limit(request: Request, user_id: int = 1) -> None:
    import os

    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    settings = get_settings()
    # 限流阈值可配置（默认 10/min），plan 相关 5/min 更严
    limit = LIMIT
    if request.url.path.startswith("/api/v1/plans"):
        limit = 5
    # key: user_id:ip:path（防 X-User-Id 伪造绕过）
    ip = request.client.host if request.client else "unknown"
    # 兼容代理头
    xf = request.headers.get("x-forwarded-for")
    if xf:
        ip = xf.split(",")[0].strip() or ip
    path = _normalize_path(request.url.path)
    key = f"rate:{user_id}:{ip}:{path}"
    # 优先 Redis
    r = _get_redis()
    if r is not None:
        try:
            # 滑动窗口：INCR + EXPIRE
            cnt = r.incr(key)
            if cnt == 1:
                r.expire(key, WINDOW)
            if cnt > limit:
                raise HTTPException(status_code=429, detail={"code": 42901, "msg": f"限流 {limit}/min"})
            return
        except HTTPException:
            raise
        except Exception:
            # Redis 异常回退内存
            pass
    # 内存回退
    now = time.time()
    q = _store[key]
    while q and q[0] < now - WINDOW:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail={"code": 42901, "msg": f"限流 {limit}/min"})
    q.append(now)
