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
    top_k: int = Query(default=5),
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
