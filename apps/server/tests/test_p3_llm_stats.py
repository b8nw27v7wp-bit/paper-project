"""新增小接口回归：summarize 50001 / overview focus_seconds / trend 365d（中文注释）"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.database import init_db
from app.main import app

init_db()
client = TestClient(app)


def _future(days=5):
    # 中文注释：生成合法 deadline（大于当前+1天）
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_summarize_no_key_50001(monkeypatch):
    # 中文注释：无 key/失败时抛 50001，由前端回退拼装，后端不拼装
    for k in ("ZHIPU_API_KEY", "BIGMODEL_API_KEY", "ZHIPU_API_KEY_ENV", "DEEPSEEK_API_KEY", "QWEN_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    r = client.post("/api/v1/llm/summarize", json={"text": "番茄钟专注学习了两小时", "max_len": 12})
    assert r.status_code == 500, r.text
    body = r.json()
    assert body["code"] == 50001, body
    assert body["data"] is None, body


def test_overview_has_focus_seconds():
    # 中文注释：overview 必含 focus_seconds 字段，无数据时为 0
    r = client.get("/api/v1/stats/overview")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "focus_seconds" in data, data
    assert isinstance(data["focus_seconds"], int) and data["focus_seconds"] >= 0


def test_overview_focus_seconds_with_pomodoro():
    # 中文注释：用隔离用户造一条 pomodoro 上报，overview 的 focus_seconds 应累加
    import random

    uid = str(random.randint(51000, 99999))
    headers = {"X-User-Id": uid}
    gid = client.post("/api/v1/goals", json={"title": "FocusSec", "deadline": _future()}, headers=headers).json()["data"]["id"]
    now = datetime.now(timezone.utc)
    s = (now + timedelta(days=1)).isoformat()
    e = (now + timedelta(days=1, hours=1)).isoformat()
    tid = client.post("/api/v1/tasks/batch", json={"tasks": [{"goal_id": gid, "title": "T", "planned_start": s, "planned_end": e}]}, headers=headers).json()["data"][0]["id"]
    pr = client.post(f"/api/v1/tasks/{tid}/pomodoro", json={"duration_seconds": 150, "focus_score": 0.9}, headers=headers)
    assert pr.status_code == 200, pr.text
    r = client.get("/api/v1/stats/overview", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["focus_seconds"] >= 150, data
    client.delete(f"/api/v1/goals/{gid}", headers=headers)


def test_trend_365d_returns_365_points():
    # 中文注释：年趋势 range=365d 返回 365 点
    r = client.get("/api/v1/stats/trend", params={"range": "365d"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data["dates"]) == 365, len(data["dates"])
    assert len(data["rates"]) == 365
    assert len(data["loads"]) == 365


def test_overview_365d_ok():
    # 中文注释：overview 同样放开 365d，不应 422 且含 focus_seconds
    r = client.get("/api/v1/stats/overview", params={"range": "365d"})
    assert r.status_code == 200, r.text
    assert "focus_seconds" in r.json()["data"]
