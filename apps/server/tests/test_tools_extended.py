"""P1工具干活能力扩展用例：schema缺参/双写默认关/双写开关开/未知工具。"""
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agents.graph import executor_node
from app.agents.tools import registry
from app.core.database import init_db
from app.main import app

init_db()
client = TestClient(app)


def _future(days=5):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _make_goal(title):
    r = client.post("/api/v1/goals", json={"title": title, "deadline": _future()})
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["id"]


@pytest.mark.asyncio
async def test_schema_missing_param_fails():
    # calendar_create 缺必填 start → ToolSchema 校验失败（execute_tool 生命周期：校验→before→执行→after→事件）
    res = await registry.execute_tool("calendar_create", {"title": "NoStart"})
    assert res.get("is_error") is True
    assert "validation failed" in str(res.get("error", "")) or "missing" in str(res.get("error", ""))
    # todo_create 缺 title 同样失败
    res2 = await registry.execute_tool("todo_create", {})
    assert res2.get("is_error") is True
    # web_search 缺 query 同样失败
    res3 = await registry.execute_tool("web_search", {})
    assert res3.get("is_error") is True


@pytest.mark.asyncio
async def test_unknown_tool_not_found():
    res = await registry.execute_tool("not_exist_tool_xyz", {})
    assert res.get("is_error") is True
    assert "not found" in str(res.get("error", "")).lower()


@pytest.mark.asyncio
async def test_dual_write_default_off(monkeypatch):
    gid = _make_goal("Ext Dual Off")
    try:
        now = datetime.now(timezone.utc)
        task = {
            "title": "Ext Dual Off T",
            "planned_start": (now + timedelta(days=1)).isoformat(),
            "planned_end": (now + timedelta(days=1, hours=1)).isoformat(),
            "priority": 3,
        }
        spy = {"calendar": 0}
        real_execute = registry.execute_tool

        async def spy_exec(name, args, context=None):
            if name == "calendar_create":
                spy["calendar"] += 1
            return await real_execute(name, args, context)

        monkeypatch.setattr(registry, "execute_tool", spy_exec)
        res = await executor_node({
            "tasks": [task],
            "goal": {"id": gid, "title": "Ext Dual Off"},
            "trace_id": "traceextoff01",
            "user_id": 1,
            "preferences": {"hours_per_day": 2},
            "_thought": "",
        })
        assert res["task_persist"]["persisted"] is True
        assert spy["calendar"] == 0
        assert "日历双写关闭" in res["_thought"]
        assert res["task_persist"].get("calendar_sync", {}).get("enabled") is False
    finally:
        client.delete(f"/api/v1/goals/{gid}")


@pytest.mark.asyncio
async def test_dual_write_enabled(monkeypatch):
    gid = _make_goal("Ext Dual On")
    try:
        now = datetime.now(timezone.utc)
        task = {
            "title": "Ext Dual On T",
            "planned_start": (now + timedelta(days=1)).isoformat(),
            "planned_end": (now + timedelta(days=1, hours=1)).isoformat(),
            "priority": 3,
        }
        calls: list = []
        real_execute = registry.execute_tool

        async def spy_exec(name, args, context=None):
            if name == "calendar_create":
                calls.append(dict(args))
                return {"result": {"event_id": "mock-id", "title": args.get("title")}, "is_error": False}
            return await real_execute(name, args, context)

        monkeypatch.setattr(registry, "execute_tool", spy_exec)
        res = await executor_node({
            "tasks": [task],
            "goal": {"id": gid, "title": "Ext Dual On"},
            "trace_id": "traceexton01",
            "user_id": 1,
            "preferences": {"hours_per_day": 2, "require_calendar": True},
            "_thought": "",
        })
        assert res["task_persist"]["persisted"] is True
        assert len(calls) >= 1
        assert calls[0].get("title") == "Ext Dual On T"
        assert "日历双写" in res["_thought"]
        assert res["task_persist"].get("calendar_sync", {}).get("enabled") is True
    finally:
        client.delete(f"/api/v1/goals/{gid}")
