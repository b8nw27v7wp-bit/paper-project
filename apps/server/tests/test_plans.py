from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db

init_db()
client = TestClient(app)

def future(days=5):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

def test_plans_flow():
    # create goal
    r = client.post("/api/v1/goals", json={"title": "Plan Test", "deadline": future(5)})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    # create plan mock
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r2.status_code == 200, r2.text
    data = r2.json()["data"]
    trace = data["trace_id"]
    tasks = data["tasks"]
    assert len(tasks) >= 3
    assert "mentor_msg" in data
    # logs
    r3 = client.get(f"/api/v1/plans/{trace}/logs")
    assert r3.status_code == 200
    assert len(r3.json()["data"]) >= 1
    # stream - check endpoint exists (TestClient can iterate)
    # Use stream via client
    with client.stream("GET", f"/api/v1/plans/stream?trace_id={trace}") as s:
        assert s.status_code == 200
        content = b"".join(s.iter_raw()).decode()
        assert "task_created" in content or "done" in content

def test_plans_invalid():
    r = client.post("/api/v1/plans", json={"goal_id": 9999})
    assert r.status_code == 404
    r2 = client.post("/api/v1/plans", json={"goal_id": 1, "preferences": {"hours_per_day": 99}})
    # need valid goal first
    gid = client.post("/api/v1/goals", json={"title": "BadPref", "deadline": future(5)}).json()["data"]["id"]
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 99}})
    assert r2.status_code == 400

def test_sse_true_stream():
    # 真流验证：用 TestClient get 拿到完整 SSE 文本，校验 content-type 与首事件
    r = client.post("/api/v1/goals", json={"title": "SSE True Stream", "deadline": future(5)})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r2.status_code == 200, r2.text
    trace_id = r2.json()["data"]["trace_id"]
    # 使用 TestClient 同步 get 验证 SSE（非 stream 迭代）
    r3 = client.get(f"/api/v1/plans/stream?trace_id={trace_id}")
    assert r3.status_code == 200, r3.text
    ctype = r3.headers.get("content-type", "")
    assert "text/event-stream" in ctype, f"content-type should be text/event-stream, got {ctype}"
    text = r3.text
    assert "event: thought" in text, text[:2000]
    # 首事件应为 thought
    events = [line.strip() for line in text.splitlines() if line.strip().startswith("event:")]
    assert len(events) >= 1, f"no events in {text[:500]}"
    assert events[0] == "event: thought", f"first event should be thought, got {events[0]}"
    # 同时应包含 done 结束事件
    assert "event: done" in text
    client.delete(f"/api/v1/goals/{gid}")
