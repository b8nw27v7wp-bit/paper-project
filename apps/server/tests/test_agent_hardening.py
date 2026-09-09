import pytest
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.core.llm as llm_mod
from app.agents.graph import critic_node, executor_node
from app.agents.tools import registry
from app.core.database import engine, init_db
from app.main import app
from app.models.task import Task
from app.scheduler.reflector import generate_reflection

init_db()
client = TestClient(app)


def _future(days=5):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _mk_task(start, end, title="T"):
    return {"title": title, "planned_start": start.isoformat(), "planned_end": end.isoformat(), "priority": 3}


def _overlap_tasks():
    now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    return [_mk_task(now, now + timedelta(hours=2), "A"), _mk_task(now + timedelta(hours=1), now + timedelta(hours=3), "B")]


def _make_goal(title):
    r = client.post("/api/v1/goals", json={"title": title, "deadline": _future()})
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["id"]


# ── D1: critic LLM 复核在 astream 事件循环内被真实 await ────────────────


@pytest.mark.asyncio
async def test_critic_llm_real_awaited(monkeypatch):
    calls = {"n": 0}

    class FakeClient:
        async def chat(self, messages, **kw):
            calls["n"] += 1
            assert kw.get("temperature") == 0.2
            return '{"pass": false, "reason": "负荷过高"}'

    monkeypatch.setattr(llm_mod, "UnifiedClient", FakeClient)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    res = await critic_node({"tasks": _overlap_tasks(), "graphDeps": [], "rewrites": 0})
    assert calls["n"] == 1
    assert "LLM复核" in res["critic_feedback"]
    assert "负荷过高" in res["critic_feedback"]


@pytest.mark.asyncio
async def test_critic_llm_fail_degrades_to_rules(monkeypatch):
    calls = {"n": 0}

    class BoomClient:
        async def chat(self, messages, **kw):
            calls["n"] += 1
            raise TimeoutError("llm down")

    monkeypatch.setattr(llm_mod, "UnifiedClient", BoomClient)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    tasks = []
    for i in range(3):
        s = now + timedelta(hours=i * 1.5)
        tasks.append(_mk_task(s, s + timedelta(hours=1.5), f"T{i}"))
    res = await critic_node({"tasks": tasks, "graphDeps": [], "rewrites": 0})
    assert calls["n"] == 1
    assert res["critic_feedback"]
    assert "超4h" in res["critic_feedback"] or "负荷" in res["critic_feedback"]


@pytest.mark.asyncio
async def test_critic_llm_pass_returns_no_feedback(monkeypatch):
    calls = {"n": 0}

    class FakeClient:
        async def chat(self, messages, **kw):
            calls["n"] += 1
            return '{"pass": true, "reason": ""}'

    monkeypatch.setattr(llm_mod, "UnifiedClient", FakeClient)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    t1 = _mk_task(now, now + timedelta(hours=1), "A")
    t2 = _mk_task(now + timedelta(hours=2), now + timedelta(hours=3), "B")
    res = await critic_node({"tasks": [t1, t2], "graphDeps": [], "rewrites": 0})
    assert calls["n"] == 1
    assert res["critic_feedback"] == ""


# ── D2: executor 经 execute_tool("write_tasks") 真落库 + 失败降级 ───────


@pytest.mark.asyncio
async def test_executor_persists_via_execute_tool(monkeypatch):
    gid = _make_goal("Hardening Exec")
    now = datetime.now(timezone.utc)
    task = {
        "title": "Hardening Exec T",
        "planned_start": (now + timedelta(days=1)).isoformat(),
        "planned_end": (now + timedelta(days=1, hours=1)).isoformat(),
        "priority": 3,
    }
    spy = {"n": 0}
    real_execute = registry.execute_tool

    async def execute_spy(name, args, context=None):
        spy["n"] += 1
        assert name == "write_tasks"
        return await real_execute(name, args, context)

    monkeypatch.setattr(registry, "execute_tool", execute_spy)
    res = await executor_node({"tasks": [task], "goal": {"id": gid, "title": "Hardening Exec"}, "trace_id": "traceexec01", "user_id": 1, "_thought": ""})
    assert spy["n"] == 1
    assert res["task_persist"]["persisted"] is True
    assert res["task_persist"]["created"] == 1
    with Session(engine) as s:
        rows = s.exec(select(Task).where(Task.goal_id == gid, Task.title == "Hardening Exec T")).all()
        assert len(rows) == 1
        assert rows[0].source_agent == "planner:traceexec01"
    client.delete(f"/api/v1/goals/{gid}")


