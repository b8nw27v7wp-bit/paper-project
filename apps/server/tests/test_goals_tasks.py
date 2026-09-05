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


def _mk_task_for_user(user_id: int):
    # 为指定用户建目标+任务，返回 task_id
    h = {"X-User-Id": str(user_id)}
    payload = {"title": f"Pomodoro Goal U{user_id}", "deadline": future_deadline(3), "subject": "Test"}
    r = client.post("/api/v1/goals", json=payload, headers=h)
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    now = datetime.now(timezone.utc)
    batch = {"tasks": [
        {"goal_id": gid, "title": "Pomodoro Task", "planned_start": (now + timedelta(hours=1)).isoformat(), "planned_end": (now + timedelta(hours=2)).isoformat()},
    ]}
    r = client.post("/api/v1/tasks/batch", json=batch, headers=h)
    assert r.status_code == 201, r.text
    return gid, r.json()["data"][0]["id"]


def test_pomodoro_success_and_validation():
    gid, tid = _mk_task_for_user(1)
    # 成功写入
    r = client.post(f"/api/v1/tasks/{tid}/pomodoro", json={"duration_seconds": 300, "focus_score": 0.8})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["task_id"] == tid
    assert data["actual_duration"] == 300
    assert data["completion_rate"] == 0.8
    assert data["delay_reason"] == "pomodoro"
    # 参数越界 -> 400（全局 RequestValidationError -> 40001）
    r = client.post(f"/api/v1/tasks/{tid}/pomodoro", json={"duration_seconds": 601, "focus_score": 0.5})
    assert r.status_code == 400
    assert r.json()["code"] == 40001
    r = client.post(f"/api/v1/tasks/{tid}/pomodoro", json={"duration_seconds": 0, "focus_score": 0.5})
    assert r.status_code == 400
    r = client.post(f"/api/v1/tasks/{tid}/pomodoro", json={"duration_seconds": 600, "focus_score": 1.2})
    assert r.status_code == 400
    # 边界值可用
    r = client.post(f"/api/v1/tasks/{tid}/pomodoro", json={"duration_seconds": 600, "focus_score": 1.0})
    assert r.status_code == 200
    # 清理
    client.delete(f"/api/v1/tasks/{tid}")
    client.delete(f"/api/v1/goals/{gid}")


def test_pomodoro_404_and_forbidden():
    # 不存在的任务 -> 404
    r = client.post("/api/v1/tasks/999999/pomodoro", json={"duration_seconds": 300, "focus_score": 0.5})
    assert r.status_code == 404
    assert r.json()["code"] == 40401
    # 非本人任务 -> 404（goal 属于 user 2，匿名默认 user 1）
    gid2, tid2 = _mk_task_for_user(2)
    r = client.post(f"/api/v1/tasks/{tid2}/pomodoro", json={"duration_seconds": 300, "focus_score": 0.5})
    assert r.status_code == 404
    assert r.json()["code"] == 40401
    # 本人可访问（对照）
    r = client.post(f"/api/v1/tasks/{tid2}/pomodoro", json={"duration_seconds": 300, "focus_score": 0.5}, headers={"X-User-Id": "2"})
    assert r.status_code == 200
    client.delete(f"/api/v1/tasks/{tid2}", headers={"X-User-Id": "2"})
    client.delete(f"/api/v1/goals/{gid2}", headers={"X-User-Id": "2"})
