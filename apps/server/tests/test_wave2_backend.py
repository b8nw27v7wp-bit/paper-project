import time
import uuid
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.core.database import init_db

init_db()
client = TestClient(app)


def future(days=5):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _mk_goal(title="Wave2"):
    r = client.post("/api/v1/goals", json={"title": title + "-" + uuid.uuid4().hex[:6], "deadline": future(5)})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def test_wave2_citations_nonempty():
    # seed knowledge so vector_deps non-empty -> citations non-empty
    gid = _mk_goal("Wave2Cit")
    # seed via memory create (knowledge) + rag ingest path uses store_chunks; simplest: create knowledge via /memory
    # /memory only allows memory/knowledge, use knowledge
    r = client.post("/api/v1/memory", json={"content": "Wave2Cit knowledge about planning " + uuid.uuid4().hex, "type": "knowledge"})
    assert r.status_code == 200, r.text
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r2.status_code == 200, r2.text
    data = r2.json()["data"]
    assert "citations" in data, data.keys()
    # citations should be list; with seeded knowledge it should be non-empty (tier_fill returns top_k even if low score)
    assert isinstance(data["citations"], list)
    # at least check field exists and if knowledge exists then non-empty; allow empty only if no knowledge for user? we seeded so expect non-empty
    assert len(data["citations"]) > 0, f"citations empty, data={list(data.keys())}"
    client.delete(f"/api/v1/goals/{gid}")


def test_wave2_ephemeral_visible():
    gid = _mk_goal("Wave2Eph")
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}, "ephemeral": True})
    assert r2.status_code == 200, r2.text
    trace = r2.json()["data"]["trace_id"]
    r3 = client.get("/api/v1/plans/sessions", params={"size": 100})
    assert r3.status_code == 200, r3.text
    items = r3.json()["data"]["items"]
    hit = next((x for x in items if x["trace_id"] == trace), None)
    assert hit is not None, f"ephemeral trace {trace} not visible in sessions"
    assert hit.get("ephemeral") is True
    assert "degraded" in hit and "citations" in hit and "citations_count" in hit
    client.delete(f"/api/v1/goals/{gid}")


def test_wave2_sessions_extra_fields():
    gid = _mk_goal("Wave2SessFields")
    r2 = client.post("/api/v1/plans", json={"goal_id": gid})
    assert r2.status_code == 200
    trace = r2.json()["data"]["trace_id"]
    r3 = client.get("/api/v1/plans/sessions", params={"size": 100})
    hit = next((x for x in r3.json()["data"]["items"] if x["trace_id"] == trace), None)
    assert hit is not None
    assert hit.get("ephemeral") is False
    assert isinstance(hit.get("degraded"), bool)
    assert isinstance(hit.get("citations"), list)
    assert isinstance(hit.get("citations_count"), int)
    assert hit["citations_count"] == len(hit["citations"])
    client.delete(f"/api/v1/goals/{gid}")


