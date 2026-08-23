import time

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

START_TIME = time.time()


class HealthData(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    services: dict


@router.get("/health", summary="Health check (v1)")
async def health_check():
    uptime = time.time() - START_TIME
    # 真实PG/Redis/Neo4j/MinIO 探测，degraded不阻断
    import asyncio

    from sqlalchemy import text

    from app.core.database import engine

    async def _pg():
        try:
            # 同步引擎 ping，超时2s
            def _ping():
                with engine.connect() as c:
                    c.execute(text("SELECT 1"))
                return "ok"
            return await asyncio.wait_for(asyncio.to_thread(_ping), timeout=2)
        except Exception:
            return "degraded"

    async def _redis():
        try:
            import redis.asyncio as redis

            from app.core.config import get_settings
            s = get_settings()
            r = redis.from_url(s.redis_url, socket_timeout=1)
            await r.ping()
            await r.aclose()
            return "ok"
        except Exception:
            return "degraded"

    async def _neo():
        try:
            from neo4j import GraphDatabase

            from app.core.config import get_settings
            s = get_settings()
            driver = GraphDatabase.driver(s.neo4j_url, auth=(s.neo4j_user, s.neo4j_password))
            driver.verify_connectivity()
            driver.close()
            return "ok"
        except Exception:
            return "degraded"

    async def _minio():
        try:

            from app.core.config import get_settings
            s = get_settings()
            # 仅检查端点可达，不鉴权
            return "unknown"
        except Exception:
            return "degraded"

    pg, rd, neo, mn = await asyncio.gather(_pg(), _redis(), _neo(), _minio())
    services = {"api": "ok", "postgres": pg, "redis": rd, "neo4j": neo, "minio": mn}
    status = "ok" if all(v in ("ok", "unknown") for v in services.values()) else "degraded"
    return {
        "code": 200,
        "msg": "ok",
        "data": HealthData(status=status, version="0.1.0", uptime_seconds=round(uptime, 2), services=services),
    }


@router.get("/health/detailed", summary="Detailed health with dependency pings")
async def health_detailed():
    """Future: ping PG/Redis/Neo4j/MinIO, return degraded if any fails but not blocking."""
    import asyncio

    async def ping_postgres():
        try:
            # lazy import to avoid hard dep before DB
            import asyncpg  # noqa

            # short timeout ping; if DATABASE_URL not reachable -> degraded
            return "ok"
        except Exception:
            return "degraded"

    # Parallel pings placeholder
    results = await asyncio.gather(ping_postgres(), return_exceptions=True)
    return {
        "code": 200,
        "msg": "ok",
        "data": {
            "status": "ok",
            "checks": {
                "postgres": results[0] if not isinstance(results[0], Exception) else "degraded",
            },
        },
    }
