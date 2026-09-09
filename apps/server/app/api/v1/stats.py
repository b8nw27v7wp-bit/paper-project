from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.services.stats import experiment_a, experiment_b, overview, self_evolution_curve, trend

router = APIRouter()

@router.get("/stats/overview")
def get_overview(range: str = Query(default="7d", pattern="^(7d|30d|365d)$"), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    data = overview(session, user_id, range)
    return {"code":200,"msg":"ok","data":data}

@router.get("/stats/trend")
def get_trend(range: str = Query(default="30d", pattern="^(7d|30d|365d)$"), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    data = trend(session, user_id, range)
    return {"code":200,"msg":"ok","data":data}

@router.post("/stats/experiment")
def run_experiment(type: str = Query(default="A", pattern="^(A|B)$"), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    if type == "A":
        return {"code":200,"msg":"ok","data": experiment_a(session, user_id)}
    else:
        return {"code":200,"msg":"ok","data": experiment_b(session, user_id)}

@router.get("/stats/self-evolution")
def get_self_evolution(weeks: int = Query(default=3, ge=1, le=12), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """自演进曲线：复用 stats.self_evolution_curve（底层即 memory.self_evolution_experiment），estimated 口径不变"""
    data = self_evolution_curve(session, user_id, weeks=weeks)
    return {"code":200,"msg":"ok","data":data}
