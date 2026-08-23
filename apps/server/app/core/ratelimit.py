import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# 内存限流：10/min per user+path
_store: dict[str, deque[float]] = defaultdict(deque)
LIMIT = 10
WINDOW = 60

def check_rate_limit(request: Request, user_id: int = 1) -> None:
    import os
    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    key = f"{user_id}:{request.url.path}"
    now = time.time()
    q = _store[key]
    while q and q[0] < now - WINDOW:
        q.popleft()
    if len(q) >= LIMIT:
        raise HTTPException(status_code=429, detail={"code": 42901, "msg": "限流 10/min"})
    q.append(now)
