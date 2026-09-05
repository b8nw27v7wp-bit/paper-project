import json
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db
from app.models.log import AgentRunLog

init_db()
client = TestClient(app)

def future(days=5):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

def _parse_sse(text: str) -> list[dict]:
    evs: list[dict] = []
    cur: dict = {}
    for line in text.splitlines():
        if line.startswith("event:"):
            cur["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            try:
                cur["data"] = json.loads(line.split(":", 1)[1].strip())
            except (ValueError, TypeError):
                cur["data"] = {}
        elif not line.strip() and "event" in cur:
            evs.append(cur)
            cur = {}
    if "event" in cur:
        evs.append(cur)
    return evs


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

def test_sse_node_order_true_stream(monkeypatch):
    # L1 真实节点事件流：SSE 事件顺序与 6 节点执行序一致（planner→researcher→executor→critic→mentor→reflector）
    from app.agents import compaction

    monkeypatch.setattr(compaction, "THRESHOLD", 10**9)  # 排除会话压干扰，锚点事件全量可见
    r = client.post("/api/v1/goals", json={"title": "Node Order Stream", "deadline": future(5)})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r2.status_code == 200, r2.text
    trace_id = r2.json()["data"]["trace_id"]
    r3 = client.get(f"/api/v1/plans/stream?trace_id={trace_id}")
    assert r3.status_code == 200, r3.text
    evs = _parse_sse(r3.text)
    names = [e["event"] for e in evs]
    assert names[0] == "thought" and evs[0]["data"].get("agent") == "planner"
    assert names[-1] == "done"
    # 锚点定位：各节点完成的标志性事件（executor 无专属事件类型，契约中跳过）
    def idx_of(pred):
        for i, e in enumerate(evs):
            if pred(e):
                return i
        return -1
    i_gen = idx_of(lambda e: e["event"] == "tool_call" and e["data"].get("tool") == "planner_generate")
    i_res = idx_of(lambda e: e["event"] == "tool_call_start" and e["data"].get("tool") == "researcher")
    i_task_last = max((i for i, e in enumerate(evs) if e["event"] == "task_created"), default=-1)
    i_critic = idx_of(lambda e: e["event"] == "critic_feedback")
    i_mentor = idx_of(lambda e: e["event"] == "mentor_msg")
    i_reflector = idx_of(lambda e: e["event"] == "reflector_patch")
    assert -1 not in (i_gen, i_res, i_critic, i_mentor, i_reflector), names
    # 执行序：planner(任务) → researcher → critic → mentor → reflector → done
    assert i_task_last < i_res, names
    assert i_gen < i_res < i_critic < i_mentor < i_reflector < len(names) - 1, names
    client.delete(f"/api/v1/goals/{gid}")

def test_sse_no_fake_delay():
    # L1 验收：删除伪流 sleep(0.08)×N，流式总耗时应显著小于 事件数×0.08s；源码级断言伪流已移除
    import inspect
    import time as _time

    from app.api.v1 import plans as plans_mod

    assert "sleep(0.08)" not in inspect.getsource(plans_mod)
    assert "模拟流式" not in inspect.getsource(plans_mod)
    r = client.post("/api/v1/goals", json={"title": "No Fake Delay", "deadline": future(5)})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r2.status_code == 200, r2.text
    trace_id = r2.json()["data"]["trace_id"]
    t0 = _time.perf_counter()
    r3 = client.get(f"/api/v1/plans/stream?trace_id={trace_id}")
    elapsed = _time.perf_counter() - t0
    assert r3.status_code == 200, r3.text
    n_events = len([line for line in r3.text.splitlines() if line.startswith("event:")])
    assert n_events >= 5
    assert elapsed < n_events * 0.08, f"stream took {elapsed:.3f}s for {n_events} events (伪流延迟未删除?)"
    client.delete(f"/api/v1/goals/{gid}")

def test_stream_trace_ownership():
    # 他人 trace 访问 stream 应 404（防枚举泄露）
    r = client.post("/api/v1/goals", json={"title": "Owner Test", "deadline": future(5)})
    gid = r.json()["data"]["id"]
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r2.status_code == 200
    trace = r2.json()["data"]["trace_id"]
    # 归属 user1（默认），user2 访问应 404
    r3 = client.get(f"/api/v1/plans/stream?trace_id={trace}", headers={"X-User-Id": "2"})
    assert r3.status_code == 404, r3.text
    # 归属本人正常 200
    r4 = client.get(f"/api/v1/plans/stream?trace_id={trace}", headers={"X-User-Id": "1"})
    assert r4.status_code == 200
    client.delete(f"/api/v1/goals/{gid}")

def test_safe_parse_dt():
    from app.api.v1.plans import _safe_parse_dt

    assert _safe_parse_dt("2026-09-10T09:00:00+00:00") is not None
    assert _safe_parse_dt("not-a-date") is None
    assert _safe_parse_dt(None) is None
    assert _safe_parse_dt("") is None
    d = _safe_parse_dt("2026-09-10T09:00:00")
    assert d is not None and d.tzinfo is not None

def test_reflector_patch_replan_edge():
    from app.api.v1.plans import _build_graph_from_logs

    trace = "t" * 32
    goal = {"id": 1, "title": "x"}
    logs = [
        AgentRunLog(trace_id=trace, agent_name="planner", input={"goal": goal}, output={"tasks": []}, tool_calls=[]),
        AgentRunLog(trace_id=trace, agent_name="critic", input={}, output={"feedback": "", "rewrites": 0}, tool_calls=[]),
        AgentRunLog(trace_id=trace, agent_name="reflector", input={}, output={"patch": {"reallocate": True}}, tool_calls=[]),
    ]
    g = _build_graph_from_logs(logs, trace)
    assert any(e["type"] == "replan" for e in g["edges"]), g
    # 无 patch 无 rewrites 时不产生回边
    logs2 = [l for l in logs if l.agent_name != "reflector"]
    logs2.append(AgentRunLog(trace_id=trace, agent_name="reflector", input={}, output={"patch": {}}, tool_calls=[]))
    g2 = _build_graph_from_logs(logs2, trace)
    assert not any(e["type"] == "replan" for e in g2["edges"]), g2
    # rewrites 语义不被 patch 分支污染
    assert g["rewrites"] == 0
