from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.models.execution import ExecutionCreate, TaskExecutionLog
from app.models.goal import LearningGoal
from app.models.task import Task, TaskBatchCreate, TaskUpdate
from app.services.memory import create_memory, summarize_for_task

router = APIRouter()


def _ensure_goal_owned(goal_id: int, session: Session, user_id: int) -> LearningGoal:
    goal = session.get(LearningGoal, goal_id)
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


@router.get("/tasks")
def list_tasks(
    goal_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    q = select(Task)
    if goal_id is not None:
        _ensure_goal_owned(goal_id, session, user_id)
        q = q.where(Task.goal_id == goal_id)
    else:
        # 限定用户下所有目标的任务
        goal_ids = session.exec(select(LearningGoal.id).where(LearningGoal.user_id == user_id)).all()
        if not goal_ids:
            return {"code": 200, "msg": "ok", "data": {"items": [], "total": 0, "page": page, "size": size}}
        q = q.where(Task.goal_id.in_(goal_ids))
    if status:
        if status not in ("todo", "doing", "done", "delayed"):
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "status非法"})
        q = q.where(Task.status == status)
    total = session.exec(select(func.count()).select_from(q.subquery())).one()
    items = session.exec(q.order_by(Task.planned_start).offset((page - 1) * size).limit(size)).all()
    return {"code": 200, "msg": "ok", "data": {"items": items, "total": total, "page": page, "size": size}}


@router.put("/tasks/{task_id}")
def update_task(task_id: int, payload: TaskUpdate, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "任务不存在"})
    _ensure_goal_owned(task.goal_id, session, user_id)
    if payload.title is not None:
        t = payload.title.strip()
        if not t:
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "标题不能为空"})
        task.title = t
    # 时间校验
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
    session.commit()
    session.refresh(task)
    return {"code": 200, "msg": "ok", "data": task}


@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: int, payload: ExecutionCreate, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "任务不存在"})
    _ensure_goal_owned(task.goal_id, session, user_id)
    # 写入 log
    log = TaskExecutionLog(
        task_id=task_id,
        actual_duration=payload.actual_duration,
        completion_rate=payload.completion_rate,
        delay_reason=payload.delay_reason,
    )
    session.add(log)
    # 同步更新任务状态为 done/delayed 依据完成率
    if payload.completion_rate >= 1:
        task.status = "done"
    elif payload.completion_rate == 0 and payload.delay_reason:
        task.status = "delayed"
    session.add(task)
    session.commit()
    session.refresh(log)
    # 自动沉淀记忆 (W12) - 避免二次commit导致log过期
    log_data = log.model_dump()
    try:
        content = summarize_for_task(task.title, payload.actual_duration, payload.completion_rate, payload.delay_reason)
        await create_memory(session, user_id, content, type_="memory", source_id=task_id)
        # 重新刷新log以防过期
        session.refresh(log)
        log_data = log.model_dump()
    except Exception:
        pass
    return {"code": 200, "msg": "ok", "data": log_data}


@router.post("/tasks/batch", status_code=201)
def batch_create(payload: TaskBatchCreate, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    if not payload.tasks:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "tasks不能为空"})
    created = []
    for tc in payload.tasks:
        if tc.goal_id is None:
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "每项需含 goal_id"})
        _ensure_goal_owned(tc.goal_id, session, user_id)
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
    session.commit()
    for c in created:
        session.refresh(c)
    return {"code": 200, "msg": "ok", "data": created}


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "任务不存在"})
    _ensure_goal_owned(task.goal_id, session, user_id)
    # 删除关联 log
    logs = session.exec(select(TaskExecutionLog).where(TaskExecutionLog.task_id == task_id)).all()
    for l in logs:
        session.delete(l)
    session.delete(task)
    session.commit()
