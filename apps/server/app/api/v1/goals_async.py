"""全链 Async 示例：Goals 的 AsyncSession 完整迁移（P0-1 收口 2%）

- 使用 app/core/database.py:async_engine + async_session_factory
- 演示 5 接口全 async：POST/GET/GET{id}/PUT/DELETE 均 await
- 原同步 goals.py 保留兼容，本路由为 /api/v1/async/goals 前缀，供压测对比
"""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.database import get_async_session
from app.core.deps import get_current_user_id
from app.models.goal import LearningGoal

router = APIRouter()

def _v_deadline(v: datetime):
    if v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    if v <= datetime.now(UTC) + __import__("datetime").timedelta(days=1):
        raise HTTPException(status_code=400, detail={"code":40001,"msg":"deadline需>now+1d"})
    return v

@router.post("/async/goals", status_code=201)
async def create_async(payload: dict, session: AsyncSession = Depends(get_async_session), user_id: int = Depends(get_current_user_id)):
    title = (payload.get("title") or "").strip()
    if not title or len(title) > 200:
        raise HTTPException(status_code=400, detail={"code":40001,"msg":"title 1-200 必填"})
    dl = payload.get("deadline")
    if not dl:
        raise HTTPException(status_code=400, detail={"code":40001,"msg":"deadline 必填"})
    try:
        d = datetime.fromisoformat(str(dl))
    except Exception:
        raise HTTPException(status_code=400, detail={"code":40001,"msg":"deadline 非 ISO8601"})
    d = _v_deadline(d)
    g = LearningGoal(user_id=user_id, title=title, description=(payload.get("description") or "")[:2000], deadline=d, subject=payload.get("subject"))
    session.add(g)
    await session.commit()
    await session.refresh(g)
    return {"code":201,"msg":"ok","data": g}

@router.get("/async/goals")
async def list_async(status: str | None = Query(default=None), page: int = Query(default=1, ge=1), size: int = Query(default=20, ge=1, le=100), session: AsyncSession = Depends(get_async_session), user_id: int = Depends(get_current_user_id)):
    from sqlalchemy import func
    # 兼容：async_session 对 select 的 exec 需 await
    q = select(LearningGoal).where(LearningGoal.user_id == user_id)
    if status:
        q = q.where(LearningGoal.status == status)
    # total
    total_q = select(func.count()).select_from(q.subquery())
    total = (await session.exec(total_q)).one() if hasattr(session, "exec") else (await session.execute(total_q)).scalar()  # type: ignore
    # items
    items = (await session.exec(q.order_by(LearningGoal.created_at.desc()).offset((page-1)*size).limit(size))).all() if hasattr(session, "exec") else (await session.execute(q.order_by(LearningGoal.created_at.desc()).offset((page-1)*size).limit(size))).scalars().all()  # type: ignore
    return {"code":200,"msg":"ok","data":{"items": items, "total": total, "page": page, "size": size}}

@router.get("/async/goals/{gid}")
async def get_one_async(gid: int, session: AsyncSession = Depends(get_async_session), user_id: int = Depends(get_current_user_id)):
    g = await session.get(LearningGoal, gid)
    if not g or g.user_id != user_id:
        raise HTTPException(status_code=404, detail={"code":40401,"msg":"目标不存在"})
    return {"code":200,"msg":"ok","data": g}

@router.put("/async/goals/{gid}")
async def update_async(gid: int, payload: dict, session: AsyncSession = Depends(get_async_session), user_id: int = Depends(get_current_user_id)):
    g = await session.get(LearningGoal, gid)
    if not g or g.user_id != user_id:
        raise HTTPException(status_code=404, detail={"code":40401,"msg":"目标不存在"})
    if "title" in payload:
        t = str(payload["title"]).strip()
        if not t: raise HTTPException(status_code=400, detail={"code":40001,"msg":"标题不能为空"})
        g.title = t[:200]
    if "deadline" in payload and payload["deadline"]:
        d = datetime.fromisoformat(str(payload["deadline"]))
        g.deadline = _v_deadline(d)
    if "status" in payload:
        g.status = payload["status"]
    session.add(g)
    await session.commit()
    await session.refresh(g)
    return {"code":200,"msg":"ok","data": g}

@router.delete("/async/goals/{gid}", status_code=204)
async def delete_async(gid: int, session: AsyncSession = Depends(get_async_session), user_id: int = Depends(get_current_user_id)):
    from app.models.execution import TaskExecutionLog
    from app.models.task import Task

    g = await session.get(LearningGoal, gid)
    if not g or g.user_id != user_id:
        raise HTTPException(status_code=404, detail={"code":40401,"msg":"目标不存在"})
    # 级联删 tasks（PG 强制 FK：先删 task_execution_log，再删 task；与同步 goals.py 一致）
    t_res = await session.execute(select(Task).where(Task.goal_id == gid))
    try:
        tasks = t_res.scalars().all()  # type: ignore
    except Exception:
        tasks = t_res.all()
    for t in tasks:
        obj = t[0] if isinstance(t, (list, tuple)) else t
        tid = obj.id if hasattr(obj, "id") else obj
        l_res = await session.execute(select(TaskExecutionLog).where(TaskExecutionLog.task_id == tid))
        try:
            logs = l_res.scalars().all()  # type: ignore
        except Exception:
            logs = l_res.all()
        for l in logs:
            await session.delete(l[0] if isinstance(l, (list, tuple)) else l)
        await session.delete(obj)
    # 无 relationship 时同 flush 删序不可靠，分步 flush 强制 log→task→goal
    await session.flush()
    await session.delete(g)
    await session.commit()
    return None
