"""边界测试 - 覆盖 F01/F03/F02 输入极限"""
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db
import pytest

init_db()
client = TestClient(app)

def future(days=2, hours=0):
    return (datetime.now(timezone.utc) + timedelta(days=days, hours=hours)).isoformat()

def test_goal_title_boundaries():
    # 空标题
    r = client.post("/api/v1/goals", json={"title": "", "deadline": future()})
    assert r.status_code in (400, 422)
    # 超长 201
    r = client.post("/api/v1/goals", json={"title": "a"*201, "deadline": future()})
    assert r.status_code in (400, 422)
    # 边界 1 和 200
    r = client.post("/api/v1/goals", json={"title": "a", "deadline": future()})
    assert r.status_code == 201
    gid = r.json()["data"]["id"]
    client.delete(f"/api/v1/goals/{gid}")
    r = client.post("/api/v1/goals", json={"title": "a"*200, "deadline": future()})
    assert r.status_code == 201
    client.delete(f"/api/v1/goals/{r.json()['data']['id']}")

def test_goal_deadline_boundaries():
    now = datetime.now(timezone.utc)
    # 正好 now+1天 -1秒 应失败
    bad = (now + timedelta(days=1) - timedelta(seconds=1)).isoformat()
    r = client.post("/api/v1/goals", json={"title": "Deadline Bad", "deadline": bad})
    assert r.status_code == 400
    assert r.json()["code"] == 40001
    # now+1天+1秒 应成功
    good = (now + timedelta(days=1, seconds=2)).isoformat()
    r = client.post("/api/v1/goals", json={"title": "Deadline Good", "deadline": good})
    assert r.status_code == 201
    client.delete(f"/api/v1/goals/{r.json()['data']['id']}")
    # 无时区
    r = client.post("/api/v1/goals", json={"title": "NoTZ", "deadline": future()[:-6]})  # 去掉时区
    # 应成功或400，取决于实现
    assert r.status_code in (201, 400)

def test_goal_pagination_boundaries():
    # size 0,101 非法
    r = client.get("/api/v1/goals?page=0&size=20")
    assert r.status_code in (400, 422)
    r = client.get("/api/v1/goals?page=1&size=101")
    assert r.status_code in (400, 422)
    # size 1 正常
    r = client.get("/api/v1/goals?page=1&size=1")
    assert r.status_code == 200
    assert r.json()["data"]["size"] == 1
    # 超大页码
    r = client.get("/api/v1/goals?page=9999&size=20")
    assert r.status_code == 200
    assert r.json()["data"]["items"] == []

def test_task_time_boundaries():
    gid = client.post("/api/v1/goals", json={"title": "TaskBound", "deadline": future(5)}).json()["data"]["id"]
    now = datetime.now(timezone.utc)
    s = (now + timedelta(days=1)).isoformat()
    e = s  # 相等应失败
    r = client.post("/api/v1/tasks/batch", json={"tasks": [{"goal_id": gid, "title": "T1", "planned_start": s, "planned_end": e}]})
    assert r.status_code == 400
    assert r.json()["code"] == 40001
    # end < start
    e2 = (now + timedelta(days=1) - timedelta(hours=1)).isoformat()
    r = client.post("/api/v1/tasks/batch", json={"tasks": [{"goal_id": gid, "title": "T1", "planned_start": s, "planned_end": e2}]})
    assert r.status_code == 400
    # 正常
    e3 = (now + timedelta(days=1, hours=1)).isoformat()
    r = client.post("/api/v1/tasks/batch", json={"tasks": [{"goal_id": gid, "title": "T1", "planned_start": s, "planned_end": e3}]})
    assert r.status_code == 201
    tid = r.json()["data"][0]["id"]
    # priority 边界
    for p in [0, 6]:
        r = client.put(f"/api/v1/tasks/{tid}", json={"priority": p})
        assert r.status_code in (400, 422)
    for p in [1, 5]:
        r = client.put(f"/api/v1/tasks/{tid}", json={"priority": p})
        assert r.status_code == 200
    client.delete(f"/api/v1/goals/{gid}")

def test_task_status_enum():
    gid = client.post("/api/v1/goals", json={"title": "StatusTest", "deadline": future(5)}).json()["data"]["id"]
    now = datetime.now(timezone.utc)
    s = (now + timedelta(days=1)).isoformat()
    e = (now + timedelta(days=1, hours=1)).isoformat()
    tid = client.post("/api/v1/tasks/batch", json={"tasks": [{"goal_id": gid, "title": "S", "planned_start": s, "planned_end": e}]}).json()["data"][0]["id"]
    r = client.put(f"/api/v1/tasks/{tid}", json={"status": "invalid"})
    assert r.status_code == 400
    assert r.json()["code"] == 40001
    for ok in ["todo", "doing", "done", "delayed"]:
        r = client.put(f"/api/v1/tasks/{tid}", json={"status": ok})
        assert r.status_code == 200
    client.delete(f"/api/v1/goals/{gid}")

def test_complete_boundaries():
    gid = client.post("/api/v1/goals", json={"title": "CompleteBound", "deadline": future(5)}).json()["data"]["id"]
    now = datetime.now(timezone.utc)
    s = (now + timedelta(days=1)).isoformat()
    e = (now + timedelta(days=1, hours=1)).isoformat()
    tid = client.post("/api/v1/tasks/batch", json={"tasks": [{"goal_id": gid, "title": "C", "planned_start": s, "planned_end": e}]}).json()["data"][0]["id"]
    # duration 负数/601
    r = client.post(f"/api/v1/tasks/{tid}/complete", json={"actual_duration": -1, "completion_rate": 0.5})
    assert r.status_code in (400, 422)
    r = client.post(f"/api/v1/tasks/{tid}/complete", json={"actual_duration": 601, "completion_rate": 0.5})
    assert r.status_code in (400, 422)
    # rate -0.1 / 1.1
    r = client.post(f"/api/v1/tasks/{tid}/complete", json={"actual_duration": 30, "completion_rate": -0.1})
    assert r.status_code in (400, 422)
    r = client.post(f"/api/v1/tasks/{tid}/complete", json={"actual_duration": 30, "completion_rate": 1.1})
    assert r.status_code in (400, 422)
    # 边界 0,600,0,1
    r = client.post(f"/api/v1/tasks/{tid}/complete", json={"actual_duration": 0, "completion_rate": 0, "delay_reason": "test"})
    assert r.status_code == 200
    r = client.post(f"/api/v1/tasks/{tid}/complete", json={"actual_duration": 600, "completion_rate": 1})
    assert r.status_code == 200
    client.delete(f"/api/v1/goals/{gid}")

def test_plan_hours_boundaries():
    gid = client.post("/api/v1/goals", json={"title": "PlanBound", "deadline": future(5)}).json()["data"]["id"]
    for h in [0, 9, -1]:
        r = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": h}})
        assert r.status_code == 400
        assert r.json()["code"] == 40001
    for h in [1, 8]:
        r = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": h}})
        assert r.status_code == 200
    client.delete(f"/api/v1/goals/{gid}")

def test_batch_empty():
    r = client.post("/api/v1/tasks/batch", json={"tasks": []})
    assert r.status_code == 400
    assert r.json()["code"] == 40001