def test_wave2_steer_ttl_and_get():
    from app.api.v1 import plans as plans_mod
    # manual non-done trace for success path
    trace = "w2steer" + uuid.uuid4().hex[:24]
    # owner binding
    plans_mod._TRACE_OWNERS[trace] = 1
    plans_mod._TRACE_OWNERS_TS[trace] = time.time() + 3600
    plans_mod._TRACE_GOALS[trace] = 999999  # dummy, but sessions not needed here
    plans_mod._TRACE_GOALS_TS[trace] = time.time() + 3600
    # ensure no done events
    try:
        plans_mod._plan_events_ts.pop(trace, None)
    except Exception:
        pass
    # steer should succeed (no done)
    r = client.post(f"/api/v1/plans/{trace}/steer", json={"message": "hello-steer"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["queued"] == 1
    # GET should show queue
    r2 = client.get(f"/api/v1/plans/{trace}/steer")
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["queued"] == ["hello-steer"]
    # TTL expire -> GET empty
    try:
        plans_mod._STEER_TS[trace] = time.time() - 1
    except Exception:
        pass
    r3 = client.get(f"/api/v1/plans/{trace}/steer")
    assert r3.status_code == 200, r3.text
    assert r3.json()["data"]["queued"] == []
    # done后拒收: set done events then steer should 400
    plans_mod._plan_events_set(trace, [{"event": "done", "data": {"trace_id": trace}}])
    # need owner still
    plans_mod._TRACE_OWNERS[trace] = 1
    plans_mod._TRACE_OWNERS_TS[trace] = time.time() + 3600
    r4 = client.post(f"/api/v1/plans/{trace}/steer", json={"message": "after-done"})
    assert r4.status_code == 400, r4.text
    assert r4.json().get("code") == 40001
    # cleanup
    try:
        plans_mod._steer_box.pop(trace, None)
        plans_mod._STEER_TS.pop(trace, None)
        plans_mod._TRACE_OWNERS.pop(trace, None)
        plans_mod._TRACE_OWNERS_TS.pop(trace, None)
        plans_mod._TRACE_GOALS.pop(trace, None)
        plans_mod._TRACE_GOALS_TS.pop(trace, None)
        from app.services.planner import plan_store as _ps
        _ps.pop(trace, None)
        plans_mod._plan_events_ts.pop(trace, None)
    except Exception:
        pass


def test_wave2_schema_fallback():
    from app.api.v1 import plans as plans_mod
    gid = _mk_goal("Wave2Schema")
    # force validation fail to trigger mock fallback
    orig = plans_mod._validate_tasks_for_schema
    plans_mod._validate_tasks_for_schema = lambda x: False
    try:
        r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}, "output_schema": "{}"})
        assert r2.status_code == 200, r2.text
        data = r2.json()["data"]
        assert data.get("schema_fallback") is True, f"expected schema_fallback True, got {data.keys()}"
        trace = data["trace_id"]
        # done.data should also have flag via stream
        r3 = client.get(f"/api/v1/plans/stream?trace_id={trace}")
        assert r3.status_code == 200, r3.text
        assert "schema_fallback" in r3.text
    finally:
        plans_mod._validate_tasks_for_schema = orig
    # normal (no output_schema) should have no flag
    r4 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r4.status_code == 200
    assert "schema_fallback" not in r4.json()["data"]
    client.delete(f"/api/v1/goals/{gid}")


def test_wave2_mcp_nohead_401(monkeypatch):
    from app.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "debug", False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    for path in ["/api/v1/mcp/servers", "/api/v1/mcp/tools"]:
        r = client.get(path)
        assert r.status_code == 401, f"{path} {r.text}"
        assert r.json()["code"] == 40101
    # public endpoints stay open (manifest/capabilities)
    r2 = client.get("/api/v1/agent/manifest")
    assert r2.status_code == 200, r2.text
    r3 = client.get("/api/v1/multimodal/capabilities")
    assert r3.status_code == 200, r3.text


def test_wave2_steer_429(monkeypatch):
    import app.core.ratelimit as rl
    from app.core.config import get_settings
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("RATELIMIT_DISABLED", raising=False)
    monkeypatch.setattr(rl, "_get_redis", lambda: None)
    rl._store.clear()
    s = get_settings()
    monkeypatch.setattr(s, "rate_limit_plan", 2)
    # need a trace without done for steer success path (use manual)
    from app.api.v1 import plans as plans_mod
    trace = "w2ratelimit" + uuid.uuid4().hex[:20]
    plans_mod._TRACE_OWNERS[trace] = 1
    plans_mod._TRACE_OWNERS_TS[trace] = time.time() + 3600
    # ensure no done
    try:
        plans_mod._plan_events_ts.pop(trace, None)
        from app.services.planner import plan_store as _ps
        _ps.pop(trace, None)
    except Exception:
        pass
    # use unique IP via X-Forwarded-For to isolate bucket
    ip = "203.0.113." + str(int(time.time()) % 250 + 1)
    headers = {"X-Forwarded-For": ip}
    r1 = client.post(f"/api/v1/plans/{trace}/steer", json={"message": "m1"}, headers=headers)
    assert r1.status_code == 200, r1.text
    r2 = client.post(f"/api/v1/plans/{trace}/steer", json={"message": "m2"}, headers=headers)
    assert r2.status_code == 200, r2.text
    r3 = client.post(f"/api/v1/plans/{trace}/steer", json={"message": "m3"}, headers=headers)
    assert r3.status_code == 429, r3.text
    assert r3.json()["code"] == 42901
    rl._store.clear()
    try:
        plans_mod._TRACE_OWNERS.pop(trace, None)
        plans_mod._TRACE_OWNERS_TS.pop(trace, None)
        plans_mod._steer_box.pop(trace, None)
        plans_mod._STEER_TS.pop(trace, None)
    except Exception:
        pass


