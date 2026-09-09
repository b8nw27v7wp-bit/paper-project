"""Inspector 深字段（v2.0）：replan_reasons / citations / degraded 加法字段。

builder 直测为主（快），端点级一例锁包络。
"""
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.v1.plans import _build_inspector_from_logs
from app.core.database import engine, init_db
from app.main import app
from app.models.goal import LearningGoal
from app.models.log import AgentRunLog
from app.models.task import Task

init_db()
client = TestClient(app)


def _log(agent, output, tid="insp-t1", goal_id=None):
    inp = {"goal": {"id": goal_id, "title": "G"}} if goal_id else {}
    return AgentRunLog(trace_id=tid, agent_name=agent, input=inp, output=output, tool_calls=[])


def test_builder_replan_reasons_and_degraded():
    logs = [
        _log("planner", {"tasks": []}),
        _log("critic", {"feedback": "fb", "rewrites": 1, "replan_reasons": ["overload Mon"]}),
        _log("executor", {"count": 0, "persist": {"persisted": False, "created": 0, "error": "boom"}}),
    ]
    data = _build_inspector_from_logs(logs, "insp-t1")
    assert data["state"]["replan_reasons"] == ["overload Mon"]
    assert data["state"]["degraded"] is True


def test_builder_clean_trace_not_degraded():
    logs = [
        _log("planner", {"tasks": []}),
        _log("critic", {"feedback": "ok", "rewrites": 0}),
        _log("executor", {"count": 2, "persist": {"persisted": True, "created": 2, "error": ""}}),
    ]
    data = _build_inspector_from_logs(logs, "insp-t1")
    assert data["state"]["degraded"] is False
    assert "replan_reasons" not in data["state"] or data["state"].get("replan_reasons") in (None, [])


def test_builder_citations_from_task_rows():
    tid = "insp-cit-" + uuid.uuid4().hex[:8]
    with Session(engine) as s:
        g = LearningGoal(user_id=1, title="Insp Cit", deadline=datetime.now(UTC) + timedelta(days=5))
        s.add(g)
        s.commit()
        s.refresh(g)
        t = Task(
            goal_id=g.id,
            title="Cit Task",
            planned_start=datetime.now(UTC) + timedelta(days=1),
            planned_end=datetime.now(UTC) + timedelta(days=1, hours=1),
            source_agent=f"planner:{tid}",
            citations=[{"chunk_id": 7, "score": 0.9}],
        )
        s.add(t)
        s.commit()
        try:
            data = _build_inspector_from_logs([_log("planner", {"tasks": []}, tid, g.id)], tid, s)
            assert data["state"]["citations"] == [{"chunk_id": 7, "score": 0.9}]
        finally:
            s.delete(t)
            s.delete(g)
            s.commit()


def test_inspector_endpoint_has_new_fields():
    r = client.post("/api/v1/goals", json={"title": "Insp EP", "deadline": (datetime.now(UTC) + timedelta(days=5)).isoformat()})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    tid = "insp-ep-" + uuid.uuid4().hex[:8]
    with Session(engine) as s:
        s.add(AgentRunLog(trace_id=tid, agent_name="planner", input={"goal": {"id": gid}}, output={"tasks": []}, tool_calls=[]))
        s.add(AgentRunLog(trace_id=tid, agent_name="critic", input={}, output={"feedback": "f", "rewrites": 0, "replan_reasons": ["r1"]}, tool_calls=[]))
        s.add(AgentRunLog(trace_id=tid, agent_name="executor", input={}, output={"count": 0, "persist": {"persisted": False, "created": 0, "error": "x"}}, tool_calls=[]))
        s.add(Task(goal_id=gid, title="EP T", planned_start=datetime.now(UTC) + timedelta(days=1), planned_end=datetime.now(UTC) + timedelta(days=1, hours=1), source_agent=f"planner:{tid}", citations=[{"chunk_id": 1, "score": 0.5}]))
        s.commit()
    try:
        r2 = client.get(f"/api/v1/plans/{tid}/inspector")
        assert r2.status_code == 200, r2.text
        st = r2.json()["data"]["state"]
        assert st["replan_reasons"] == ["r1"]
        assert st["degraded"] is True
        assert st["citations"] == [{"chunk_id": 1, "score": 0.5}]
    finally:
        with Session(engine) as s:
            for lg in s.exec(select(AgentRunLog).where(AgentRunLog.trace_id == tid)).all():
                s.delete(lg)
            for t in s.exec(select(Task).where(Task.source_agent == f"planner:{tid}")).all():
                s.delete(t)
            s.commit()
        client.delete(f"/api/v1/goals/{gid}")
