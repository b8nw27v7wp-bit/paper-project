import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import init_db

init_db()
client = TestClient(app)


def future_deadline(days=5):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["code"] == 200


def test_goals_crud():
    # create
    payload = {"title": "Test Goal W3", "deadline": future_deadline(3), "subject": "Test"}
    r = client.post("/api/v1/goals", json=payload)
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]

    # list
    r = client.get("/api/v1/goals?page=1&size=20")
    assert r.status_code == 200
    assert r.json()["data"]["total"] >= 1

    # get detail
    r = client.get(f"/api/v1/goals/{gid}")
    assert r.status_code == 200
    assert r.json()["data"]["id"] == gid

    # update
    r = client.put(f"/api/v1/goals/{gid}", json={"title": "Updated Goal"})
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Updated Goal"

    # deadline validation
    bad = {"title": "Bad", "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    r = client.post("/api/v1/goals", json=bad)
    assert r.status_code == 400
    assert r.json()["code"] == 40001

    # delete later
    return gid


def test_tasks_crud():
    gid = test_goals_crud()
    # batch create
    now = datetime.now(timezone.utc)
    s1 = (now + timedelta(days=1)).isoformat()
    e1 = (now + timedelta(days=1, hours=1)).isoformat()
    s2 = (now + timedelta(days=2)).isoformat()
    e2 = (now + timedelta(days=2, hours=2)).isoformat()
    batch = {"tasks": [
        {"goal_id": gid, "title": "Task A", "planned_start": s1, "planned_end": e1, "priority": 4},
        {"goal_id": gid, "title": "Task B", "planned_start": s2, "planned_end": e2, "priority": 5},
    ]}
    r = client.post("/api/v1/tasks/batch", json=batch)
    assert r.status_code == 201, r.text
    tids = [t["id"] for t in r.json()["data"]]
    assert len(tids) == 2

    # list
    r = client.get(f"/api/v1/tasks?goal_id={gid}&page=1&size=20")
    assert r.status_code == 200
    assert r.json()["data"]["total"] == 2

    # update (drag)
    new_end = (now + timedelta(days=1, hours=2)).isoformat()
    r = client.put(f"/api/v1/tasks/{tids[0]}", json={"planned_end": new_end})
    assert r.status_code == 200

    # complete
    r = client.post(f"/api/v1/tasks/{tids[0]}/complete", json={"actual_duration": 60, "completion_rate": 1.0})
    assert r.status_code == 200
    assert r.json()["data"]["task_id"] == tids[0]

    # verify done
    r = client.get(f"/api/v1/tasks?goal_id={gid}")
    items = r.json()["data"]["items"]
    assert any(t["status"] == "done" for t in items)

    # validation: end before start
    r = client.put(f"/api/v1/tasks/{tids[1]}", json={"planned_start": e1, "planned_end": s1})
    assert r.status_code == 400

    # delete task
    r = client.delete(f"/api/v1/tasks/{tids[1]}")
    assert r.status_code == 204

    # delete goal cascades
    r = client.delete(f"/api/v1/goals/{gid}")
    assert r.status_code == 204

    # verify gone
    r = client.get(f"/api/v1/goals/{gid}")
    assert r.status_code == 404