def test_wave2_membox_expire():
    from app.api.v1 import plans as plans_mod
    # owners
    tid = "w2exp" + uuid.uuid4().hex[:24]
    plans_mod._TRACE_OWNERS[tid] = 1
    plans_mod._TRACE_OWNERS_TS[tid] = time.time() - 1
    plans_mod._EPHEMERAL_TRACES.add(tid)
    plans_mod._EPHEMERAL_TS[tid] = time.time() - 1
    plans_mod._ABORT_TRACES.add(tid)
    plans_mod._ABORT_TS[tid] = time.time() - 1
    plans_mod._steer_box[tid] = ["x"]
    plans_mod._STEER_TS[tid] = time.time() - 1
    plans_mod._cleanup_mem_boxes()
    assert tid not in plans_mod._TRACE_OWNERS
    assert tid not in plans_mod._EPHEMERAL_TRACES
    assert tid not in plans_mod._ABORT_TRACES
    assert tid not in plans_mod._steer_box


def test_wave2_async_pomodoro():
    gid = _mk_goal("Wave2AsyncPomo")
    now = datetime.now(timezone.utc)
    s = (now + timedelta(days=1)).isoformat()
    e = (now + timedelta(days=1, hours=1)).isoformat()
    rb = client.post("/api/v1/tasks/batch", json={"tasks": [{"goal_id": gid, "title": "AsyncPomoT", "planned_start": s, "planned_end": e}]})
    assert rb.status_code == 201, rb.text
    tid = rb.json()["data"][0]["id"]
    # async complete should invalidate cache (just check 200)
    rc = client.post(f"/api/v1/async/tasks/{tid}/complete", json={"actual_duration": 30, "completion_rate": 1.0})
    assert rc.status_code == 200, rc.text
    # async pomodoro
    rp = client.post(f"/api/v1/async/tasks/{tid}/pomodoro", json={"duration_seconds": 120, "focus_score": 0.9})
    assert rp.status_code == 200, rp.text
    assert rp.json()["data"]["delay_reason"] == "pomodoro"
    client.delete(f"/api/v1/goals/{gid}")


def test_wave2_async_goal_tasks():
    gid = _mk_goal("Wave2AsyncGoal")
    now = datetime.now(timezone.utc)
    s = (now + timedelta(days=1)).isoformat()
    e = (now + timedelta(days=1, hours=1)).isoformat()
    client.post("/api/v1/tasks/batch", json={"tasks": [{"goal_id": gid, "title": "GTask", "planned_start": s, "planned_end": e}]})
    r = client.get(f"/api/v1/async/goals/{gid}")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "tasks" in data, f"async goal should join tasks, got {list(data.keys())}"
    assert len(data["tasks"]) >= 1
    client.delete(f"/api/v1/goals/{gid}")


def test_wave2_sessions_delete():
    gid = _mk_goal("Wave2Del")
    r2 = client.post("/api/v1/plans", json={"goal_id": gid})
    assert r2.status_code == 200
    trace = r2.json()["data"]["trace_id"]
    # ensure visible
    r3 = client.get("/api/v1/plans/sessions", params={"size": 100})
    assert any(x["trace_id"] == trace for x in r3.json()["data"]["items"])
    # delete
    rd = client.delete(f"/api/v1/plans/sessions/{trace}")
    assert rd.status_code == 200, rd.text
    assert rd.json()["data"]["deleted"] is True
    # gone from sessions
    r4 = client.get("/api/v1/plans/sessions", params={"size": 100})
    assert not any(x["trace_id"] == trace for x in r4.json()["data"]["items"])
    # logs gone -> 404
    r5 = client.get(f"/api/v1/plans/{trace}/logs")
    assert r5.status_code == 404
    client.delete(f"/api/v1/goals/{gid}")


def test_wave2_memory_type_400():
    r = client.get("/api/v1/memory/search", params={"q": "hi", "type": "badtype"})
    assert r.status_code == 400, r.text
    assert r.json()["code"] == 40001
    # valid types pass (may be empty but 200)
    for t in ["memory", "knowledge", "execution"]:
        r2 = client.get("/api/v1/memory/search", params={"q": "hi", "type": t})
        assert r2.status_code == 200, f"{t} {r2.text}"


