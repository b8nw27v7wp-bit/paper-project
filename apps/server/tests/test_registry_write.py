from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.agents.tools import registry
from app.core.database import engine, init_db
from app.main import app
from app.models.task import Task

init_db()
client = TestClient(app)


def _make_goal(title):
    d = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    r = client.post("/api/v1/goals", json={"title": title, "deadline": d})
    assert r.status_code in (200, 201)
    return r.json()["data"]["id"]


def _count(goal_id, title):
    with Session(engine) as s:
        return len(s.exec(select(Task).where(Task.goal_id == goal_id, Task.title == title)).all())


async def test_write_tasks_persists():
    gid = _make_goal("WT Persist")
    now = datetime.now(UTC)
    tasks = [
        {"goal_id": gid, "title": "WT A", "planned_start": (now + timedelta(days=1)).isoformat(), "planned_end": (now + timedelta(days=1, hours=1)).isoformat(), "priority": 2},
        {"goal_id": gid, "title": "WT B", "planned_start": (now + timedelta(days=2)).isoformat(), "planned_end": (now + timedelta(days=2, hours=2)).isoformat()},
    ]
    res = await registry.write_tasks(tasks=tasks, user_id=1)
    assert isinstance(res, list) and len(res) == 2
    assert all(r["goal_id"] == gid for r in res)
    assert _count(gid, "WT A") == 1
    assert _count(gid, "WT B") == 1
    assert res[0]["priority"] == 2
    assert res[1]["priority"] == 3
    client.delete(f"/api/v1/goals/{gid}")


async def test_write_tasks_forbidden_goal():
    res = await registry.write_tasks(tasks=[{
        "goal_id": 99999999,
        "title": "WT X",
        "planned_start": "2026-09-10T09:00:00Z",
        "planned_end": "2026-09-10T10:00:00Z",
    }], user_id=1)
    assert isinstance(res, dict)
    assert res["code"] == 40401
    assert res["is_error"] is True


async def test_write_tasks_invalid_time():
    gid = _make_goal("WT BadTime")
    res = await registry.write_tasks(tasks=[{
        "goal_id": gid,
        "title": "WT Bad",
        "planned_start": "2026-09-10T10:00:00Z",
        "planned_end": "2026-09-10T09:00:00Z",
    }], user_id=1)
    assert isinstance(res, dict)
    assert res["code"] == 40001
    assert "planned_end" in res["error"]
    assert _count(gid, "WT Bad") == 0
    client.delete(f"/api/v1/goals/{gid}")


async def test_write_tasks_missing_title():
    gid = _make_goal("WT NoTitle")
    res = await registry.write_tasks(tasks=[{
        "goal_id": gid,
        "title": "   ",
        "planned_start": "2026-09-10T09:00:00Z",
        "planned_end": "2026-09-10T10:00:00Z",
    }], user_id=1)
    assert isinstance(res, dict)
    assert res["code"] == 40001
    assert _count(gid, "   ") == 0
    client.delete(f"/api/v1/goals/{gid}")


async def test_write_tasks_idempotent():
    gid = _make_goal("WT Idem")
    payload = [{
        "goal_id": gid,
        "title": "WT Idem T",
        "planned_start": "2026-09-11T09:00:00+00:00",
        "planned_end": "2026-09-11T11:00:00+00:00",
    }]
    r1 = await registry.write_tasks(tasks=payload, user_id=1)
    assert isinstance(r1, list) and len(r1) == 1
    r2 = await registry.write_tasks(tasks=payload, user_id=1)
    assert isinstance(r2, list) and len(r2) == 0
    assert _count(gid, "WT Idem T") == 1
    client.delete(f"/api/v1/goals/{gid}")


async def test_write_tasks_dedup_in_batch():
    gid = _make_goal("WT BatchDup")
    item = {
        "goal_id": gid,
        "title": "WT Dup",
        "planned_start": "2026-09-12T09:00:00+00:00",
        "planned_end": "2026-09-12T10:00:00+00:00",
    }
    res = await registry.write_tasks(tasks=[item, dict(item)], user_id=1)
    assert isinstance(res, list) and len(res) == 1
    assert _count(gid, "WT Dup") == 1
    client.delete(f"/api/v1/goals/{gid}")


async def test_write_tasks_via_execute_tool():
    gid = _make_goal("WT Exec")
    res = await registry.execute_tool("write_tasks", {"tasks": [{
        "goal_id": gid,
        "title": "WT Exec T",
        "planned_start": "2026-09-13T09:00:00+00:00",
        "planned_end": "2026-09-13T10:00:00+00:00",
    }]})
    assert res["is_error"] is False
    assert isinstance(res["result"], list) and len(res["result"]) == 1
    assert _count(gid, "WT Exec T") == 1
    client.delete(f"/api/v1/goals/{gid}")
