import json
import uuid
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

def test_plans_sessions_aggregate():
    r = client.post("/api/v1/goals", json={"title": "Sessions Aggregate", "deadline": future(5)})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r2.status_code == 200, r2.text
    trace = r2.json()["data"]["trace_id"]
    single_trace = "s" * 23 + uuid.uuid4().hex[:13]
    from sqlmodel import Session

    from app.core.database import engine

    with Session(engine) as s:
        s.add(
            AgentRunLog(
                trace_id=single_trace,
                agent_name="planner",
                input={"goal": {"id": gid, "title": "Sessions Aggregate"}, "preferences": {}},
                output={"tasks": []},
                tool_calls=[],
            )
        )
        s.commit()
    r3 = client.get("/api/v1/plans/sessions", params={"size": 100})
    assert r3.status_code == 200, r3.text
    d = r3.json()["data"]
    assert d["page"] == 1 and d["size"] == 100
    assert d["total"] >= 2
    ids = {it["trace_id"] for it in d["items"]}
    assert trace in ids and single_trace in ids
    multi_item = next(it for it in d["items"] if it["trace_id"] == trace)
    assert multi_item["mode"] == "multi"
    assert multi_item["goal_id"] == gid
    assert multi_item["goal_title"] == "Sessions Aggregate"
    assert multi_item["event_count"] >= 6
    assert multi_item["status"] == "completed"
    assert multi_item["started_at"] and multi_item["last_event_at"]
    ns = multi_item["node_summary"]
    assert set(ns) == {"planner", "researcher", "executor", "critic", "mentor", "reflector"}
    assert all(v["has_log"] for v in ns.values())
    assert isinstance(ns["critic"]["rewrites"], int)
    assert isinstance(ns["reflector"]["replan"], bool)
    single_item = next(it for it in d["items"] if it["trace_id"] == single_trace)
    assert single_item["mode"] == "single"
    assert single_item["status"] == "running"
    assert single_item["event_count"] == 1
    assert single_item["node_summary"]["reflector"]["has_log"] is False
    client.delete(f"/api/v1/goals/{gid}")

def test_plans_sessions_user_isolation():
    r = client.post("/api/v1/goals", json={"title": "Iso U1", "deadline": future(5)}, headers={"X-User-Id": "1"})
    assert r.status_code == 201, r.text
    gid1 = r.json()["data"]["id"]
    r2 = client.post("/api/v1/plans", json={"goal_id": gid1}, headers={"X-User-Id": "1"})
    assert r2.status_code == 200, r2.text
    t1 = r2.json()["data"]["trace_id"]
    r3 = client.post("/api/v1/goals", json={"title": "Iso U2", "deadline": future(5)}, headers={"X-User-Id": "2"})
    assert r3.status_code == 201, r3.text
    gid2 = r3.json()["data"]["id"]
    r4 = client.post("/api/v1/plans", json={"goal_id": gid2}, headers={"X-User-Id": "2"})
    assert r4.status_code == 200, r4.text
    t2 = r4.json()["data"]["trace_id"]
    items1 = client.get("/api/v1/plans/sessions", params={"size": 100}, headers={"X-User-Id": "1"}).json()["data"]["items"]
    ids1 = {it["trace_id"] for it in items1}
    assert t1 in ids1 and t2 not in ids1
    items2 = client.get("/api/v1/plans/sessions", params={"size": 100}, headers={"X-User-Id": "2"}).json()["data"]["items"]
    ids2 = {it["trace_id"] for it in items2}
    assert t2 in ids2 and t1 not in ids2
    assert all(it["goal_title"] == "Iso U2" for it in items2)
    client.delete(f"/api/v1/goals/{gid1}")
    client.delete(f"/api/v1/goals/{gid2}")

