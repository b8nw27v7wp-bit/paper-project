from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, SQLModel, select

from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.models.execution import TaskExecutionLog
from app.models.goal import GoalCreate, GoalUpdate, LearningGoal
from app.models.task import Task

router = APIRouter()


class BatchArchiveRequest(SQLModel):
    ids: list[int]


@router.post("/goals/batch-archive")
def batch_archive_goals(payload: BatchArchiveRequest, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """P2-BE 批量归档：逐个归档（复用单目标校验+404语义），返回 {archived, missing}，上限50（只增不改既有）。"""
    try:
        ids = list(payload.ids or [])
    except Exception:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "ids需为整数数组"})
    if len(ids) > 50:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "批量最多50条"})
    archived: list[int] = []
    missing: list[int] = []
    for gid in ids:
        try:
            _gid = int(gid)
        except Exception:
            try:
                missing.append(int(gid))  # type: ignore
            except Exception:
                pass
            continue
        goal = session.get(LearningGoal, _gid)
        if not goal or goal.user_id != user_id:
            missing.append(_gid)
            continue
        try:
            goal.status = "archived"
            session.add(goal)
            archived.append(_gid)
        except Exception:
            missing.append(_gid)
            continue
    try:
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail={"code": 50001, "msg": "批量归档落库失败"})
    return {"code": 200, "msg": "ok", "data": {"archived": archived, "missing": missing}}


def _validate_deadline(deadline: datetime):
    # 确保 timezone aware
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if deadline <= now + timedelta(days=1):
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "deadline需大于当前时间+1天"})


@router.post("/goals", status_code=201)
def create_goal(payload: GoalCreate, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    _validate_deadline(payload.deadline)
    if payload.status not in (None, "active", "archived"):
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "status仅支持 active/archived"})
    goal = LearningGoal(
        user_id=user_id,
        title=payload.title.strip(),
        description=payload.description,
        deadline=payload.deadline,
        subject=payload.subject,
        status=payload.status or "active",
    )
    if not goal.title:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "标题不能为空"})
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return {"code": 201, "msg": "ok", "data": goal}


@router.get("/goals")
def list_goals(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    q = select(LearningGoal).where(LearningGoal.user_id == user_id)
    if status:
        if status not in ("active", "archived"):
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "status非法"})
        q = q.where(LearningGoal.status == status)
    total = session.exec(select(func.count()).select_from(q.subquery())).one()
    items = session.exec(q.order_by(LearningGoal.created_at.desc()).offset((page - 1) * size).limit(size)).all()
    return {"code": 200, "msg": "ok", "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/goals/{goal_id}")
def get_goal(goal_id: int, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    goal = session.get(LearningGoal, goal_id)
    if not goal or goal.user_id != user_id:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "目标不存在"})
    tasks = session.exec(select(Task).where(Task.goal_id == goal_id).order_by(Task.planned_start)).all()
    # 合并返回
    data = goal.model_dump()
    data["tasks"] = tasks
    return {"code": 200, "msg": "ok", "data": data}


@router.put("/goals/{goal_id}")
def update_goal(goal_id: int, payload: GoalUpdate, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    goal = session.get(LearningGoal, goal_id)
    if not goal or goal.user_id != user_id:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "目标不存在"})
    if payload.deadline is not None:
        _validate_deadline(payload.deadline)
        goal.deadline = payload.deadline
    if payload.title is not None:
        t = payload.title.strip()
        if not t:
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "标题不能为空"})
        goal.title = t
    if payload.description is not None:
        goal.description = payload.description
    if payload.subject is not None:
        goal.subject = payload.subject
    if payload.status is not None:
        if payload.status not in ("active", "archived"):
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "status非法"})
        goal.status = payload.status
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return {"code": 200, "msg": "ok", "data": goal}


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    goal = session.get(LearningGoal, goal_id)
    if not goal or goal.user_id != user_id:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "目标不存在"})
    # 级联删 tasks（PG 强制 FK：先删 task_execution_log，再删 task，最后删 goal；
    # 无 relationship 时 UOW 同 flush 内删序不可靠，必须分步 flush 强制顺序）
    tasks = session.exec(select(Task).where(Task.goal_id == goal_id)).all()
    for t in tasks:
        logs = session.exec(select(TaskExecutionLog).where(TaskExecutionLog.task_id == t.id)).all()
        for lg in logs:
            session.delete(lg)
        session.delete(t)
    session.flush()
    session.delete(goal)
    session.commit()
