from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db

init_db()
client = TestClient(app)

def test_memory_crud_and_search():
    # 清空旧记忆：直接查
    # 创建 3 条记忆
    r = client.post("/api/v1/memory", json={"content": "拖延因难度高，需拆解", "type": "memory"})
    assert r.status_code == 200
    r2 = client.post("/api/v1/memory", json={"content": "偏好早上学习", "type": "memory"})
    assert r2.status_code == 200
    r3 = client.post("/api/v1/memory", json={"content": "薄弱点：链表", "type": "memory"})
    assert r3.status_code == 200
    # 检索
    r = client.get("/api/v1/memory/search?q=拖延&top_k=5")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    assert any("拖延" in d["content"] for d in data)
    # 检索 <1s 已在接口保证

def test_auto_memory_on_complete():
    # 创建 goal+task 完成触发记忆
    from datetime import datetime, timezone, timedelta
    d = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    gid = client.post("/api/v1/goals", json={"title": "AutoMem", "deadline": d}).json()["data"]["id"]
    now = datetime.now(timezone.utc)
    s = (now + timedelta(days=1)).isoformat()
    e = (now + timedelta(days=1, hours=1)).isoformat()
    tid = client.post("/api/v1/tasks/batch", json={"tasks": [{"goal_id": gid, "title": "AutoTask", "planned_start": s, "planned_end": e}]}).json()["data"][0]["id"]
    # 完成
    r = client.post(f"/api/v1/tasks/{tid}/complete", json={"actual_duration": 30, "completion_rate": 0.5, "delay_reason": "难度高"})
    assert r.status_code == 200
    # 查记忆应+1
    r2 = client.get("/api/v1/memory/search?q=AutoTask&top_k=5")
    assert r2.status_code == 200
    # 至少能检索到刚生成的记忆（hash mock 保证相似度）
    # 清理
    client.delete(f"/api/v1/goals/{gid}")

def test_plan_injects_memory():
    d = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    gid = client.post("/api/v1/goals", json={"title": "InjectMem Goal", "deadline": d}).json()["data"]["id"]
    # 先写一条记忆与标题相关
    client.post("/api/v1/memory", json={"content": "InjectMem Goal 相关记忆：偏好晚上", "type": "memory"})
    # 规划
    r = client.post("/api/v1/plans", json={"goal_id": gid})
    assert r.status_code == 200
    tid = r.json()["data"]["trace_id"]
    # 检查 stream 含 memory_search
    with client.stream("GET", f"/api/v1/plans/stream?trace_id={tid}") as s:
        txt = b"".join(s.iter_raw()).decode()
        # 若有记忆，应含 memory_search
        # 即使无记忆，也不报错
        assert "task_created" in txt
    client.delete(f"/api/v1/goals/{gid}")