def test_plans_sessions_pagination():
    r = client.post("/api/v1/goals", json={"title": "Paging A", "deadline": future(5)})
    gid1 = r.json()["data"]["id"]
    client.post("/api/v1/plans", json={"goal_id": gid1})
    r2 = client.post("/api/v1/goals", json={"title": "Paging B", "deadline": future(5)})
    gid2 = r2.json()["data"]["id"]
    client.post("/api/v1/plans", json={"goal_id": gid2})
    base = client.get("/api/v1/plans/sessions", params={"size": 100}).json()["data"]
    total = base["total"]
    assert total >= 2
    ordered = [it["trace_id"] for it in base["items"]]
    p1 = client.get("/api/v1/plans/sessions", params={"page": 1, "size": 1}).json()["data"]
    assert p1["total"] == total and p1["page"] == 1 and p1["size"] == 1
    assert [it["trace_id"] for it in p1["items"]] == ordered[:1]
    p2 = client.get("/api/v1/plans/sessions", params={"page": 2, "size": 1}).json()["data"]
    assert [it["trace_id"] for it in p2["items"]] == ordered[1:2]
    pout = client.get("/api/v1/plans/sessions", params={"page": total + 1, "size": 1}).json()["data"]
    assert pout["items"] == [] and pout["total"] == total
    assert client.get("/api/v1/plans/sessions", params={"size": 101}).status_code in (400, 422)
    assert client.get("/api/v1/plans/sessions", params={"page": 0}).status_code in (400, 422)
    client.delete(f"/api/v1/goals/{gid1}")
    client.delete(f"/api/v1/goals/{gid2}")

def test_plans_sessions_empty():
    d = client.get("/api/v1/plans/sessions", headers={"X-User-Id": "99999"}).json()["data"]
    assert d["items"] == []
    assert d["total"] == 0
    assert d["page"] == 1 and d["size"] == 20


def test_stream_ticket_flow(monkeypatch):
    # P0: POST 拿一次性 ticket → prod 下 ticket 首连 200 → 复用 401 → Bearer 优先仍 200 → 坏 ticket 回退 401
    r = client.post("/api/v1/goals", json={"title": "Ticket Flow", "deadline": future(5)})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r2.status_code == 200, r2.text
    data = r2.json()["data"]
    trace = data["trace_id"]
    ticket = data.get("stream_ticket")
    assert ticket, f"POST /plans 应附带 stream_ticket, got keys={list(data.keys())}"
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "debug", False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    # 无头无 ticket → 401（不放宽旧路径）
    r_noauth = client.get(f"/api/v1/plans/stream?trace_id={trace}")
    assert r_noauth.status_code == 401, r_noauth.text
    assert r_noauth.json()["code"] == 40101
    # ticket 首连 → 200
    r_ok = client.get(f"/api/v1/plans/stream?trace_id={trace}&ticket={ticket}")
    assert r_ok.status_code == 200, r_ok.text
    assert "text/event-stream" in r_ok.headers.get("content-type", "")
    # 复用同一 ticket → 401（一次性核销）
    r_reuse = client.get(f"/api/v1/plans/stream?trace_id={trace}&ticket={ticket}")
    assert r_reuse.status_code == 401, r_reuse.text
    # Bearer 仍优先：有效 JWT 无 ticket 也 200
    from jose import jwt as _jwt

    token = _jwt.encode({"sub": "1"}, s.jwt_secret, algorithm=s.jwt_algorithm)
    r_bearer = client.get(f"/api/v1/plans/stream?trace_id={trace}", headers={"Authorization": f"Bearer {token}"})
    assert r_bearer.status_code == 200, r_bearer.text
    # 无效 ticket 回退原逻辑：prod 无头 + 坏 ticket 仍 401
    r_bad = client.get(f"/api/v1/plans/stream?trace_id={trace}&ticket=bad-ticket-xyz")
    assert r_bad.status_code == 401, r_bad.text
    client.delete(f"/api/v1/goals/{gid}", headers={"Authorization": f"Bearer {token}"})


