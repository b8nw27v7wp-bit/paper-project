from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.goals import router as goals_router
from app.api.v1.graph import router as graph_router
from app.api.v1.health import router as health_router
from app.api.v1.llm import router as llm_router
from app.api.v1.mcp import router as mcp_router
from app.api.v1.memory import router as memory_router
from app.api.v1.multimodal import router as multimodal_router
from app.api.v1.plans import router as plans_router
from app.api.v1.rag import router as rag_router
from app.api.v1.reflection import router as reflection_router
from app.api.v1.stats import router as stats_router
from app.api.v1.tasks import router as tasks_router
from app.core.config import get_settings
from app.core.database import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = None
    # 启动周反思调度
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from sqlmodel import Session

        from app.core.database import engine
        from app.scheduler.reflector import generate_reflection
        scheduler = AsyncIOScheduler()

        async def _weekly():
            with Session(engine) as s:
                try:
                    await generate_reflection(s, user_id=1)
                except Exception as e:
                    print(f"[scheduler] reflection error {e}")

        scheduler.add_job(_weekly, "cron", day_of_week="sun", hour=23, minute=0, id="weekly_reflection", replace_existing=True)
        scheduler.start()
        print("[scheduler] started weekly 0 23 * * 0")
    except Exception as e:
        print(f"[scheduler] start failed {e}")
    yield
    try:
        if scheduler:
            scheduler.shutdown()
    except Exception:
        pass

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="基于多智能体协作与记忆增强的自进化学习任务规划与管理系统 — FastAPI 后端",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS: P0 permissive for local dev (5173+Electron); production tighten via settings.cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Root health (no prefix, for Docker/K8s probes)
@app.get("/health", tags=["health"], summary="Root health probe")
async def root_health():
    return {"code": 200, "msg": "ok", "data": {"status": "ok", "version": settings.app_version}}


@app.get("/", tags=["root"])
async def root():
    return {
        "code": 200,
        "msg": "ok",
        "data": {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/health",
            "api_health": "/api/v1/health",
        },
    }


# API v1
app.include_router(health_router, prefix="/api/v1", tags=["health"])
app.include_router(goals_router, prefix="/api/v1", tags=["goals"])
app.include_router(tasks_router, prefix="/api/v1", tags=["tasks"])
app.include_router(plans_router, prefix="/api/v1", tags=["plans"])
app.include_router(memory_router, prefix="/api/v1", tags=["memory"])
app.include_router(rag_router, prefix="/api/v1", tags=["rag"])
app.include_router(graph_router, prefix="/api/v1", tags=["graph"])
app.include_router(mcp_router, prefix="/api/v1", tags=["mcp"])
app.include_router(multimodal_router, prefix="/api/v1", tags=["multimodal"])
app.include_router(reflection_router, prefix="/api/v1", tags=["reflection"])
app.include_router(stats_router, prefix="/api/v1", tags=["stats"])
app.include_router(llm_router, prefix="/api/v1", tags=["llm"])


# Validation errors -> 40001
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"code": 40001, "msg": "参数校验失败", "data": {"errors": exc.errors()}},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # 若 detail 已含 code/msg 则透传
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        code = exc.detail.get("code", 40001)
        msg = exc.detail.get("msg", str(exc.detail))
        status = exc.status_code
        return JSONResponse(status_code=status, content={"code": code, "msg": msg, "data": None})
    return await request_validation_exception_handler(request, exc) if exc.status_code == 400 else JSONResponse(
        status_code=exc.status_code, content={"code": exc.status_code * 100 + 1, "msg": str(exc.detail), "data": None}
    )


# Global fallback
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"code": 50001, "msg": str(exc), "data": None},
    )