@pytest.mark.asyncio
async def test_executor_degrades_on_structured_error():
    gid = _make_goal("Hardening Degrade")
    res = await executor_node({
        "tasks": [{"title": "Bad Goal", "planned_start": "2026-09-10T09:00:00+00:00", "planned_end": "2026-09-10T10:00:00+00:00"}],
        "goal": {"id": 99999999, "title": "nope"},
        "trace_id": "tracedeg01",
        "user_id": 1,
        "_thought": "",
    })
    assert res["task_persist"]["persisted"] is False
    assert "40401" in res["task_persist"]["error"] or "目标不存在" in res["task_persist"]["error"]
    with Session(engine) as s:
        assert not s.exec(select(Task).where(Task.title == "Bad Goal")).all()
    client.delete(f"/api/v1/goals/{gid}")


@pytest.mark.asyncio
async def test_executor_degrades_on_execute_tool_crash(monkeypatch):
    gid = _make_goal("Hardening Crash")

    async def boom(name, args, context=None):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(registry, "execute_tool", boom)
    now = datetime.now(timezone.utc)
    task = {"title": "Crash T", "planned_start": (now + timedelta(days=1)).isoformat(), "planned_end": (now + timedelta(days=1, hours=1)).isoformat()}
    res = await executor_node({"tasks": [task], "goal": {"id": gid, "title": "Hardening Crash"}, "trace_id": "tracecrash1", "user_id": 1, "_thought": ""})
    assert res["task_persist"]["persisted"] is False
    assert res["task_persist"]["error"]
    assert res["_thought"].endswith("落库失败降级state透传")
    client.delete(f"/api/v1/goals/{gid}")


# ── D3: replan 写入 state/日志 + reflector 统计读取到（自演进闭环）──────


@pytest.mark.asyncio
async def test_critic_accumulates_replan_reasons():
    res = await critic_node({"tasks": _overlap_tasks(), "graphDeps": [], "rewrites": 0})
    assert res["replan_reasons"]
    assert "重叠" in res["replan_reasons"][0]
    res2 = await critic_node({"tasks": _overlap_tasks(), "graphDeps": [], "rewrites": 0, "replan_reasons": ["历史原因"]})
    assert res2["replan_reasons"][0] == "历史原因"
    assert len(res2["replan_reasons"]) == 2


