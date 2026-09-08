"""Async 示范：Tasks 的 AsyncSession 完整迁移（与 goals_async.py 对称）

- 使用 app/core/database.py:async_engine + async_session_factory
- 演示 5 接口全 async：GET/PUT/POST{complete}/POST{batch}/DELETE 均 await
- 原同步 tasks.py 保留兼容，本路由为 /api/v1/async/tasks 前缀，供压测对比
- 保持 {code,msg,data} 统一，DELETE 204
"""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.database import get_async_session
from app.core.deps import get_current_user_id
from app.models.execution import ExecutionCreate, TaskExecutionLog
from app.models.goal import LearningGoal
from app.models.task import Task, TaskBatchCreate, TaskUpdate
from app.services.memory import summarize_for_task

router = APIRouter()


async def _ensure_goal_owned_async(goal_id: int, session: AsyncSession, user_id: int) -> LearningGoal:
    goal = await session.get(LearningGoal, goal_id)
    if not goal or goal.user_id != user_id:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "目标不存在或无权限"})
    return goal


def _validate_task_time(start: datetime, end: datetime):
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if end <= start:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "planned_end必须大于planned_start"})


@router.get("/async/tasks")
async def list_tasks_async(
    goal_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_async_session),
    user_id: int = Depends(get_current_user_id),
):
    q = select(Task)
    if goal_id is not None:
        await _ensure_goal_owned_async(goal_id, session, user_id)
        q = q.where(Task.goal_id == goal_id)
    else:
        # 限定用户下所有目标的任务
        # AsyncSession 执行 select
        goal_ids_res = await session.execute(select(LearningGoal.id).where(LearningGoal.user_id == user_id))
        # 兼容 SQLite/PG 返回
        try:
            goal_ids = [r[0] for r in goal_ids_res.all()]
        except Exception:
            goal_ids = list(goal_ids_res.scalars().all())  # type: ignore
        if not goal_ids:
            return {"code": 200, "msg": "ok", "data": {"items": [], "total": 0, "page": page, "size": size}}
        q = q.where(Task.goal_id.in_(goal_ids))
    if status:
        if status not in ("todo", "doing", "done", "delayed"):
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "status非法"})
        q = q.where(Task.status == status)
    # total
    total_q = select(func.count()).select_from(q.subquery())
    total_res = await session.execute(total_q)
    try:
        total = total_res.scalar() or 0
    except Exception:
        total = total_res.one()[0]  # type: ignore
    # items
    items_res = await session.execute(q.order_by(Task.planned_start).offset((page - 1) * size).limit(size))
    try:
        items = items_res.scalars().all()  # type: ignore
    except Exception:
        items = items_res.all()
    return {"code": 200, "msg": "ok", "data": {"items": items, "total": total, "page": page, "size": size}}


@router.put("/async/tasks/{task_id}")
async def update_task_async(task_id: int, payload: TaskUpdate, session: AsyncSession = Depends(get_async_session), user_id: int = Depends(get_current_user_id)):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "任务不存在"})
    await _ensure_goal_owned_async(task.goal_id, session, user_id)
    if payload.title is not None:
        t = payload.title.strip()
        if not t:
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "标题不能为空"})
        task.title = t
    new_start = payload.planned_start if payload.planned_start is not None else task.planned_start
    new_end = payload.planned_end if payload.planned_end is not None else task.planned_end
    if payload.planned_start is not None or payload.planned_end is not None:
        _validate_task_time(new_start, new_end)
        task.planned_start = new_start
        task.planned_end = new_end
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.status is not None:
        if payload.status not in ("todo", "doing", "done", "delayed"):
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "status非法"})
        task.status = payload.status
    if payload.source_agent is not None:
        task.source_agent = payload.source_agent
    if payload.citations is not None:
        task.citations = payload.citations
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return {"code": 200, "msg": "ok", "data": task}


@router.post("/async/tasks/{task_id}/complete")
async def complete_task_async(task_id: int, payload: ExecutionCreate, session: AsyncSession = Depends(get_async_session), user_id: int = Depends(get_current_user_id)):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "任务不存在"})
    await _ensure_goal_owned_async(task.goal_id, session, user_id)
    log = TaskExecutionLog(
        task_id=task_id,
        actual_duration=payload.actual_duration,
        completion_rate=payload.completion_rate,
        delay_reason=payload.delay_reason,
    )
    session.add(log)
    if payload.completion_rate >= 1:
        task.status = "done"
    elif payload.completion_rate == 0 and payload.delay_reason:
        task.status = "delayed"
    session.add(task)
    await session.commit()
    await session.refresh(log)
    log_data = log.model_dump()
    try:
        content = summarize_for_task(task.title, payload.actual_duration, payload.completion_rate, payload.delay_reason)
        # AsyncSession 兼容：直接创建 MemoryChunk 而非调用同步 create_memory
        from app.models.memory import MemoryChunk
        from app.services.memory import embed_text
        import json

        vec = await embed_text(content)
        try:
            from app.models.memory import _USE_PG_VECTOR

            embedding_val = vec if _USE_PG_VECTOR else json.dumps(vec)
        except Exception:
            embedding_val = json.dumps(vec)
        mc = MemoryChunk(user_id=user_id, content=content, embedding=embedding_val, type="execution", source_id=task_id)  # type: ignore
        session.add(mc)
        await session.commit()
        await session.refresh(log)
        log_data = log.model_dump()
    except Exception:
        pass
    return {"code": 200, "msg": "ok", "data": log_data}


@router.post("/async/tasks/batch", status_code=201)
async def batch_create_async(payload: TaskBatchCreate, session: AsyncSession = Depends(get_async_session), user_id: int = Depends(get_current_user_id)):
    if not payload.tasks:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "tasks不能为空"})
    if len(payload.tasks) > 50:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "批量最多50条"})
    created = []
    for tc in payload.tasks:
        if tc.goal_id is None:
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "每项需含 goal_id"})
        await _ensure_goal_owned_async(tc.goal_id, session, user_id)
        _validate_task_time(tc.planned_start, tc.planned_end)
        t = Task(
            goal_id=tc.goal_id,
            title=tc.title.strip(),
            planned_start=tc.planned_start,
            planned_end=tc.planned_end,
            priority=tc.priority or 3,
            status=tc.status or "todo",
            source_agent=tc.source_agent,
            citations=tc.citations,
        )
        if not t.title:
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "标题不能为空"})
        session.add(t)
        created.append(t)
    await session.commit()
    for c in created:
        await session.refresh(c)
    return {"code": 200, "msg": "ok", "data": created}


@router.delete("/async/tasks/{task_id}", status_code=204)
async def delete_task_async(task_id: int, session: AsyncSession = Depends(get_async_session), user_id: int = Depends(get_current_user_id)):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "任务不存在"})
    await _ensure_goal_owned_async(task.goal_id, session, user_id)
    # 删除关联 log
    logs_res = await session.execute(select(TaskExecutionLog).where(TaskExecutionLog.task_id == task_id))
    try:
        logs = logs_res.scalars().all()  # type: ignore
    except Exception:
        logs = logs_res.all()
    for l in logs:
        # l 可能是 Row，取实际对象
        obj = l[0] if isinstance(l, (list, tuple)) else l
        await session.delete(obj)
    # 无 relationship 时同 flush 删序不可靠，分步 flush 强制 log→task
    await session.flush()
    await session.delete(task)
    await session.commit()
    return None