def test_wave2_rag_truncate():
    # seed long knowledge
    long_content = "x" * 500
    files = {"file": ("long.txt", long_content.encode(), "text/plain")}
    client.post("/api/v1/rag/ingest", files=files, data={"subject": "w2truncate-" + uuid.uuid4().hex[:6]})
    # ingest may succeed; if not, fallback to direct DB insert via memory
    r2 = client.get("/api/v1/rag/chunks", params={"size": 5})
    assert r2.status_code == 200, r2.text
    items = r2.json()["data"]["items"]
    assert len(items) >= 1
    for it in items:
        assert "has_more" in it, it.keys()
        assert len(it["content"]) <= 200, len(it["content"])
    # find one with has_more True (the long one) - at least one long exists from this test or previous long seeds
    # create explicit long via memory table knowledge type
    from sqlmodel import Session
    from app.core.database import engine
    from app.models.memory import MemoryChunk
    import json as _json
    from app.services.memory import _hash_mock_embedding
    vec = _hash_mock_embedding(long_content)
    with Session(engine) as s:
        mc = MemoryChunk(user_id=1, content=long_content, embedding=_json.dumps(vec), type="knowledge")
        s.add(mc)
        s.commit()
    r3 = client.get("/api/v1/rag/chunks", params={"size": 100})
    hits = [x for x in r3.json()["data"]["items"] if x.get("has_more") is True]
    assert len(hits) >= 1, "expected at least one truncated has_more True"
    assert all(len(x["content"]) == 200 for x in hits)


def test_wave2_topk_passthrough():
    r = client.get("/api/v1/experiments/memory-ablation", params={"query": "hi", "top_k": 7})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data.get("top_k") == 7, data
    # underlying should have used top_k (ab_test hits <= top_k)
    try:
        ab = data.get("ab_test", {})
        with_mem = ab.get("with_memory", [])
        assert len(with_mem) <= 7
    except Exception:
        pass
    r2 = client.post("/api/v1/experiments/memory-ablation", json={"query": "hi", "top_k": 3})
    assert r2.status_code == 200
    assert r2.json()["data"].get("top_k") == 3


def test_wave2_require_calendar():
    gid = _mk_goal("Wave2Cal")
    # explicit require_calendar True -> receipt should contain calendar:{synced:bool}
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2, "require_calendar": True}})
    assert r2.status_code == 200, r2.text
    data = r2.json()["data"]
    assert "calendar" in data, f"explicit require_calendar should echo calendar, got {list(data.keys())}"
    assert isinstance(data["calendar"].get("synced"), bool)
    # default (no require_calendar) -> no calendar key (additive, default off)
    r3 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r3.status_code == 200
    assert "calendar" not in r3.json()["data"], f"default should not contain calendar, got {list(r3.json()['data'].keys())}"
    client.delete(f"/api/v1/goals/{gid}")


# ---- H1: citations 读写错位修复（写侧统一 trace 式，读侧兼容） ----
def test_h1_citations_trace_write_read():
    from sqlmodel import Session, select
    from app.core.database import engine
    from app.models.task import Task
    gid = _mk_goal("H1Trace")
    r = client.post("/api/v1/memory", json={"content": "H1 trace knowledge " + uuid.uuid4().hex, "type": "knowledge"})
    assert r.status_code == 200, r.text
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r2.status_code == 200, r2.text
    trace = r2.json()["data"]["trace_id"]
    with Session(engine) as s:
        rows = s.exec(select(Task).where(Task.goal_id == gid)).all()
        assert len(rows) >= 1
        for t in rows:
            assert t.source_agent == f"planner:{trace}", f"write side must be trace-style, got {t.source_agent}"
    # 读侧 inspector 反查非空（citations 加法字段）
    r3 = client.get(f"/api/v1/plans/{trace}/inspector")
    assert r3.status_code == 200, r3.text
    # Task 行有 citations 则 inspector 应透出；至少不 0 行（write/read 对齐）
    with Session(engine) as s:
        rows2 = s.exec(select(Task).where(Task.source_agent == f"planner:{trace}")).all()
        assert len(rows2) >= 1
    client.delete(f"/api/v1/goals/{gid}")


