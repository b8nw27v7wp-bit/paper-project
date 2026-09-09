from fastapi import APIRouter, Depends, Query, Body
from pydantic import BaseModel
from sqlmodel import Session

from app.core.database import get_session
from app.core.deps import get_current_user_id

router = APIRouter()


class AgentCompareRequest(BaseModel):
    goal_title: str = "演示目标"
    goal_id: int | None = None


class MemoryAblationRequest(BaseModel):
    query: str = "学习"
    top_k: int = 5


class GraphEvidenceRequest(BaseModel):
    query: str = "链表"
    subject: str | None = None


@router.get("/experiments/memory-ablation")
async def memory_ablation_get(
    query: str = Query(default="学习"),
    top_k: int = Query(default=5, ge=1, le=20),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    from app.services.experiments import memory_ablation_experiment

    data = memory_ablation_experiment(session, user_id, query=query)
    data["top_k"] = top_k
    return {"code": 200, "msg": "ok", "data": data}


@router.post("/experiments/memory-ablation")
async def memory_ablation_post(
    payload: MemoryAblationRequest = Body(default=MemoryAblationRequest()),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    from app.services.experiments import memory_ablation_experiment

    data = memory_ablation_experiment(session, user_id, query=payload.query)
    data["top_k"] = payload.top_k
    return {"code": 200, "msg": "ok", "data": data}


@router.get("/experiments/agent-comparison")
async def agent_comparison_get(
    goal_title: str = Query(default="演示目标"),
    goal_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    title = goal_title
    if goal_id:
        try:
            from app.models.goal import LearningGoal

            g = session.get(LearningGoal, goal_id)
            if g and g.user_id == user_id:
                title = g.title
        except Exception:
            pass
    from app.services.experiments import single_vs_multi_experiment

    data = single_vs_multi_experiment(session, user_id, goal_title=title)
    return {"code": 200, "msg": "ok", "data": data}


@router.post("/experiments/agent-comparison")
async def agent_comparison_post(
    payload: AgentCompareRequest = Body(default=AgentCompareRequest()),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    title = payload.goal_title
    if payload.goal_id:
        try:
            from app.models.goal import LearningGoal

            g = session.get(LearningGoal, payload.goal_id)
            if g and g.user_id == user_id:
                title = g.title
        except Exception:
            pass
    from app.services.experiments import single_vs_multi_experiment

    data = single_vs_multi_experiment(session, user_id, goal_title=title)
    return {"code": 200, "msg": "ok", "data": data}


@router.get("/experiments/graph-evidence")
async def graph_evidence_get(
    query: str = Query(default="链表"),
    subject: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    from app.services.experiments import graph_evidence_experiment

    data = graph_evidence_experiment(session, user_id, query=query, subject=subject)
    return {"code": 200, "msg": "ok", "data": data}


@router.post("/experiments/graph-evidence")
async def graph_evidence_post(
    payload: GraphEvidenceRequest = Body(default=GraphEvidenceRequest()),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    from app.services.experiments import graph_evidence_experiment

    data = graph_evidence_experiment(session, user_id, query=payload.query, subject=payload.subject)
    return {"code": 200, "msg": "ok", "data": data}


@router.get("/experiments/suite")
async def suite(
    query: str = Query(default="学习"),
    subject: str | None = Query(default=None),
    goal_title: str = Query(default="演示"),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    from app.services.experiments import full_comparison_suite

    data = full_comparison_suite(session, user_id, goal_title=goal_title, query=query, subject=subject)
    return {"code": 200, "msg": "ok", "data": data}


class SelfEvolutionRequest(BaseModel):
    weeks: int = 3


@router.get("/experiments/self-evolution")
async def self_evolution_get(
    weeks: int = Query(default=3, ge=1, le=12),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """自演进曲线：复用 memory.self_evolution_experiment（经 stats 透传），estimated 口径不变，无新依赖"""
    from app.services.stats import self_evolution_curve

    data = self_evolution_curve(session, user_id, weeks=weeks)
    return {"code": 200, "msg": "ok", "data": data}


@router.post("/experiments/self-evolution")
async def self_evolution_post(
    payload: SelfEvolutionRequest = Body(default=SelfEvolutionRequest()),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    from app.services.stats import self_evolution_curve

    try:
        weeks = max(1, min(12, int(payload.weeks)))
    except (TypeError, ValueError):
        weeks = 3
    data = self_evolution_curve(session, user_id, weeks=weeks)
    return {"code": 200, "msg": "ok", "data": data}
