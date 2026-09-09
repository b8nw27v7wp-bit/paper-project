import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.core.config import get_settings

# 多级限流：Redis 优先，内存回退；key 归一 path(不含query) + user_id + IP
_store: dict[str, deque[float]] = defaultdict(deque)
LIMIT = 10
WINDOW = 60

# auth 防爆破独立阈值（/min）：与 plans 5/min 语义解耦，勿复用 plans 常量
AUTH_LOGIN_LIMIT = 10
AUTH_REGISTER_LIMIT = 5

# 惰性 Redis 客户端；不可达后按冷却间隔重试，避免一旦失败永久卡死内存回退
_redis_client = None
_redis_ok = None
_redis_retry_at = 0.0
_REDIS_RETRY_INTERVAL = 30.0


def _get_redis():
    global _redis_client, _redis_ok, _redis_retry_at
    now = time.time()
    if _redis_ok is True:
        return _redis_client
    if _redis_ok is False and now < _redis_retry_at:
        return None
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
        _redis_retry_at = now + _REDIS_RETRY_INTERVAL
        return None


# 固定窗口原子脚本：INCR + 首计数 EXPIRE，保证并发下窗口正确
_FIXED_WINDOW_LUA = """
local cnt = redis.call('INCR', KEYS[1])
if cnt == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return cnt
"""


def _normalize_path(path: str) -> str:
    # 去除尾斜杠，统一小写，QPS 归一
    p = path.rstrip("/") or "/"
    # 对 /plans/stream 带 query 的路径归一到 /plans/stream
    # request.url.path 本身不含 query，已归一
    return p.lower()


def check_rate_limit(request: Request, user_id: int = 1) -> None:
    import os

    # 显式开关关闭限流（测试用 monkeypatch.setenv("RATELIMIT_DISABLED","1")）
    if os.getenv("RATELIMIT_DISABLED") == "1":
        return
    settings = get_settings()
    # 先归一化 path 再判定阈值/组 key，避免大小写路径拿错桶（如 /API/v1/plans）
    path = _normalize_path(request.url.path)
    try:
        uid = int(user_id)  # type: ignore[arg-type]
    except Exception:
        uid = 0
    # 限流阈值可配置（默认 10/min），plan 相关更严（默认 5/min）
    limit = getattr(settings, "rate_limit_default", LIMIT) or LIMIT
    try:
        limit = int(limit)
    except Exception:
        limit = LIMIT
    if path.startswith("/api/v1/plans"):
        plan_limit = getattr(settings, "rate_limit_plan", 5)
        try:
            limit = int(plan_limit)
        except Exception:
            limit = 5
    # auth 防爆破：按归一化 path 精确匹配，阈值独立于 plans/default；
    # settings 覆盖可选（rate_limit_auth_* 未在 Settings 定义时回退模块常量，不改现有语义）
    if path == "/api/v1/auth/login":
        try:
            limit = int(getattr(settings, "rate_limit_auth_login", AUTH_LOGIN_LIMIT))
        except Exception:
            limit = AUTH_LOGIN_LIMIT
    elif path == "/api/v1/auth/register":
        try:
            limit = int(getattr(settings, "rate_limit_auth_register", AUTH_REGISTER_LIMIT))
        except Exception:
            limit = AUTH_REGISTER_LIMIT
    # key: user_id:ip:path（防 X-User-Id 伪造绕过）
    ip = request.client.host if request.client else "unknown"
    # 兼容代理头
    xf = request.headers.get("x-forwarded-for")
    if xf:
        ip = xf.split(",")[0].strip() or ip
    key = f"rate:{uid}:{ip}:{path}"
    # 优先 Redis（连接/初始化异常也静默回退内存，避免 500）
    try:
        r = _get_redis()
    except Exception:
        r = None
    if r is not None:
        try:
            # 固定窗口原子计数：Lua 脚本保证 INCR+EXPIRE 原子性
            try:
                cnt = r.eval(_FIXED_WINDOW_LUA, 1, key, WINDOW)
                cnt = int(cnt)
            except Exception:
                # Redis 不支持 EVAL（如 fakeredis）时回退 INCR+EXPIRE
                cnt = r.incr(key)
                if cnt == 1:
                    r.expire(key, WINDOW)
            if cnt > limit:
                raise HTTPException(status_code=429, detail={"code": 42901, "msg": f"限流 {limit}/min"}, headers={"Retry-After": str(WINDOW)})
            return
        except HTTPException:
            raise
        except Exception:
            # Redis 运行期异常：标记不可达走冷却重试，本次回退内存
            global _redis_ok, _redis_client
            _redis_ok = False
            _redis_client = None
            pass
    # 内存回退
    now = time.time()
    q = _store[key]
    while q and q[0] < now - WINDOW:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail={"code": 42901, "msg": f"限流 {limit}/min"}, headers={"Retry-After": str(WINDOW)})
    q.append(now)