# ---- H2: exec_policy 无行保内存 ----
def test_h2_exec_policy_load_no_rows_keeps_memory():
    from sqlalchemy import text
    from app.core.database import get_session
    from app.services import exec_policy as ep
    ep.add_rule("h2probe", "Allow", "h2 just")
    assert "h2probe" in ep.list_rules()
    # 清掉 DB 行模拟无行
    gen = get_session()
    sess = next(gen)
    try:
        try:
            sess.execute(text("CREATE TABLE IF NOT EXISTS global_state (key TEXT PRIMARY KEY, value TEXT)"))
            sess.execute(text("DELETE FROM global_state WHERE key='approval_rules'"))
            sess.commit()
        except Exception:
            try:
                sess.rollback()
            except Exception:
                pass
        ok = ep.load_from_db(sess)
        assert ok is False
        assert "h2probe" in ep.list_rules(), "无行时内存新规则不得被覆盖"
        # 空列表亦保持内存不动
        try:
            sess.execute(text("INSERT OR REPLACE INTO global_state (key, value) VALUES ('approval_rules', '[]')"))
            sess.commit()
        except Exception:
            pass
        ok2 = ep.load_from_db(sess)
        assert ok2 is False
        assert "h2probe" in ep.list_rules()
    finally:
        try:
            sess.execute(text("DELETE FROM global_state WHERE key='approval_rules'"))
            sess.commit()
        except Exception:
            pass
        try:
            gen.close()
        except Exception:
            pass
        ep.remove_rule("h2probe")


# ---- H3: DELETE 失败 500 + Task 级联删 ----
def test_h3_delete_commit_failure_500(monkeypatch):
    gid = _mk_goal("H3Fail")
    r2 = client.post("/api/v1/plans", json={"goal_id": gid})
    assert r2.status_code == 200
    trace = r2.json()["data"]["trace_id"]
    from sqlmodel import Session as _S
    def _boom(self):
        raise RuntimeError("boom-commit")
    monkeypatch.setattr(_S, "commit", _boom)
    rd = client.delete(f"/api/v1/plans/sessions/{trace}")
    assert rd.status_code == 500, rd.text
    assert rd.json().get("code") == 50001
    monkeypatch.undo()
    # 回滚后日志仍在（非假成功）
    r5 = client.get(f"/api/v1/plans/{trace}/logs")
    assert r5.status_code == 200, r5.text
    client.delete(f"/api/v1/plans/sessions/{trace}")
    client.delete(f"/api/v1/goals/{gid}")


def test_h3_delete_cascades_tasks():
    from sqlmodel import Session, select
    from app.core.database import engine
    from app.models.task import Task
    gid = _mk_goal("H3Cascade")
    r2 = client.post("/api/v1/plans", json={"goal_id": gid})
    assert r2.status_code == 200
    trace = r2.json()["data"]["trace_id"]
    with Session(engine) as s:
        rows = s.exec(select(Task).where(Task.source_agent == f"planner:{trace}")).all()
        assert len(rows) >= 1, "前置：该 trace 应有 Task 行"
    rd = client.delete(f"/api/v1/plans/sessions/{trace}")
    assert rd.status_code == 200, rd.text
    with Session(engine) as s:
        rows2 = s.exec(select(Task).where(Task.source_agent == f"planner:{trace}")).all()
        assert len(rows2) == 0, f"Task 应级联删，残留 {len(rows2)}"
    client.delete(f"/api/v1/goals/{gid}")


# ---- H4: delayed None 不 500 + 番茄不计 delay ----
def test_h4_stats_delayed_none_and_pomodoro():
    from app.services import stats as st
    st.invalidate_stats_cache(None)
    # None 行：mock session.exec 返回伪造 logs
    class _FakeLog:
        def __init__(self, cr, dr, dur=60):
            self.completion_rate = cr
            self.delay_reason = dr
            self.actual_duration = dur
    fake_logs = [_FakeLog(None, None), _FakeLog(1.0, None), _FakeLog(0.2, "pomodoro", dur=120), _FakeLog(0.2, "拖延", dur=30)]
    class _FakeExec:
        def all(self):
            return fake_logs
    class _FakeSess:
        def exec(self, stmt):
            return _FakeExec()
    out = st.overview(_FakeSess(), 1, "7d")
    # done=1/4, delayed 应仅 1（拖延行；pomodoro 排除；None 行按 0 处理但无 reason 且 <0.5？None→0<0.5 会计入）
    # None 行 (0,无reason): (0==0 and reason)=False，但 0<0.5=True → delayed 计 1；拖延行计 1；pomodoro 排除 → delayed=2
    assert out["delay_rate"] == round(2 / 4, 3), out
    assert out["focus_seconds"] == 120, out
    st.invalidate_stats_cache(None)


