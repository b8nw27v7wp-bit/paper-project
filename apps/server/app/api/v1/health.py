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
    # P0: simple status, W3+ will add real PG/Redis/Neo4j pings with degraded handling
    services = {
        "api": "ok",
        "postgres": "unknown",  # TODO: asyncpg ping when DB wired
        "redis": "unknown",
        "neo4j": "unknown",
        "minio": "unknown",
    }
    return {
        "code": 200,
        "msg": "ok",
        "data": HealthData(
            status="ok",
            version="0.1.0",
            uptime_seconds=round(uptime, 2),
            services=services,
        ),
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