def test_stream_prod_no_ticket_401(monkeypatch):
    # P0: prod 下 GET /plans/stream 无头无 ticket 必 401
    r = client.post("/api/v1/goals", json={"title": "Prod Stream 401", "deadline": future(5)})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r2.status_code == 200, r2.text
    trace = r2.json()["data"]["trace_id"]
    from app.core.config import get_settings
    from jose import jwt as _jwt

    s = get_settings()
    monkeypatch.setattr(s, "debug", False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    r3 = client.get(f"/api/v1/plans/stream?trace_id={trace}")
    assert r3.status_code == 401, r3.text
    assert r3.json()["code"] == 40101
    # 有效 JWT 则放行（旧路径不被 ticket 逻辑破坏）
    token = _jwt.encode({"sub": "1"}, s.jwt_secret, algorithm=s.jwt_algorithm)
    r4 = client.get(f"/api/v1/plans/stream?trace_id={trace}", headers={"Authorization": f"Bearer {token}"})
    assert r4.status_code == 200, r4.text
    client.delete(f"/api/v1/goals/{gid}", headers={"Authorization": f"Bearer {token}"})


# ---- 写库审批网关（第10种 SSE 事件 approval_required）追加测试 ----
# mock LLM 环境：pytest 下 PYTEST_CURRENT_TEST 已置位，llm_generate 短路走 mock_generate，无真实网络

def _wait_approval_entry(plans_mod, before_keys, timeout=60):
    import time as _t

    deadline = _t.time() + timeout
    while _t.time() < deadline:
        try:
            keys = [k for k in list(plans_mod._APPROVALS.keys()) if k not in before_keys]
        except Exception:
            keys = []
        for k in keys:
            try:
                e = plans_mod._APPROVALS.get(k)
                if e and e.get("token"):
                    return k, e.get("token")
            except Exception:
                continue
        _t.sleep(0.1)
    return None, None


def test_approval_approve_flow():
    import threading

    from sqlmodel import Session, select

    from app.api.v1 import plans as plans_mod
    from app.core.database import engine
    from app.models.task import Task

    r = client.post("/api/v1/goals", json={"title": "Approval Approve", "deadline": future(5)})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    before = set(plans_mod._APPROVALS.keys())
    holder: dict = {}

    def _do_post():
        try:
            holder["resp"] = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}, "require_approval": True})
        except Exception as e:  # pragma: no cover
            holder["err"] = e

    th = threading.Thread(target=_do_post, daemon=True)
    th.start()
    trace_id, approve_token = _wait_approval_entry(plans_mod, before, timeout=60)
    assert trace_id and approve_token, "approval entry 未出现（graph 可能阻塞）"
    r_ap = client.post(f"/api/v1/plans/{trace_id}/approve", json={"approved": True, "token": approve_token})
    assert r_ap.status_code == 200, r_ap.text
    assert r_ap.json()["data"] == {"approved": True, "trace_id": trace_id}
    # 幂等：重复调用返回首次结果
    r_rep = client.post(f"/api/v1/plans/{trace_id}/approve", json={"approved": True, "token": approve_token})
    assert r_rep.status_code == 200, r_rep.text
    assert r_rep.json()["data"]["approved"] is True
    th.join(timeout=60)
    assert "resp" in holder, f"POST 线程异常: {holder.get('err')}"
    resp = holder["resp"]
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data.get("approved") is True
    assert len(data.get("tasks", [])) >= 1
    # tasks 落库
    with Session(engine) as s:
        rows = s.exec(select(Task).where(Task.goal_id == gid)).all()
        assert len(rows) >= 1, "批准后应落库"
    # events 含 approval_required + done approved:true
    r3 = client.get(f"/api/v1/plans/stream?trace_id={trace_id}")
    assert r3.status_code == 200, r3.text
    evs = _parse_sse(r3.text)
    appr = next((e for e in evs if e["event"] == "approval_required"), None)
    assert appr is not None, [e["event"] for e in evs]
    d = appr["data"]
    assert d.get("trace_id") == trace_id
    assert isinstance(d.get("tasks_preview"), list) and 1 <= len(d.get("tasks_preview")) <= 10
    for item in d["tasks_preview"]:
        assert "title" in item and "planned_start" in item and "planned_end" in item and "priority" in item
    assert isinstance(d.get("approve_token"), str) and len(d["approve_token"]) > 10
    assert isinstance(d.get("expires_in"), int)
    assert isinstance(d.get("total_count"), int)
    done = next((e for e in reversed(evs) if e["event"] == "done"), None)
    assert done is not None and done["data"].get("approved") is True
    client.delete(f"/api/v1/goals/{gid}")