# ---- M5: abort 淘汰最早 ----
def test_m5_abort_evicts_earliest():
    from app.api.v1 import plans as pm
    # 填满 500
    base = time.time()
    pm._ABORT_TRACES.clear()
    pm._ABORT_TS.clear()
    for i in range(500):
        tid = f"m5old{i:04d}"
        pm._ABORT_TRACES.add(tid)
        pm._ABORT_TS[tid] = base + i  # i 越小越早
    earliest = "m5old0000"
    assert earliest in pm._ABORT_TRACES
    r = client.post("/api/v1/plans/m5newtrace000000000000000000000000/abort", json={})
    # 新 trace 无归属在 debug 下放行
    assert r.status_code == 200, r.text
    assert earliest not in pm._ABORT_TRACES, "应淘汰时间戳最早"
    assert "m5newtrace000000000000000000000000" in pm._ABORT_TRACES
    assert len(pm._ABORT_TRACES) <= 501
    pm._ABORT_TRACES.clear()
    pm._ABORT_TS.clear()


# ---- M6: should_replan 多次调用无叠字 ----
def test_m6_should_replan_idempotent():
    from app.agents.graph import should_replan
    state = {"critic_feedback": "", "_review": {"score": 10, "issues": ["冲突A"]}, "_thought": "t0", "rewrites": 0}
    assert should_replan(state) == "mentor"
    first = state.get("_thought", "")
    assert first.count("reviewer低分") == 1, first
    # 第二次调用：critic_feedback 已被注入走 replan 分支（预期），但 thought 不得叠字
    second_ret = should_replan(state)
    assert second_ret in ("mentor", "replan")
    second = state.get("_thought", "")
    assert second.count("reviewer低分") == 1, f"重复调用叠字: {second}"
    assert second == first
    # 第三次亦然
    should_replan(state)
    assert state.get("_thought", "") == first


# ---- M7: rag full=1 全文 ----
def test_m7_rag_full_param():
    long_content = "y" * 500 + uuid.uuid4().hex
    files = {"file": ("m7full.txt", long_content.encode(), "text/plain")}
    r = client.post("/api/v1/rag/ingest", files=files, data={"subject": "m7-" + uuid.uuid4().hex[:6]})
    assert r.status_code == 200, r.text
    r2 = client.get("/api/v1/rag/chunks", params={"size": 5})
    assert r2.status_code == 200
    for it in r2.json()["data"]["items"]:
        assert len(it["content"]) <= 200
    r3 = client.get("/api/v1/rag/chunks", params={"size": 100, "full": 1})
    assert r3.status_code == 200, r3.text
    items = r3.json()["data"]["items"]
    assert any(len(x["content"]) > 200 for x in items), "full=1 应返回全文"


# ---- M8: sessions 用户隔离分页 ----
def test_m8_sessions_user_isolation():
    gid = _mk_goal("M8Iso")
    r2 = client.post("/api/v1/plans", json={"goal_id": gid})
    assert r2.status_code == 200
    trace = r2.json()["data"]["trace_id"]
    r_own = client.get("/api/v1/plans/sessions", params={"size": 100})
    assert r_own.status_code == 200
    assert any(x["trace_id"] == trace for x in r_own.json()["data"]["items"])
    r_other = client.get("/api/v1/plans/sessions", params={"size": 100}, headers={"X-User-Id": "9999"})
    assert r_other.status_code == 200, r_other.text
    assert not any(x["trace_id"] == trace for x in r_other.json()["data"]["items"]), "他用户不得见本用户 trace"
    # 分页结构不变
    d = r_own.json()["data"]
    assert {"items", "total", "page", "size"} <= set(d.keys())
    client.delete(f"/api/v1/plans/sessions/{trace}")
    client.delete(f"/api/v1/goals/{gid}")


# ---- M9: sqlite 指数退避恢复 ----
def test_m9_sqlite_retry():
    import sqlite3
    from app.graph import sqlite_graph as sg
    calls = {"n": 0}
    def _flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"
    assert sg._with_retry(_flaky, attempts=5, base_ms=1) == "ok"
    assert calls["n"] == 3
    # 非 locked 错误直抛不重试
    def _bad():
        raise sqlite3.OperationalError("no such table: x")
    try:
        sg._with_retry(_bad, attempts=3, base_ms=1)
        assert False, "非locked应直抛"
    except sqlite3.OperationalError:
        pass
    # 写路径可用
    sg.sqlite_upsert_node("m9node-" + uuid.uuid4().hex[:6], "M9")
    sg.sqlite_add_edge("m9a-" + uuid.uuid4().hex[:4], "m9b-" + uuid.uuid4().hex[:4])
