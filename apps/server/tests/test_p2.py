from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db
import io

init_db()
client = TestClient(app)

def test_mcp():
    r = client.get("/api/v1/mcp/servers")
    assert r.status_code == 200
    assert len(r.json()["data"]) >= 2
    r2 = client.post("/api/v1/mcp/call", json={"server": "calendar", "tool": "create_calendar_event", "args": {"title": "Test", "start": "2026-08-25T09:00:00Z", "end": "2026-08-25T10:00:00Z"}})
    assert r2.status_code == 200
    assert "event_id" in r2.json()["data"]

def test_multimodal():
    # OCR mock
    r = client.post("/api/v1/multimodal/ocr", files={"file": ("test.jpg", io.BytesIO(b"fake image"), "image/jpeg")})
    assert r.status_code == 200
    assert "courses" in r.json()["data"]
    # ASR mock
    r2 = client.post("/api/v1/multimodal/asr", files={"file": ("test.webm", io.BytesIO(b"fake audio"), "audio/webm")})
    assert r2.status_code == 200
    assert "text" in r2.json()["data"]

def test_reflection():
    # 先造点执行数据
    from datetime import datetime, timezone, timedelta
    d = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    gid = client.post("/api/v1/goals", json={"title": "Reflect", "deadline": d}).json()["data"]["id"]
    now = datetime.now(timezone.utc)
    s = (now + timedelta(days=1)).isoformat()
    e = (now + timedelta(days=1, hours=1)).isoformat()
    tid = client.post("/api/v1/tasks/batch", json={"tasks": [{"goal_id": gid, "title": "T", "planned_start": s, "planned_end": e}]}).json()["data"][0]["id"]
    client.post(f"/api/v1/tasks/{tid}/complete", json={"actual_duration": 60, "completion_rate": 1.0})
    r = client.post("/api/v1/reflection/run")
    assert r.status_code == 200
    assert "completion_rate" in r.json()["data"]
    week = r.json()["data"]["week"]
    r2 = client.get(f"/api/v1/reflection/week?week={week}")
    assert r2.status_code == 200
    client.delete(f"/api/v1/goals/{gid}")

def test_cli_import():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("cli", "apps/cli/main.py")
    assert spec is not None
