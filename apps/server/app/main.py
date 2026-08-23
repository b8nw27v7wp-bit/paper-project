from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

from app.core.config import get_settings
from app.core.database import init_db
from app.api.v1.health import router as health_router
from app.api.v1.goals import router as goals_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.plans import router as plans_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="基于多智能体协作与记忆增强的自进化学习任务规划与管理系统 — FastAPI 后端",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS: allow Vite 5173 + Electron
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # P0 permissive; tighten in production via settings.cors_origins
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