@pytest.mark.asyncio
async def test_replan_loop_to_reflector(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_api_key", "")

    def overlapping_mock(goal, preferences, trace_id=""):
        now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
        tasks = _overlap_tasks()
        for t in tasks:
            t["date"] = now.date().isoformat()
        return tasks, "mock"

    monkeypatch.setattr("app.agents.graph.mock_generate", overlapping_mock)
    gid = _make_goal("Hardening Replan")
    r = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    trace = data["trace_id"]
    assert data["rewrites"] >= 1
    assert data["replan_reasons"]
    logs = client.get(f"/api/v1/plans/{trace}/logs").json()["data"]
    critic_log = next(l for l in logs if l["agent_name"] == "critic")
    assert critic_log["output"]["rewrites"] >= 1
    assert critic_log["output"]["replan_reasons"]
    with Session(engine) as s:
        report = await generate_reflection(s, 1)
    patch = report.next_plan_patch or {}
    assert patch.get("replan_rate", 0) > 0
    assert "重演" in report.analysis
    client.delete(f"/api/v1/goals/{gid}")


# ── 新增：落库顺序（critic 拦截时不落库，executor 移到 critic 通过之后） ──


@pytest.mark.asyncio
async def test_persist_order_critic_blocks_no_write(monkeypatch):
    from app.agents.graph import critic_node, should_replan

    spy = {"n": 0}
    real_execute = registry.execute_tool

    async def spy_exec(name, args, context=None):
        if name == "write_tasks":
            spy["n"] += 1
        return await real_execute(name, args, context)

    monkeypatch.setattr(registry, "execute_tool", spy_exec)
    # critic 拦截：重叠任务必有反馈，should_replan=replan（不走 executor）
    cres = await critic_node({"tasks": _overlap_tasks(), "graphDeps": [], "rewrites": 0})
    assert cres["critic_feedback"]
    assert "重叠" in cres["critic_feedback"]
    assert should_replan({"critic_feedback": cres["critic_feedback"], "rewrites": 0}) == "replan"
    assert spy["n"] == 0
    # 通过才走 executor
    assert should_replan({"critic_feedback": "", "rewrites": 0}) == "executor"
    assert should_replan({"terminate": True}) == "mentor"
    # 耗尽重写仍有反馈时直达 mentor（不落库）——P2放宽为rewrites<3，第3轮仍replan，仅第4轮才mentor
    assert should_replan({"critic_feedback": "重叠", "rewrites": 2}) == "replan"
    assert should_replan({"critic_feedback": "重叠", "rewrites": 3}) == "mentor"


# ── 新增：user_id 全链透传（executor→write_tasks 必填） ──


@pytest.mark.asyncio
async def test_user_id_passthrough_required(monkeypatch):
    captured: dict = {}
    real_execute = registry.execute_tool

    async def cap_exec(name, args, context=None):
        if name == "write_tasks":
            captured.update(args)
        return await real_execute(name, args, context)

    monkeypatch.setattr(registry, "execute_tool", cap_exec)
    gid = _make_goal("Hardening UID")
    now = datetime.now(timezone.utc)
    task = {
        "title": "UID T",
        "planned_start": (now + timedelta(days=1)).isoformat(),
        "planned_end": (now + timedelta(days=1, hours=1)).isoformat(),
        "priority": 3,
    }
    res = await executor_node({"tasks": [task], "goal": {"id": gid, "title": "Hardening UID"}, "trace_id": "traceuid01", "user_id": 1, "_thought": ""})
    assert res["task_persist"]["persisted"] is True
    assert captured.get("user_id") == 1
    # 缺 user_id 调用方必填 → 不落库并报错
    res2 = await executor_node({"tasks": [task], "goal": {"id": gid, "title": "Hardening UID"}, "trace_id": "traceuid02", "_thought": ""})
    assert res2["task_persist"]["persisted"] is False
    assert "user_id" in res2["task_persist"]["error"]
    # execute_tool 直调缺 user_id → schema/函数双层拦截
    bad = await real_execute("write_tasks", {"tasks": [{"goal_id": gid, "title": "NoUID", "planned_start": task["planned_start"], "planned_end": task["planned_end"]}]})
    assert bad.get("is_error") is True
    client.delete(f"/api/v1/goals/{gid}")


# ── 新增：伪 LLM 复核降级标记（不再拼“LLM复核:不通过”） ──


@pytest.mark.asyncio
async def test_llm_degraded_marker_no_fake_feedback(monkeypatch):
    from app.agents.graph import critic_node as _critic

    class BoomClient:
        async def chat(self, messages, **kw):
            raise TimeoutError("llm down")

    monkeypatch.setattr(llm_mod, "UnifiedClient", BoomClient)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    # 合法单任务：规则无反馈，LLM 失败应标记 degraded 且不拼伪造复核
    t = _mk_task(now, now + timedelta(hours=1), "Solo")
    res = await _critic({"tasks": [t], "graphDeps": [], "rewrites": 0})
    assert res["critic_feedback"] == ""
    assert res.get("llm") == "degraded"
    # 规则有反馈 + LLM 失败：保留规则反馈，不拼伪造，仍标记 degraded
    res2 = await _critic({"tasks": _overlap_tasks(), "graphDeps": [], "rewrites": 0})
    assert "重叠" in res2["critic_feedback"]
    assert "LLM复核" not in res2["critic_feedback"]
    assert res2.get("llm") == "degraded"