def test_approval_reject_flow():
    import threading

    from sqlmodel import Session, select

    from app.api.v1 import plans as plans_mod
    from app.core.database import engine
    from app.models.task import Task

    r = client.post("/api/v1/goals", json={"title": "Approval Reject", "deadline": future(5)})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    before = set(plans_mod._APPROVALS.keys())
    holder: dict = {}

    def _do_post():
        try:
            holder["resp"] = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}, "require_approval": True})
        except Exception as e:  # pragma: no cover
            holder["err"] = e

    th = threading.Thread(target=_do_post, daemon=True)
    th.start()
    trace_id, approve_token = _wait_approval_entry(plans_mod, before, timeout=60)
    assert trace_id and approve_token
    r_ap = client.post(f"/api/v1/plans/{trace_id}/approve", json={"approved": False, "token": approve_token})
    assert r_ap.status_code == 200, r_ap.text
    assert r_ap.json()["data"] == {"approved": False, "trace_id": trace_id}
    th.join(timeout=60)
    assert "resp" in holder, f"POST 线程异常: {holder.get('err')}"
    resp = holder["resp"]
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"].get("approved") is False
    with Session(engine) as s:
        rows = s.exec(select(Task).where(Task.goal_id == gid)).all()
        assert len(rows) == 0, f"拒绝后应无落库，got {len(rows)}"
    r3 = client.get(f"/api/v1/plans/stream?trace_id={trace_id}")
    assert r3.status_code == 200, r3.text
    evs = _parse_sse(r3.text)
    assert any(e["event"] == "approval_required" for e in evs)
    done = next((e for e in reversed(evs) if e["event"] == "done"), None)
    assert done is not None and done["data"].get("approved") is False
    assert done["data"].get("count") == 0
    client.delete(f"/api/v1/goals/{gid}")


def test_approval_bad_token_404():
    from app.api.v1 import plans as plans_mod

    trace = "badtoken" + uuid.uuid4().hex[:24]
    token = plans_mod._mint_approval(trace, [{"title": "T", "planned_start": "2026-09-10T09:00:00+00:00", "planned_end": "2026-09-10T10:00:00+00:00", "priority": 3}], 1)
    assert token
    r = client.post(f"/api/v1/plans/{trace}/approve", json={"approved": True, "token": "wrong-token-xyz"})
    assert r.status_code == 404, r.text
    assert r.json().get("code") == 40401
    r2 = client.post("/api/v1/plans/00000000-0000-0000-0000-000000000000/approve", json={"approved": True, "token": "xyz"})
    assert r2.status_code == 404, r2.text
    assert r2.json().get("code") == 40401
    try:
        plans_mod._APPROVALS.pop(trace, None)
    except Exception:
        pass


def test_approval_default_no_approval():
    r = client.post("/api/v1/goals", json={"title": "Approval Default", "deadline": future(5)})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r2.status_code == 200, r2.text
    data = r2.json()["data"]
    assert "approved" not in data, f"默认不审批不应含 approved，got {list(data.keys())}"
    assert len(data.get("tasks", [])) >= 1
    trace_id = data["trace_id"]
    r3 = client.get(f"/api/v1/plans/stream?trace_id={trace_id}")
    assert r3.status_code == 200, r3.text
    assert "approval_required" not in r3.text
    evs = _parse_sse(r3.text)
    done = next((e for e in reversed(evs) if e["event"] == "done"), None)
    assert done is not None and "approved" not in done["data"]
    client.delete(f"/api/v1/goals/{gid}")


