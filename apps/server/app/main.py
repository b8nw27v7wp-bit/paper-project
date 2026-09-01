from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.auth import router as auth_router
from app.api.v1.goals import router as goals_router
from app.api.v1.goals_async import router as goals_async_router
from app.api.v1.graph import router as graph_router
from app.api.v1.health import router as health_router
from app.api.v1.llm import router as llm_router
from app.api.v1.mcp import router as mcp_router
from app.api.v1.memory import router as memory_router
from app.api.v1.multimodal import router as multimodal_router
from app.api.v1.plans import router as plans_router
from app.api.v1.rag import router as rag_router
from app.api.v1.reflection import router as reflection_router
from app.api.v1.experiments import router as experiments_router
from app.api.v1.stats import router as stats_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.tasks_async import router as tasks_async_router
from app.api.v1.desktop import router as desktop_router
from app.api.v1.agent import router as agent_router
from app.core.config import get_settings
from app.core.database import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = None
    # 启动周反思调度（P2 W21 + P3 周维度增强：register_reflector_jobs 统一注册）
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        from app.scheduler.reflector import register_reflector_jobs, weekly_reflection_job

        scheduler = AsyncIOScheduler()
        # 统一注册周维度作业（weekly_reflection_job 带摘要+通知）
        try:
            register_reflector_jobs(scheduler)
        except Exception as e:
            print(f"[scheduler] register_reflector_jobs failed {e}")
            # 兜底：至少保证基础周反思
            async def _weekly():
                await weekly_reflection_job(user_id=1)

            scheduler.add_job(_weekly, "cron", day_of_week="sun", hour=23, minute=0, id="weekly_reflection", replace_existing=True)
        scheduler.start()
        print("[scheduler] started weekly reflector (P2/P3)")
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
    description="基于多智能体协作与记忆增强的自进化学习任务规划与管理的智能体 — FastAPI 后端",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS: dev 宽松但合规，prod 收敛（修复 H-01：* + credentials 浏览器拒）
# debug=True 时允许本地 5173/3000/Electron，credentials=False 避免预检失败；prod 用 settings.cors_origins
def _cors_config():
    if settings.debug:
        # dev: 明确列出本地源，兼容 TestClient 的 Origin 校验
        return {
            "allow_origins": ["http://localhost:5173", "http://localhost:3000", "http://localhost:5174", "http://127.0.0.1:5173", "app://*"],
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
            "expose_headers": ["Content-Type", "Last-Event-ID", "X-Request-ID"],
        }
    # prod: 仅允许配置的 http(s) 源，过滤 app://*
    origins = [o for o in settings.cors_origins if o.startswith("http://") or o.startswith("https://")]
    return {
        "allow_origins": origins or ["http://localhost:5173"],
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        "allow_headers": ["Authorization", "Content-Type", "X-User-Id", "X-Request-ID", "X-Requested-With", "Last-Event-ID"],
        "expose_headers": ["Content-Type", "Last-Event-ID", "X-Request-ID"],
    }


_cors = _cors_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors["allow_origins"],
    allow_credentials=_cors["allow_credentials"],
    allow_methods=_cors["allow_methods"],
    allow_headers=_cors["allow_headers"],
    expose_headers=_cors.get("expose_headers", ["Content-Type"]),
)


# 强制 JSON 响应带 charset=utf-8，避免 Win/Electron 按 GBK 解码中文
@app.middleware("http")
async def _charset_middleware(request: Request, call_next):
    response = await call_next(request)
    # 仅对 JSON/SSE 追加 charset，若已带 charset 则跳过
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("application/json") and "charset" not in ctype:
        response.headers["content-type"] = "application/json; charset=utf-8"
    if ctype.startswith("text/event-stream") and "charset" not in ctype:
        response.headers["content-type"] = "text/event-stream; charset=utf-8"
    # 额外暴露编码头，供前端调试
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


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
            "agent": "/api/v1/agent/manifest",
        },
    }


# API v1
app.include_router(auth_router, prefix="/api/v1", tags=["auth"])
app.include_router(health_router, prefix="/api/v1", tags=["health"])
app.include_router(goals_router, prefix="/api/v1", tags=["goals"])
app.include_router(goals_async_router, prefix="/api/v1", tags=["goals-async"])
app.include_router(tasks_router, prefix="/api/v1", tags=["tasks"])
app.include_router(tasks_async_router, prefix="/api/v1", tags=["tasks-async"])
app.include_router(plans_router, prefix="/api/v1", tags=["plans"])
app.include_router(memory_router, prefix="/api/v1", tags=["memory"])
app.include_router(rag_router, prefix="/api/v1", tags=["rag"])
app.include_router(graph_router, prefix="/api/v1", tags=["graph"])
app.include_router(mcp_router, prefix="/api/v1", tags=["mcp"])
app.include_router(multimodal_router, prefix="/api/v1", tags=["multimodal"])
app.include_router(reflection_router, prefix="/api/v1", tags=["reflection"])
app.include_router(stats_router, prefix="/api/v1", tags=["stats"])
app.include_router(llm_router, prefix="/api/v1", tags=["llm"])
app.include_router(experiments_router, prefix="/api/v1", tags=["experiments"])
app.include_router(desktop_router, prefix="/api/v1", tags=["desktop"])
app.include_router(agent_router, prefix="/api/v1", tags=["agent"])


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


# Global fallback（H-02：prod 不泄露 str(exc)）
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import logging
    import uuid

    logger = logging.getLogger("app.global")
    trace = str(uuid.uuid4())[:8]
    # 始终服务端记录
    logger.exception(f"[trace={trace}] unhandled {request.method} {request.url.path}: {exc}")
    if settings.debug:
        msg = str(exc) or "internal error"
    else:
        msg = f"internal error (trace={trace})"
    return JSONResponse(
        status_code=500,
        content={"code": 50001, "msg": msg, "data": None},
    )
