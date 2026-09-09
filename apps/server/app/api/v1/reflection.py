
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.models.reflection import ReflectionReport
from app.scheduler.reflector import generate_reflection

router = APIRouter()


@router.get("/reflection/latest")
def get_latest(session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """返回最新反思报告"""
    report = session.exec(
        select(ReflectionReport).where(ReflectionReport.user_id == user_id).order_by(ReflectionReport.created_at.desc())  # type: ignore
    ).first()
    if not report:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "暂无反思报告"})
    return {"code": 200, "msg": "ok", "data": report}


@router.get("/reflection/week")
def get_week(week: str = Query(...), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    report = session.exec(select(ReflectionReport).where(ReflectionReport.user_id==user_id, ReflectionReport.week==week)).first()
    if not report:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail={"code":40401,"msg":"周报不存在"})
    return {"code":200,"msg":"ok","data": report}

@router.post("/reflection/run")
async def run_reflection(week: str | None = Query(default=None), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    report = await generate_reflection(session, user_id, week)
    return {"code":200,"msg":"ok","data": report}


def _reflection_state_upsert(session: Session, key: str, value: str) -> None:
    """global_state 跨库 upsert（复用 desktop 同语义；reflection:applied 无处存故走 global_state，不设 TTL，配置类数据）。"""
    from sqlalchemy import text

    from app.core.database import USE_PG

    session.execute(text("CREATE TABLE IF NOT EXISTS global_state (key TEXT PRIMARY KEY, value TEXT)"))
    if USE_PG:
        session.execute(
            text("INSERT INTO global_state (key, value) VALUES (:k, :v) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"),
            {"k": key, "v": value},
        )
    else:
        session.execute(
            text("INSERT OR REPLACE INTO global_state (key, value) VALUES (:k, :v)"),
            {"k": key, "v": value},
        )
    session.commit()


@router.post("/reflection/{week}/apply")
def apply_reflection(week: str, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """P2-BE 报告应用标记：ReflectionReport 模型无 applied 列（仅 analysis/next_plan_patch），诚实 bookkeeping 走 global_state。

    - 存 key=reflection:applied:{week}（契约要求）+ 用户隔离键 reflection:applied:{user_id}:{week}（防串用户，值相同）；
    - 返回 {week, applied:true, patch}（patch 取 next_plan_patch，便于前端幂等回显）；
    - 幂等：重复 POST 同值覆盖，结果一致。
    """
    from fastapi import HTTPException

    import json as _json

    try:
        _w = str(week or "").strip()
    except Exception:
        _w = ""
    if not _w:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "week不能为空"})
    report = session.exec(select(ReflectionReport).where(ReflectionReport.user_id == user_id, ReflectionReport.week == _w)).first()
    if not report:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "周报不存在"})
    try:
        _patch = getattr(report, "next_plan_patch", None)
        if _patch is None:
            _patch = {}
        if not isinstance(_patch, dict):
            _patch = {"value": _patch}
    except Exception:
        _patch = {}
    try:
        _val = _json.dumps({"applied": True, "user_id": int(user_id), "week": _w}, ensure_ascii=False)
        _reflection_state_upsert(session, f"reflection:applied:{_w}", _val)
        try:
            _reflection_state_upsert(session, f"reflection:applied:{int(user_id)}:{_w}", _val)
        except Exception:
            pass
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": 50001, "msg": f"应用标记落库失败: {e}"[:200]})
    return {"code": 200, "msg": "ok", "data": {"week": _w, "applied": True, "patch": _patch}}