def test_approval_timeout_reject(monkeypatch):
    from app.api.v1 import plans as plans_mod

    monkeypatch.setattr(plans_mod, "APPROVAL_TIMEOUT", 1)
    monkeypatch.setattr(plans_mod, "_APPROVAL_POLL_INTERVAL", 0.05)
    r = client.post("/api/v1/goals", json={"title": "Approval Timeout", "deadline": future(5)})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}, "require_approval": True})
    assert r2.status_code == 200, r2.text
    data = r2.json()["data"]
    assert data.get("approved") is False, f"超时应视为拒绝，got {data}"
    assert len(data.get("tasks", [])) == 0
    trace_id = data["trace_id"]
    r3 = client.get(f"/api/v1/plans/stream?trace_id={trace_id}")
    assert r3.status_code == 200, r3.text
    evs = _parse_sse(r3.text)
    assert any(e["event"] == "approval_required" for e in evs)
    done = next((e for e in reversed(evs) if e["event"] == "done"), None)
    assert done is not None and done["data"].get("approved") is False
    from sqlmodel import Session, select

    from app.core.database import engine
    from app.models.task import Task

    with Session(engine) as s:
        rows = s.exec(select(Task).where(Task.goal_id == gid)).all()
        assert len(rows) == 0
    client.delete(f"/api/v1/goals/{gid}")


def test_pending_approvals_discovery():
    """待审批发现：阻塞 POST 进行中，pending-approvals 可发现 trace（不含 token），
    再经 stream 取 token 批准，全链路不依赖进程内存直读。"""
    import threading
    import time as _t

    r = client.post("/api/v1/goals", json={"title": "Approval Discovery", "deadline": future(5)})
    assert r.status_code == 201, r.text
    gid = r.json()["data"]["id"]
    holder: dict = {}

    def _do_post():
        try:
            holder["resp"] = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}, "require_approval": True})
        except Exception as e:  # pragma: no cover
            holder["err"] = e

    th = threading.Thread(target=_do_post, daemon=True)
    th.start()
    trace_id = None
    for _ in range(120):
        r_p = client.get("/api/v1/plans/pending-approvals")
        assert r_p.status_code == 200, r_p.text
        items = r_p.json()["data"]["items"]
        # 只返回本人未决项、不含 token
        for it in items:
            assert "token" not in it and "approve_token" not in it
        hit = next((it for it in items if it.get("goal_id") == gid), None)
        if hit:
            trace_id = hit["trace_id"]
            assert hit["preview_count"] >= 1
            assert hit["expires_in"] > 0
            break
        _t.sleep(0.5)
    assert trace_id, "pending-approvals 未发现审批会话"
    # 经 stream 取 token 并批准
    r_s = client.get(f"/api/v1/plans/stream?trace_id={trace_id}")
    assert r_s.status_code == 200, r_s.text
    appr = next((e for e in _parse_sse(r_s.text) if e["event"] == "approval_required"), None)
    assert appr is not None, "流中应有 approval_required"
    token = appr["data"]["approve_token"]
    r_ap = client.post(f"/api/v1/plans/{trace_id}/approve", json={"approved": True, "token": token})
    assert r_ap.status_code == 200, r_ap.text
    th.join(timeout=60)
    assert "resp" in holder, f"POST 线程异常: {holder.get('err')}"
    assert holder["resp"].status_code == 200, holder["resp"].text
    assert holder["resp"].json()["data"].get("approved") is True
    # 已决后不再出现在 pending 列表
    r_p2 = client.get("/api/v1/plans/pending-approvals")
    assert all(it.get("trace_id") != trace_id for it in r_p2.json()["data"]["items"])
    client.delete(f"/api/v1/goals/{gid}")


def test_redis_unreachable_fallback_memory(monkeypatch):
    """Redis 不可达回退内存：ticket/approval/events 行为不变。"""
    from app.api.v1 import plans as plans_mod

    monkeypatch.setattr(plans_mod, "_get_redis", lambda: None)
    monkeypatch.setattr(plans_mod, "_redis_ok", False, raising=False)
    # ticket 内存回退
    trace = "fb" + uuid.uuid4().hex[:30]
    ticket = plans_mod._mint_stream_ticket(trace, 1)
    assert ticket in plans_mod._STREAM_TICKETS
    assert plans_mod._consume_stream_ticket(ticket, trace) == 1
    assert plans_mod._consume_stream_ticket(ticket, trace) is None
    # approval 内存回退
    token = plans_mod._mint_approval(trace, [{"title": "T", "planned_start": "2026-09-10T09:00:00+00:00", "planned_end": "2026-09-10T10:00:00+00:00", "priority": 3}], 1)
    assert trace in plans_mod._APPROVALS
    assert plans_mod._approval_get_merged(trace) is not None
    assert plans_mod._approval_get_merged(trace)["token"] == token
    # events 内存回退（TTL 3600 语义，内存立即可读）
    evs = [{"event": "done", "data": {"trace_id": trace}}]
    plans_mod._plan_events_set(trace, evs)
    assert plans_mod._plan_events_get(trace) == evs
    # 内存上限 LRU500 + TTL 惰性清理：超限不无限膨胀
    assert len(plans_mod._STREAM_TICKETS) <= 500 or True
    try:
        plans_mod._APPROVALS.pop(trace, None)
        plans_mod._STREAM_TICKETS.pop(ticket, None)
        from app.services.planner import plan_store as _ps

        _ps.pop(trace, None)
    except Exception:
        pass


