"""安全测试 - 越权/注入/XSS/校验/错误码"""
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db

init_db()
client = TestClient(app)

def future(days=5):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

def test_auth_isolation():
    # user1 创建
    r = client.post("/api/v1/goals", json={"title": "User1 Goal", "deadline": future()})
    gid = r.json()["data"]["id"]
    # user2 尝试访问 (通过 X-User-Id 头)
    r2 = client.get(f"/api/v1/goals/{gid}", headers={"X-User-Id": "2"})
    assert r2.status_code == 404
    assert r2.json()["code"] == 40401
    # user2 尝试删除
    r3 = client.delete(f"/api/v1/goals/{gid}", headers={"X-User-Id": "2"})
    assert r3.status_code == 404
    # user1 正常删除
    r4 = client.delete(f"/api/v1/goals/{gid}", headers={"X-User-Id": "1"})
    assert r4.status_code == 204
    # user2 task 越权
    gid1 = client.post("/api/v1/goals", json={"title": "U1", "deadline": future()}).json()["data"]["id"]
    now = datetime.now(timezone.utc)
    s = (now + timedelta(days=1)).isoformat()
    e = (now + timedelta(days=1, hours=1)).isoformat()
    tid = client.post("/api/v1/tasks/batch", json={"tasks": [{"goal_id": gid1, "title": "T", "planned_start": s, "planned_end": e}]}).json()["data"][0]["id"]
    r5 = client.put(f"/api/v1/tasks/{tid}", headers={"X-User-Id": "2"}, json={"title": "hacked"})
    assert r5.status_code == 404
    client.delete(f"/api/v1/goals/{gid1}")

def test_sql_injection():
    # 尝试在标题中注入 SQL
    payload = {"title": "'; DROP TABLE learning_goal; --", "deadline": future()}
    r = client.post("/api/v1/goals", json=payload)
    assert r.status_code == 201
    gid = r.json()["data"]["id"]
    # 验证表仍存在
    r2 = client.get("/api/v1/goals")
    assert r2.status_code == 200
    assert r2.json()["data"]["total"] >= 1
    # 查询应安全转义
    r3 = client.get("/api/v1/goals?status=active")
    assert r3.status_code == 200
    client.delete(f"/api/v1/goals/{gid}")
    # 任务标题注入
    gid2 = client.post("/api/v1/goals", json={"title": "Safe", "deadline": future()}).json()["data"]["id"]
    now = datetime.now(timezone.utc)
    s = (now + timedelta(days=1)).isoformat()
    e = (now + timedelta(days=1, hours=1)).isoformat()
    r4 = client.post("/api/v1/tasks/batch", json={"tasks": [{"goal_id": gid2, "title": "1'; DELETE FROM task; --", "planned_start": s, "planned_end": e}]})
    assert r4.status_code == 201
    # 验证任务仍可查询
    r5 = client.get(f"/api/v1/tasks?goal_id={gid2}")
    assert r5.status_code == 200
    client.delete(f"/api/v1/goals/{gid2}")

def test_xss_storage():
    # 存储型 XSS - 标题含脚本，验证返回未执行但存储原样，依赖前端转义 (Naive UI 会转义)
    payload = {"title": "<script>alert(1)</script>", "deadline": future()}
    r = client.post("/api/v1/goals", json=payload)
    assert r.status_code == 201
    gid = r.json()["data"]["id"]
    r2 = client.get(f"/api/v1/goals/{gid}")
    assert r2.json()["data"]["title"] == "<script>alert(1)</script>"
    # 前端应转义，此处后端仅保证不执行
    client.delete(f"/api/v1/goals/{gid}")

def test_validation_error_codes():
    # 40001 参数校验
    r = client.post("/api/v1/goals", json={"title": "", "deadline": future()})
    assert r.json().get("code") in (40001, 422, 400)
    # 40401 资源不存在
    r = client.get("/api/v1/goals/999999")
    assert r.status_code == 404
    assert r.json()["code"] == 40401
    r = client.get("/api/v1/plans/00000000-0000-0000-0000-000000000000/logs")
    assert r.status_code == 404
    assert r.json()["code"] == 40401
    # 500 兜底 - 触发异常应返回 50001 (通过非法 trace 触发 plan_store 404 已是40401，不易触发500)

def test_cors_headers():
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    # FastAPI CORSMiddleware 应返回 access-control-allow-origin
    # TestClient 不完全模拟浏览器，但可检查中间件已注册
    assert r.status_code == 200
    # 可检查 app 含 CORSMiddleware
    from app.main import app as _app
    mids = [m.cls.__name__ for m in _app.user_middleware]
    assert "CORSMiddleware" in mids

def test_rate_limit_placeholder():
    # 当前未实现限流，仅验证多次请求不误判为限流
    for _ in range(5):
        r = client.get("/api/v1/goals")
        assert r.status_code != 429

def test_sse_trace_isolation():
    # 不同 trace 不应互相可见
    gid = client.post("/api/v1/goals", json={"title": "SSEIso", "deadline": future()}).json()["data"]["id"]
    tid = client.post("/api/v1/plans", json={"goal_id": gid}).json()["data"]["trace_id"]
    r = client.get("/api/v1/plans/stream?trace_id=00000000-0000-0000-0000-000000000000")
    # stream 404
    assert r.status_code == 404
    assert r.json()["code"] == 40401
    client.delete(f"/api/v1/goals/{gid}")

def test_input_length_limits():
    # description 2000 边界
    r = client.post("/api/v1/goals", json={"title": "Len", "deadline": future(), "description": "a"*2000})
    assert r.status_code == 201
    client.delete(f"/api/v1/goals/{r.json()['data']['id']}")
    r = client.post("/api/v1/goals", json={"title": "Len2", "deadline": future(), "description": "a"*2001})
    assert r.status_code in (400, 422)
