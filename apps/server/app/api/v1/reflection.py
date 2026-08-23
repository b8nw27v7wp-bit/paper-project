
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.models.reflection import ReflectionReport
from app.scheduler.reflector import generate_reflection

router = APIRouter()

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