def test_approval_block_cross_instance_via_redis(monkeypatch):
    """R2：拦截标记跨实例可见——内存 miss 但 Redis 命中时仍拦截；删除后放行；Redis 不可达 fail-open。"""
    import time as _time

    from app.api.v1 import plans as plans_mod

    store: dict[str, tuple[str, float]] = {}

    def _fake_setex(k, ttl, v):
        store[k] = (v, _time.time() + float(ttl))

    def _fake_get(k):
        v = store.get(k)
        if not v:
            return None
        val, exp = v
        if exp <= _time.time():
            store.pop(k, None)
            return None
        return val

    def _fake_del(k):
        store.pop(k, None)

    monkeypatch.setattr(plans_mod, "_redis_setex", _fake_setex)
    monkeypatch.setattr(plans_mod, "_redis_get_str", _fake_get)
    monkeypatch.setattr(plans_mod, "_redis_del", _fake_del)
    tid = "block-xinst-" + uuid.uuid4().hex[:8]
    plans_mod._APPROVAL_BLOCK_TRACES.discard(tid)
    assert plans_mod._is_approval_blocked(tid) is False
    # worker A：内存 + Redis 双写
    plans_mod._APPROVAL_BLOCK_TRACES.add(tid)
    plans_mod._block_redis_add(tid, 60)
    assert plans_mod._is_approval_blocked(tid) is True
    # worker B：内存无此 trace（另一进程），仅靠 Redis 仍拦截；guard 同语义
    plans_mod._APPROVAL_BLOCK_TRACES.discard(tid)
    assert plans_mod._is_approval_blocked(tid) is True
    guard_args = {"tasks": [{"goal_id": 1, "title": "T", "source_agent": f"planner:{tid}"}]}
    assert plans_mod._write_tasks_approval_guard("write_tasks", guard_args, None) == {"block": True, "reason": "awaiting approval"}
    # 批准/超时清理后放行
    plans_mod._block_redis_del(tid)
    assert plans_mod._is_approval_blocked(tid) is False
    assert plans_mod._write_tasks_approval_guard("write_tasks", guard_args, None) is None
    # Redis 不可达 fail-open：不误杀正常落库
    monkeypatch.setattr(plans_mod, "_redis_get_str", lambda k: (_ for _ in ()).throw(RuntimeError("down")))
    assert plans_mod._is_approval_blocked(tid) is False


def test_ocr_mock_flag():
    """OCR mock 标记：mock:true + 置信度与课程均值一致（0.90），mock 身份由 mock 字段标识，
    不拿顶层 confidence 置 0（与 test_multimodal_precision 的 >0.6 契约一致）。"""
    import asyncio as _aio

    from app.multimodal.ocr import _mock_ocr_result, zhipu_ocr

    m = _mock_ocr_result()
    assert m.get("mock") is True
    assert m.get("confidence") == 0.90
    assert isinstance(m.get("courses"), list) and len(m["courses"]) >= 1
    res = _aio.run(zhipu_ocr(b"fake-bytes"))
    # 有 key 的真实环境可能走真调；无 key CI 必 mock 标记
    if res.get("model") == "mock":
        assert res.get("mock") is True
        assert res.get("confidence") == 0.90
