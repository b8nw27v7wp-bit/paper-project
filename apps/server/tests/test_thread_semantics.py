"""Wave B 会话语义：Codex对标 exec cli + thread/resume + rollout三元组 5用例。

1. resume直通（trace_id/name/--last）
2. fork新id+forked_from_seq
3. ephemeral不写库不写Redis（只内存+SSE）
4. after_seq增量续播
5. rollout过滤纯函数
单轨mode=single走mock，无真实网络，快速可测。
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.v1 import plans as plans_mod
from app.core.database import engine, init_db
from app.main import app
from app.models.log import AgentRunLog
from app.models.task import Task

init_db()
client = TestClient(app)


def future(days=5):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _mk_goal(title: str) -> int:
    r = client.post("/api/v1/goals", json={"title": title, "deadline": future(5)})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def _post_single(gid: int, body_extra: dict | None = None):
    body = {"goal_id": gid, "preferences": {"hours_per_day": 2}}
    if body_extra:
        body.update(body_extra)
    r = client.post("/api/v1/plans?mode=single", json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_1_resume_passthrough():
    """resume直通：trace_id直通同id；标题匹配同id；--last为最近trace。"""
    uniq = "ResumeDirect-" + uuid.uuid4().hex[:8]
    gid = _mk_goal(uniq)
    d1 = _post_single(gid)
    trace = d1["trace_id"]
    assert trace
    # trace_id直通
    d2 = _post_single(gid, {"resume": trace})
    assert d2["trace_id"] == trace
    # 标题匹配（goal标题contains）
    d3 = _post_single(gid, {"resume": uniq})
    assert d3["trace_id"] == trace
    # --last按用户最近trace（刚创建的即最近，至少能解析到本人trace）
    d4 = _post_single(gid, {"resume": "--last"})
    assert isinstance(d4["trace_id"], str) and d4["trace_id"]
    # 非法resume 404
    r_bad = client.post("/api/v1/plans?mode=single", json={"goal_id": gid, "resume": "no-such-trace-xyz"})
    assert r_bad.status_code == 404
    client.delete(f"/api/v1/goals/{gid}")


def test_2_fork_new_id_and_seq():
    """fork=true时新trace_id并记forked_from_seq（取源events长度）。"""
    uniq = "ForkSrc-" + uuid.uuid4().hex[:8]
    gid = _mk_goal(uniq)
    d1 = _post_single(gid)
    src = d1["trace_id"]
    # 源events长度（增量接口total）
    r_ev = client.get(f"/api/v1/plans/{src}/events", params={"after_seq": 0})
    assert r_ev.status_code == 200, r_ev.text
    total = r_ev.json()["data"]["total"]
    assert total >= 5
    # fork
    d2 = _post_single(gid, {"resume": src, "fork": True})
    assert d2["trace_id"] != src
    assert d2.get("forked_from") == src
    assert d2.get("forked_from_seq") == total
    # done事件同样附fork标记
    r_last = client.get(f"/api/v1/plans/{d2['trace_id']}/last")
    assert r_last.status_code == 200, r_last.text
    done = r_last.json()["data"]["done"]
    assert done.get("forked_from") == src
    assert done.get("forked_from_seq") == total
    client.delete(f"/api/v1/goals/{gid}")


def test_3_ephemeral_no_db_no_redis():
    """ephemeral=true只走内存+SSE，不写DB（Task/agent_run_log跳过）不写Redis。"""
    from app.core import cache as cache_mod

    uniq = "Ephemeral-" + uuid.uuid4().hex[:8]
    gid = _mk_goal(uniq)
    with Session(engine) as s:
        tasks_before = len(s.exec(select(Task).where(Task.goal_id == gid)).all())
        logs_before = len(s.exec(select(AgentRunLog)).all())
    d = _post_single(gid, {"ephemeral": True})
    trace = d["trace_id"]
    assert len(d.get("tasks", [])) >= 1
    # DB未写
    with Session(engine) as s:
        tasks_after = len(s.exec(select(Task).where(Task.goal_id == gid)).all())
        logs_after = len(s.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace)).all())
        assert tasks_after == tasks_before
        assert logs_after == 0
    # 内存有（plan_store），Redis/cache无（workbench内存回退亦跳过）
    from app.services.planner import plan_store as _ps

    assert trace in _ps and isinstance(_ps.get(trace), list)
    assert cache_mod.get_workbench(trace) is None
    # 增量接口仍可经plan_store读到（内存+SSE语义）
    r_ev = client.get(f"/api/v1/plans/{trace}/events", params={"after_seq": 0})
    assert r_ev.status_code == 200, r_ev.text
    assert r_ev.json()["data"]["total"] >= 5
    # 清理内存避免污染
    try:
        _ps.pop(trace, None)
    except Exception:
        pass
    client.delete(f"/api/v1/goals/{gid}")


def test_4_after_seq_incremental_and_last():
    """after_seq增量续播（seq为下标）与last终态聚合。"""
    uniq = "AfterSeq-" + uuid.uuid4().hex[:8]
    gid = _mk_goal(uniq)
    d = _post_single(gid)
    trace = d["trace_id"]
    r_all = client.get(f"/api/v1/plans/{trace}/events", params={"after_seq": 0})
    assert r_all.status_code == 200, r_all.text
    all_evs = r_all.json()["data"]["events"]
    total = r_all.json()["data"]["total"]
    assert total == len(all_evs) and total >= 5
    # 增量：after_seq=2返回events[2:]
    r_inc = client.get(f"/api/v1/plans/{trace}/events", params={"after_seq": 2})
    assert r_inc.status_code == 200, r_inc.text
    inc_evs = r_inc.json()["data"]["events"]
    assert inc_evs == all_evs[2:]
    assert r_inc.json()["data"]["next_seq"] == total
    # 越界返回空
    r_oob = client.get(f"/api/v1/plans/{trace}/events", params={"after_seq": total + 10})
    assert r_oob.status_code == 200
    assert r_oob.json()["data"]["events"] == []
    # last：task_created聚合+done
    r_last = client.get(f"/api/v1/plans/{trace}/last")
    assert r_last.status_code == 200, r_last.text
    last = r_last.json()["data"]
    assert last["trace_id"] == trace
    assert last["count"] == len(last["tasks"]) >= 1
    assert isinstance(last["done"], dict) and last["done"].get("trace_id") == trace
    for t in last["tasks"]:
        assert t.get("title") and t.get("planned_start") and t.get("planned_end")
    client.delete(f"/api/v1/goals/{gid}")


def test_5_rollout_filter_pure():
    """rollout落盘过滤纯函数：剔除researcher tool_call_start，只留end与其他。"""
    evs = [
        {"event": "thought", "data": {"agent": "planner", "text": "hi"}},
        {"event": "tool_call_start", "data": {"tool": "researcher", "agent": "researcher", "args": {}}},
        {"event": "tool_call", "data": {"tool": "researcher", "args": {}}},
        {"event": "tool_call_start", "data": {"tool": "memory_search", "agent": "researcher", "args": {}}},
        {"event": "tool_call_end", "data": {"tool": "memory_search", "agent": "researcher", "result": {}}},
        {"event": "tool_call_start", "data": {"tool": "rag_search", "agent": "researcher", "args": {}}},
        {"event": "tool_call_end", "data": {"tool": "rag_search", "agent": "researcher", "result": {}}},
        {"event": "tool_call_end", "data": {"tool": "researcher", "agent": "researcher", "result": {}}},
        {"event": "tool_call_start", "data": {"tool": "planner_generate", "agent": "planner", "args": {}}},
        {"event": "task_created", "data": {"task": {"title": "T"}}},
        {"event": "done", "data": {"trace_id": "x"}},
    ]
    out = plans_mod.filter_rollout(evs)
    # 原list不动
    assert len(evs) == 11
    # 3条researcher start被剔除，planner start保留
    assert len(out) == 8
    assert not any(e.get("event") == "tool_call_start" and isinstance(e.get("data"), dict) and e["data"].get("agent") == "researcher" for e in out)
    assert any(e.get("event") == "tool_call_end" and e.get("data", {}).get("agent") == "researcher" for e in out)
    assert any(e.get("event") == "tool_call_start" and e.get("data", {}).get("agent") == "planner" for e in out)
    assert out[0]["event"] == "thought" and out[-1]["event"] == "done"
    # 空/坏输入不抛错
    assert plans_mod.filter_rollout([]) == []
    assert plans_mod.filter_rollout(None) == []
