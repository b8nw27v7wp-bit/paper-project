import time

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

START_TIME = time.time()

# SSE 事件口径（plans.py 不动，此处书面确认现状，不改行为）：
# POST /plans 多轨共 9 种 SSE 事件：thought / tool_call_start / tool_call /
# tool_call_end / task_created / critic_feedback / mentor_msg / reflector_patch / done。
# 其中 executor 节点无专属事件类型（plans.py _astream_run 中 executor 分支 pass，
# 落库仍写 6 条 agent_run_log 含 executor，事件数与旧契约一致），此处仅注释确认。


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
        # 真探：boto3 s3 list_buckets 超时2s；boto3 未装时回退 minio SDK；失败 degraded 不阻断
        try:
            from app.core.config import get_settings
            s = get_settings()
            endpoint = s.minio_endpoint
            secure = bool(s.minio_secure)

            def _probe():
                try:
                    import boto3  # type: ignore
                    from botocore.config import Config  # type: ignore

                    url = endpoint if endpoint.startswith("http") else (f"https://{endpoint}" if secure else f"http://{endpoint}")
                    cli = boto3.client(
                        "s3",
                        endpoint_url=url,
                        aws_access_key_id=s.minio_access_key,
                        aws_secret_access_key=s.minio_secret_key,
                        config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 0}),
                    )
                    cli.list_buckets()
                    return "ok"
                except ImportError:
                    pass  # boto3 未装，回退 minio SDK
                from minio import Minio

                cli = Minio(endpoint, access_key=s.minio_access_key, secret_key=s.minio_secret_key, secure=secure)
                list(cli.list_buckets())
                return "ok"

            return await asyncio.wait_for(asyncio.to_thread(_probe), timeout=2)
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
    """按 USE_PG 分支真查 DB（PG 用 asyncpg 或现有 engine，SQLite 查 PRAGMA journal_mode）。

    对外保持 {status, degraded, checks} 兼容：旧字段 status/checks.postgres 保留，
    新增 degraded(bool) 与 checks.db_mode 仅为加法，不破坏旧契约。失败 degraded 不阻断。
    """
    import asyncio
    import os

    from sqlalchemy import text

    from app.core.database import engine

    use_pg = os.getenv("USE_PG", "0") == "1"

    async def ping_postgres():
        # PG 分支：优先 asyncpg 直连 SELECT 1（超时2s），失败回退现有 engine；
        # SQLite 分支：查 PRAGMA journal_mode（WAL 即 ok，查询成功即 ok）。
        if use_pg:
            try:
                import asyncpg  # type: ignore

                from app.core.config import get_settings

                dsn = get_settings().database_url
                # asyncpg 不接受 sqlalchemy 驱动前缀，归一化为纯 postgres dsn
                for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgresql+psycopg2://"):
                    if dsn.startswith(prefix):
                        dsn = "postgresql://" + dsn[len(prefix):]
                        break

                async def _pg_direct():
                    conn = await asyncpg.connect(dsn, timeout=2)
                    try:
                        await conn.fetchval("SELECT 1")
                    finally:
                        await conn.close()
                    return "ok"

                return await asyncio.wait_for(_pg_direct(), timeout=2)
            except Exception:
                pass  # 回退现有 engine
            try:
                def _ping_engine():
                    with engine.connect() as c:
                        c.execute(text("SELECT 1"))
                    return "ok"

                return await asyncio.wait_for(asyncio.to_thread(_ping_engine), timeout=2)
            except Exception:
                return "degraded"
        else:
            try:
                def _ping_sqlite():
                    with engine.connect() as c:
                        c.execute(text("PRAGMA journal_mode;")).fetchall()
                    return "ok"

                return await asyncio.wait_for(asyncio.to_thread(_ping_sqlite), timeout=2)
            except Exception:
                return "degraded"

    # Parallel pings
    results = await asyncio.gather(ping_postgres(), return_exceptions=True)
    pg_status = results[0] if not isinstance(results[0], Exception) else "degraded"
    if not isinstance(pg_status, str):
        pg_status = "degraded"
    degraded = pg_status != "ok"
    status = "degraded" if degraded else "ok"
    return {
        "code": 200,
        "msg": "ok",
        "data": {
            "status": status,
            "degraded": degraded,
            "checks": {
                "postgres": pg_status,
                "db_mode": "pg" if use_pg else "sqlite",
            },
        },
    }
