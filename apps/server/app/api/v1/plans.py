import asyncio
import json
import logging
import os
import secrets
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

from app.agents.graph import graph as multi_graph
from app.core.cache import get_graph as cache_get_graph, get_workbench as cache_get_workbench, set_graph as cache_set_graph, set_workbench as cache_set_workbench
from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.core.ratelimit import check_rate_limit
from app.models.goal import LearningGoal
from app.models.log import AgentRunLog
from app.models.plan import ApproveRequest, PlanCreate
from app.models.task import Task
from app.services import exec_policy as _exec_policy
from app.services.exec_policy import Decision as _Decision
from app.services.memory import search_memory
from app.services.planner import generate_plan, plan_store

router = APIRouter()
logger = logging.getLogger("app.plans")

# 内存迁移（Redis 优先、内存回退）：plan:approval:{trace} TTL300 / plan:ticket:{t} TTL60 / plan:events:{trace} TTL3600
# Redis 不可达回退现有内存 dict（行为不变）；内存 dict 加上限 LRU500 + TTL 惰性清理。对外语义零变化。
_MEM_CAP = 500
_PLAN_EVENTS_TTL = 3600
_REDIS_COOLDOWN = 30
_redis_client = None
_redis_ok = None
_redis_last_try = 0.0


def _get_redis():
    global _redis_client, _redis_ok, _redis_last_try
    now = time.time()
    try:
        if _redis_ok is True and _redis_client is not None:
            return _redis_client
        if _redis_ok is False and (now - float(_redis_last_try)) < _REDIS_COOLDOWN:
            return None
    except Exception:
        pass
    try:
        import redis  # type: ignore

        from app.core.config import get_settings as _gs

        _s = _gs()
        client = redis.from_url(_s.redis_url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5)
        client.ping()
        _redis_client = client
        _redis_ok = True
        _redis_last_try = now
        return client
    except Exception:
        _redis_ok = False
        _redis_client = None
        _redis_last_try = now
        return None


def _mark_redis_dead() -> None:
    global _redis_ok, _redis_client, _redis_last_try
    _redis_ok = False
    _redis_client = None
    try:
        _redis_last_try = time.time()
    except Exception:
        pass


def _enforce_mem_cap(d: dict) -> None:
    try:
        if len(d) <= _MEM_CAP:
            return
        now = time.time()
        for k in [k for k, v in list(d.items()) if isinstance(v, dict) and float(v.get("exp", 0)) <= now]:
            try:
                d.pop(k, None)
            except Exception:
                pass
        while len(d) > _MEM_CAP:
            try:
                oldest = next(iter(d))
                d.pop(oldest, None)
            except StopIteration:
                break
            except Exception:
                break
    except Exception:
        pass


def _redis_setex(key: str, ttl: int, val: str) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(key, int(ttl), val)
    except Exception:
        _mark_redis_dead()


def _redis_get_str(key: str) -> str | None:
    r = _get_redis()
    if r is None:
        return None
    try:
        v = r.get(key)
        return v if isinstance(v, str) else None
    except Exception:
        _mark_redis_dead()
        return None


def _redis_del(key: str) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.delete(key)
    except Exception:
        _mark_redis_dead()


_plan_events_ts: dict[str, float] = {}

# S10 steering one-at-a-time：trace 级追问队列（内存，单条消费，取完即删）
_steer_box: dict[str, list[str]] = {}
_STEER_TTL = 300
_STEER_TS: dict[str, float] = {}

# Wave1 P0 中断盒：POST /plans/{trace_id}/abort 置位，_astream 每 chunk 检查（state 不可达故经内存盒透传）
_ABORT_TRACES: set[str] = set()
_ABORT_TTL = 3600
_ABORT_TS: dict[str, float] = {}

# Wave B 所有权绑定（内存）：trace_id -> user_id，供 steer/events/last 在日志落库前校验
# （_resolve_trace_user 依赖 agent_run_log，pending/ephemeral 期无日志时回退本表；legacy 无记录则放行）
_TRACE_OWNERS: dict[str, int] = {}
_TRACE_TTL = 3600
_TRACE_OWNERS_TS: dict[str, float] = {}
# ephemeral 集合：executor 写前闸门据此拦截，保证 multi ephemeral 不经 graph 写库
_EPHEMERAL_TRACES: set[str] = set()
_EPHEMERAL_TS: dict[str, float] = {}
_TRACE_GOALS: dict[str, int] = {}
_TRACE_GOALS_TS: dict[str, float] = {}
_TRACE_CITATIONS: dict[str, list] = {}
_TRACE_CITATIONS_TS: dict[str, float] = {}


def _cleanup_mem_boxes(now: float | None = None) -> None:
    try:
        _now = float(now) if now is not None else time.time()
    except Exception:
        _now = time.time()
    try:
        for k, exp in list(_STEER_TS.items()):
            try:
                if float(exp) <= _now:
                    _steer_box.pop(k, None)
                    _STEER_TS.pop(k, None)
            except Exception:
                pass
        for k, exp in list(_ABORT_TS.items()):
            try:
                if float(exp) <= _now:
                    _ABORT_TRACES.discard(k)
                    _ABORT_TS.pop(k, None)
            except Exception:
                pass
        for k, exp in list(_TRACE_OWNERS_TS.items()):
            try:
                if float(exp) <= _now:
                    _TRACE_OWNERS.pop(k, None)
                    _TRACE_OWNERS_TS.pop(k, None)
            except Exception:
                pass
        for k, exp in list(_EPHEMERAL_TS.items()):
            try:
                if float(exp) <= _now:
                    _EPHEMERAL_TRACES.discard(k)
                    _EPHEMERAL_TS.pop(k, None)
            except Exception:
                pass
        for k, exp in list(_TRACE_GOALS_TS.items()):
            try:
                if float(exp) <= _now:
                    _TRACE_GOALS.pop(k, None)
                    _TRACE_GOALS_TS.pop(k, None)
            except Exception:
                pass
        for k, exp in list(_TRACE_CITATIONS_TS.items()):
            try:
                if float(exp) <= _now:
                    _TRACE_CITATIONS.pop(k, None)
                    _TRACE_CITATIONS_TS.pop(k, None)
            except Exception:
                pass
    except Exception:
        pass
    try:
        _enforce_mem_cap(_TRACE_OWNERS)
        _enforce_mem_cap(_steer_box)
        _enforce_mem_cap(_TRACE_GOALS)
        _enforce_mem_cap(_TRACE_CITATIONS)
    except Exception:
        pass


def _is_ephemeral_trace(trace_id: str) -> bool:
    try:
        _cleanup_mem_boxes()
    except Exception:
        pass
    try:
        return trace_id in _EPHEMERAL_TRACES
    except Exception:
        return False


def _is_aborted_trace(trace_id: str) -> bool:
    try:
        _cleanup_mem_boxes()
    except Exception:
        pass
    try:
        return trace_id in _ABORT_TRACES
    except Exception:
        return False


def _enforce_trace_owner(trace_id: str, user_id: int, session=None) -> None:
    try:
        _cleanup_mem_boxes()
    except Exception:
        pass
    """归属强制：DB 可判则按 DB，否则按内存 _TRACE_OWNERS/approval 条目；不一致 404。"""
    try:
        resolved = None
        if session is not None:
            try:
                resolved = _resolve_trace_user(session, trace_id)
            except Exception:
                resolved = None
        if resolved is not None:
            if int(resolved) != int(user_id):
                raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
            return
    except HTTPException:
        raise
    except Exception:
        pass
    try:
        owner = _TRACE_OWNERS.get(trace_id)
        if owner is not None and int(owner) != int(user_id):
            raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
        if owner is not None:
            return
    except HTTPException:
        raise
    except Exception:
        pass
    # 最后回退：审批等待条目 user_id（pending 期内存/Redis 双写其一命中即判）
    try:
        ent = _approval_get_merged(trace_id)
        if isinstance(ent, dict) and ent.get("user_id") is not None:
            if int(ent.get("user_id")) != int(user_id):
                raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    except HTTPException:
        raise
    except Exception:
        pass


def _cache_get_workbench_user(trace_id: str, user_id: int | None):
    """Wave1 P0 cache user绑定读：优先新键(user_id)，miss 回读旧 trace-only 键一轮兼容。"""
    if user_id is not None:
        try:
            v = cache_get_workbench(trace_id, user_id=int(user_id))
            if v is not None:
                return v
        except Exception:
            pass
    try:
        return cache_get_workbench(trace_id)
    except Exception:
        return None


def _cache_set_workbench_user(trace_id: str, events: list, user_id: int | None) -> None:
    """Wave1 P0 cache user绑定写：双写新旧键一轮（新键 user 绑定 + 旧键兼容只读）。"""
    if user_id is not None:
        try:
            cache_set_workbench(trace_id, list(events or []), user_id=int(user_id))
        except Exception:
            pass
    try:
        cache_set_workbench(trace_id, list(events or []))
    except Exception:
        pass


def _cache_get_graph_user(trace_id: str, user_id: int | None):
    """Wave1 P0 cache user绑定读：优先新键，miss 回读旧键。"""
    if user_id is not None:
        try:
            v = cache_get_graph(trace_id, user_id=int(user_id))
            if v is not None:
                return v
        except Exception:
            pass
    try:
        return cache_get_graph(trace_id)
    except Exception:
        return None


def _cache_set_graph_user(trace_id: str, graph_data: dict, user_id: int | None) -> None:
    """Wave1 P0 cache user绑定写：双写新旧键一轮。"""
    if user_id is not None:
        try:
            cache_set_graph(trace_id, dict(graph_data or {}), user_id=int(user_id))
        except Exception:
            pass
    try:
        cache_set_graph(trace_id, dict(graph_data or {}))
    except Exception:
        pass


def _new_event_id() -> str:
    """S7 新事件 id：uuid8（与 registry AgentEvent event_id 同源短 id）。"""
    try:
        return uuid.uuid4().hex[:8]
    except Exception:
        return secrets.token_hex(4)


def _is_partial_event(ev: Any) -> bool:
    """S7 半包判定：顶层 _partial 或 data._partial 为 True 即半包。"""
    try:
        if not isinstance(ev, dict):
            return False
        if ev.get("_partial") is True:
            return True
        d = ev.get("data")
        if isinstance(d, dict) and d.get("_partial") is True:
            return True
    except Exception:
        return False
    return False


def _drop_partial_events(events: list) -> list:
    """S7 禁存流式半包：落盘前过滤 _partial==true 事件（纯过滤，不改原 list）。"""
    try:
        return [e for e in (events or []) if not _is_partial_event(e)]
    except Exception:
        return list(events or [])


def _ensure_event_chain(events: list, tail_id: str | None = None) -> list:
    """S7 prev_id 链：就地补链（复用同一 dict，保证调用方 evs 同步 enriched）。

    - 缺 event_id 的新事件用 uuid8；
    - 缺 prev_id 则补 prev（首事件取 tail_id，无则 None）；
    - 已有 id/prev_id 原样保留（兼容旧链/fork，不断链）。
    """
    try:
        prev = tail_id
        for ev in events or []:
            if not isinstance(ev, dict):
                continue
            eid = ev.get("event_id")
            if not isinstance(eid, str) or not eid:
                eid = _new_event_id()
                try:
                    ev["event_id"] = eid
                except Exception:
                    continue
            if "prev_id" not in ev:
                try:
                    ev["prev_id"] = prev
                except Exception:
                    pass
            try:
                prev = ev.get("event_id") or prev
            except Exception:
                pass
        return events
    except Exception:
        return events


# Wave B 会话语义（Codex对标 exec cli + thread/resume + rollout三元组）：只新增不重构Wave A
def filter_rollout(events: list) -> list:
    """Wave B rollout落盘过滤纯函数：剔除agent=researcher的中间tool_call_start噪音，只留tool_call_end。

    - 仅过滤 event=="tool_call_start" 且 data.agent=="researcher" 的事件；
    - 其余事件（含 tool_call/tool_call_end/thought/task_created/done 等）原样保留；
    - 无副作用：返回新list，不改原list（元素dict复用引用，与 _drop_partial_events 同语义）。
    """
    try:
        out: list = []
        for e in (events or []):
            try:
                if isinstance(e, dict) and e.get("event") == "tool_call_start":
                    d = e.get("data")
                    if isinstance(d, dict) and d.get("agent") == "researcher":
                        continue
            except Exception:
                pass
            out.append(e)
        return out
    except Exception:
        return list(events or [])


def _validate_tasks_for_schema(tasks_raw: list | None) -> bool:
    """Wave B output_schema简化校验：每条含必需键title/planned_start/planned_end（非空）即通过，空列表视为失败。"""
    try:
        if not isinstance(tasks_raw, list) or not tasks_raw:
            return False
        for t in tasks_raw:
            if not isinstance(t, dict):
                return False
            try:
                title = str(t.get("title") or "").strip()
                ps = str(t.get("planned_start") or "").strip()
                pe = str(t.get("planned_end") or "").strip()
            except Exception:
                return False
            if not title or not ps or not pe:
                return False
        return True
    except Exception:
        return False


def _plan_events_set_memory_only(trace_id: str, events: list) -> None:
    """Wave B ephemeral内存落盘：只写内存+TTL，不写Redis（与 _plan_events_set 同链语义，禁存半包+rollout过滤+prev链）。"""
    try:
        events = _drop_partial_events(events or [])
    except Exception:
        events = list(events or [])
    try:
        events = filter_rollout(events)
    except Exception:
        pass
    _tail: str | None = None
    try:
        _old = _plan_events_get(trace_id)
        if isinstance(_old, list) and _old:
            _last = _old[-1]
            if isinstance(_last, dict):
                _tid = _last.get("event_id")
                if isinstance(_tid, str) and _tid:
                    _tail = _tid
    except Exception:
        _tail = None
    try:
        _ensure_event_chain(events, _tail)
    except Exception:
        pass
    try:
        from app.services.planner import plan_store as _ps_mem

        _ps_mem[trace_id] = events
        _plan_events_ts[trace_id] = time.time() + _PLAN_EVENTS_TTL
        if len(_ps_mem) > _MEM_CAP:
            now = time.time()
            for k in [k for k in list(_ps_mem.keys()) if float(_plan_events_ts.get(k, 0) or 0) <= now]:
                try:
                    _ps_mem.pop(k, None)
                except Exception:
                    pass
                _plan_events_ts.pop(k, None)
            while len(_ps_mem) > _MEM_CAP:
                try:
                    oldest = next(iter(_ps_mem))
                    _ps_mem.pop(oldest, None)
                    _plan_events_ts.pop(oldest, None)
                except StopIteration:
                    break
                except Exception:
                    break
    except Exception:
        pass


def _persist_events_for_trace(trace_id: str, events: list, ephemeral: bool = False) -> None:
    """Wave B统一落盘入口：ephemeral仅内存，否则走Redis+内存（rollout过滤在内）。"""
    try:
        if bool(ephemeral):
            _plan_events_set_memory_only(trace_id, list(events or []))
        else:
            _plan_events_set(trace_id, list(events or []))
    except Exception:
        pass


def _load_events_for_trace(trace_id: str, session=None, user_id: int | None = None):
    """Wave B增量续播统一读链：cache:workbench(user优先/旧键兼容) → plan:events → plan_store/DB → agent_run_log重建（与stream同序）。"""
    events = None
    try:
        events = _cache_get_workbench_user(trace_id, user_id)
    except Exception:
        events = None
    if not events:
        try:
            events = _plan_events_get(trace_id)
        except Exception:
            events = None
    if not events:
        try:
            from app.services.planner import plan_store as _ps_load

            if hasattr(_ps_load, "get_or_reconstruct"):
                try:
                    events = _ps_load.get_or_reconstruct(trace_id, session)  # type: ignore
                except TypeError:
                    events = _ps_load.get(trace_id)  # type: ignore
            else:
                events = _ps_load.get(trace_id)  # type: ignore
        except Exception:
            events = None
    if not events and session is not None:
        try:
            logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at)).all()
            if logs:
                planner_log = next((l for l in logs if getattr(l, "agent_name", "") == "planner"), logs[0])
                out = getattr(planner_log, "output", None) or {}
                tasks_raw = out.get("tasks", []) if isinstance(out, dict) else []
                events = []
                events.append({"event": "thought", "data": {"agent": "planner", "text": "从DB恢复的规划轨迹..."}})
                for t in tasks_raw or []:
                    if isinstance(t, dict):
                        title = t.get("title", "任务")
                        ps = t.get("planned_start", "")
                        pe = t.get("planned_end", "")
                        pri = t.get("priority", 3)
                    else:
                        title = getattr(t, "title", "任务")
                        ps = str(getattr(t, "planned_start", ""))
                        pe = str(getattr(t, "planned_end", ""))
                        pri = getattr(t, "priority", 3)
                    events.append({"event": "task_created", "data": {"task": {"title": title, "planned_start": ps, "planned_end": pe, "priority": pri}}})
                mentor = next((getattr(l, "output", None).get("mentor_msg") for l in logs if getattr(l, "agent_name", "") == "mentor" and isinstance(getattr(l, "output", None), dict)), "")
                if mentor:
                    events.append({"event": "mentor_msg", "data": {"text": mentor}})
                events.append({"event": "done", "data": {"trace_id": trace_id, "count": len([e for e in events if isinstance(e, dict) and e.get("event") == "task_created"]), "source": "db_recover", "approved": True}})
        except Exception:
            events = None
    return events


def _resolve_resume_trace(resume: str | None, user_id: int, session) -> str | None:
    """Wave B resume解析纯查（无副作用）：trace_id直通 / "--last"按用户最近trace / name经标题匹配。未命中返回None。"""
    try:
        if resume is None or not isinstance(resume, str):
            return None
        r = resume.strip()
        if not r:
            return None
        # --last：按用户最近trace（planner日志goal归属判定）
        if r == "--last":
            try:
                goals = session.exec(select(LearningGoal).where(LearningGoal.user_id == user_id)).all()
                gids = {g.id for g in goals if getattr(g, "id", None) is not None}
                if not gids:
                    return None
                logs = session.exec(select(AgentRunLog).order_by(AgentRunLog.created_at.desc(), AgentRunLog.id.desc())).all()  # type: ignore
                seen: set[str] = set()
                ordered: list[str] = []
                for lg in logs or []:
                    try:
                        tid = getattr(lg, "trace_id", None)
                        if not isinstance(tid, str) or not tid or tid in seen:
                            continue
                        seen.add(tid)
                        ordered.append(tid)
                    except Exception:
                        continue
                trace_goal: dict[str, int] = {}
                for lg in logs or []:
                    try:
                        if getattr(lg, "agent_name", "") != "planner":
                            continue
                        tid = getattr(lg, "trace_id", None)
                        if not isinstance(tid, str) or tid in trace_goal:
                            continue
                        inp = getattr(lg, "input", None) or {}
                        g = inp.get("goal") if isinstance(inp, dict) else None
                        gid = g.get("id") if isinstance(g, dict) else None
                        if isinstance(gid, int):
                            trace_goal[tid] = gid
                    except Exception:
                        continue
                for tid in ordered:
                    if trace_goal.get(tid) in gids:
                        return tid
                return None
            except Exception:
                return None
        # trace_id直通：任一存储命中即直通（含归属校验，他人trace视为未命中）
        try:
            hit: list | None = None
            try:
                hit = _plan_events_get(r)
            except Exception:
                hit = None
            if not (isinstance(hit, list) and hit):
                try:
                    from app.services.planner import plan_store as _ps_hit

                    v = _ps_hit.get(r)
                    if isinstance(v, list) and v:
                        hit = v
                except Exception:
                    pass
            if not (isinstance(hit, list) and hit):
                try:
                    _logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == r)).all()
                    if _logs:
                        hit = [{}]
                except Exception:
                    pass
            if isinstance(hit, list) and hit:
                try:
                    owner = _resolve_trace_user(session, r)
                    if owner is not None and int(owner) != int(user_id):
                        return None
                except Exception:
                    pass
                return r
        except Exception:
            pass
        # 32位hex疑似trace但未命中：直接未命中（不回退标题匹配，避免误匹配）
        try:
            import re as _re

            if bool(_re.fullmatch(r"[0-9a-fA-F]{32}", r)):
                return None
        except Exception:
            pass
        # name标题匹配：LearningGoal标题contains（同用户）→ 该goal最近trace
        try:
            rl = r.lower()
            goals = session.exec(select(LearningGoal).where(LearningGoal.user_id == user_id)).all()
            matched = [g.id for g in (goals or []) if isinstance(getattr(g, "title", ""), str) and rl in str(getattr(g, "title", "")).lower()]
            matched_set = {m for m in matched if isinstance(m, int)}
            if matched_set:
                try:
                    plogs = session.exec(select(AgentRunLog).where(AgentRunLog.agent_name == "planner").order_by(AgentRunLog.created_at.desc(), AgentRunLog.id.desc())).all()  # type: ignore
                    for lg in plogs or []:
                        try:
                            inp = getattr(lg, "input", None) or {}
                            g = inp.get("goal") if isinstance(inp, dict) else None
                            gid = g.get("id") if isinstance(g, dict) else None
                            if gid in matched_set:
                                tid = getattr(lg, "trace_id", None)
                                if isinstance(tid, str) and tid:
                                    return tid
                        except Exception:
                            continue
                except Exception:
                    pass
        except Exception:
            pass
        # name回退：plan_store task标题contains（同用户归属可判时过滤）
        try:
            rl = r.lower()
            from app.services.planner import plan_store as _ps_nm

            for tid in reversed(list(_ps_nm.keys())):
                try:
                    evs = _ps_nm.get(tid)
                    if not isinstance(evs, list):
                        continue
                    try:
                        owner = _resolve_trace_user(session, tid)
                        if owner is not None and int(owner) != int(user_id):
                            continue
                    except Exception:
                        pass
                    for e in evs:
                        if not isinstance(e, dict) or e.get("event") != "task_created":
                            continue
                        try:
                            t = (e.get("data") or {}).get("task") or {}
                            title = str(t.get("title", "") or "")
                            if rl and rl in title.lower():
                                return tid
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception:
            pass
        return None
    except Exception:
        return None


def _plan_events_set(trace_id: str, events: list) -> None:
    # S7：禁存半包 + prev_id 链（就地补，保证调用方 evs 同步，旧测试 == 仍成立）
    # Wave B：rollout过滤（researcher tool_call_start噪音剔除，只留end）叠加在半包过滤后
    try:
        events = _drop_partial_events(events or [])
    except Exception:
        events = list(events or [])
    try:
        events = filter_rollout(events)
    except Exception:
        pass
    # 跨调用 tail：已存链末 event_id（首事件缺 prev_id 时续链；覆盖写首事件已有 prev_id 则保留不覆盖）
    _tail: str | None = None
    try:
        _old = _plan_events_get(trace_id)
        if isinstance(_old, list) and _old:
            _last = _old[-1]
            if isinstance(_last, dict):
                _tid = _last.get("event_id")
                if isinstance(_tid, str) and _tid:
                    _tail = _tid
    except Exception:
        _tail = None
    try:
        _ensure_event_chain(events, _tail)
    except Exception:
        pass
    try:
        payload = json.dumps(events, ensure_ascii=False)
    except Exception:
        payload = "[]"
    _redis_setex(f"plan:events:{trace_id}", _PLAN_EVENTS_TTL, payload)
    try:
        from app.services.planner import plan_store as _ps

        _ps[trace_id] = events
        _plan_events_ts[trace_id] = time.time() + _PLAN_EVENTS_TTL
        if len(_ps) > _MEM_CAP:
            now = time.time()
            for k in [k for k in list(_ps.keys()) if float(_plan_events_ts.get(k, 0) or 0) <= now]:
                try:
                    _ps.pop(k, None)
                except Exception:
                    pass
                _plan_events_ts.pop(k, None)
            while len(_ps) > _MEM_CAP:
                try:
                    oldest = next(iter(_ps))
                    _ps.pop(oldest, None)
                    _plan_events_ts.pop(oldest, None)
                except StopIteration:
                    break
                except Exception:
                    break
    except Exception:
        pass


def _plan_events_get(trace_id: str):
    raw = _redis_get_str(f"plan:events:{trace_id}")
    if raw:
        try:
            v = json.loads(raw)
            if isinstance(v, list):
                # S7 读时补链（旧数据无 id/prev_id 则补，不覆盖已有链）
                try:
                    _ensure_event_chain(v, None)
                except Exception:
                    pass
                return v
        except Exception:
            pass
    try:
        exp = _plan_events_ts.get(trace_id)
        if exp is not None and float(exp) <= time.time():
            try:
                from app.services.planner import plan_store as _ps2

                _ps2.pop(trace_id, None)
            except Exception:
                pass
            _plan_events_ts.pop(trace_id, None)
            return None
        from app.services.planner import plan_store as _ps3

        _res = _ps3.get(trace_id)
        # S7 读时补链（就地补，兼容旧 trace）
        if isinstance(_res, list):
            try:
                _ensure_event_chain(_res, None)
            except Exception:
                pass
        return _res
    except Exception:
        return None


def _approval_redis_get(trace_id: str) -> dict | None:
    raw = _redis_get_str(f"plan:approval:{trace_id}")
    if not raw:
        return None
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else None
    except Exception:
        return None


def _approval_redis_set(trace_id: str, entry: dict, ttl: float) -> None:
    try:
        _redis_setex(f"plan:approval:{trace_id}", int(max(1, float(ttl))), json.dumps(entry, ensure_ascii=False, default=str))
    except Exception:
        pass


def _approval_redis_del(trace_id: str) -> None:
    _redis_del(f"plan:approval:{trace_id}")


def _block_redis_add(trace_id: str, ttl: float) -> None:
    """审批拦截标记写入 Redis（跨实例可见，TTL 防崩溃残留），失败静默（内存为主）。"""
    try:
        _redis_setex(f"plan:block:{trace_id}", int(max(1, float(ttl))), "1")
    except Exception:
        pass


def _block_redis_exists(trace_id: str) -> bool:
    try:
        return _redis_get_str(f"plan:block:{trace_id}") == "1"
    except Exception:
        return False


def _block_redis_del(trace_id: str) -> None:
    _redis_del(f"plan:block:{trace_id}")


def _is_approval_blocked(trace_id: str) -> bool:
    """内存快路径优先（同进程零延迟），miss 时回查 Redis（跨实例/重启后可见）。

    Redis 不可达时视为不拦截（fail-open，与内存回退语义一致，避免误杀正常落库）。
    """
    try:
        if trace_id in _APPROVAL_BLOCK_TRACES:
            return True
    except Exception:
        pass
    return _block_redis_exists(trace_id)


def _ticket_redis_get(ticket: str) -> dict | None:
    raw = _redis_get_str(f"plan:ticket:{ticket}")
    if not raw:
        return None
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else None
    except Exception:
        return None


def _ticket_redis_set(ticket: str, entry: dict, ttl: int) -> None:
    try:
        _redis_setex(f"plan:ticket:{ticket}", int(ttl), json.dumps(entry, ensure_ascii=False, default=str))
    except Exception:
        pass


def _ticket_redis_del(ticket: str) -> None:
    _redis_del(f"plan:ticket:{ticket}")


# SSE prod 鉴权加固：一次性 stream_ticket（EventSource 无法带 Authorization 头，fetch 兼容 + ticket 兼容）
# key=ticket -> {trace_id, user_id, exp}，TTL 60s，内存 dict，一次性核销（Redis 优先 plan:ticket:{t}）
_STREAM_TICKET_TTL = 60
_STREAM_TICKETS: dict[str, dict] = {}


def _mint_stream_ticket(trace_id: str, user_id: int, ttl: int = _STREAM_TICKET_TTL) -> str:
    now = time.time()
    # 惰性清理过期 ticket，避免内存膨胀 + LRU500 上限
    try:
        for k in [k for k, v in _STREAM_TICKETS.items() if float(v.get("exp", 0)) <= now]:
            _STREAM_TICKETS.pop(k, None)
    except Exception:
        pass
    ticket = secrets.token_urlsafe(32)
    entry = {"trace_id": trace_id, "user_id": int(user_id), "exp": now + ttl}
    _STREAM_TICKETS[ticket] = entry
    _enforce_mem_cap(_STREAM_TICKETS)
    _ticket_redis_set(ticket, entry, int(ttl))
    return ticket


def _consume_stream_ticket(ticket: str | None, trace_id: str) -> int | None:
    """ticket 有效则返回绑定 user_id 并一次性核销；无效/过期/错 trace 返回 None（不放宽旧路径）。"""
    if not ticket:
        return None
    # Redis 优先
    try:
        r_entry = _ticket_redis_get(ticket)
        if r_entry is not None:
            try:
                if float(r_entry.get("exp", 0)) <= time.time():
                    _ticket_redis_del(ticket)
                    _STREAM_TICKETS.pop(ticket, None)
                    return None
            except Exception:
                _ticket_redis_del(ticket)
                _STREAM_TICKETS.pop(ticket, None)
                return None
            if r_entry.get("trace_id") != trace_id:
                return None
            _ticket_redis_del(ticket)
            _STREAM_TICKETS.pop(ticket, None)
            try:
                return int(r_entry.get("user_id"))
            except Exception:
                return None
    except Exception:
        pass
    entry = _STREAM_TICKETS.get(ticket)
    if not entry:
        return None
    try:
        if float(entry.get("exp", 0)) <= time.time():
            _STREAM_TICKETS.pop(ticket, None)
            return None
    except Exception:
        _STREAM_TICKETS.pop(ticket, None)
        return None
    if entry.get("trace_id") != trace_id:
        return None
    _STREAM_TICKETS.pop(ticket, None)
    try:
        return int(entry.get("user_id"))
    except Exception:
        return None


def _try_bearer_user_id(authorization: str | None) -> int | None:
    """仅解析 Authorization: Bearer JWT，有效返回 user_id，无效/缺失返回 None（不抛错，供 ticket 回退）。"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    try:
        from jose import jwt as _jwt

        from app.core.config import get_settings as _get_settings

        _s = _get_settings()
        payload = _jwt.decode(token, _s.jwt_secret, algorithms=[_s.jwt_algorithm])
        uid = payload.get("sub") or payload.get("user_id") or payload.get("uid")
        if uid is not None:
            try:
                return int(uid)
            except Exception:
                pass
        return 1
    except Exception:
        return None


# 写库审批后端网关（第10种 SSE 事件 approval_required）：内存 dict + TTL 300s + 轮询等待
# 仅 multi 模式且 require_approval=true 时生效，默认 false 旧流程零改动
APPROVAL_TIMEOUT = 300
_APPROVAL_TTL = APPROVAL_TIMEOUT
_APPROVAL_POLL_INTERVAL = 0.2
_APPROVALS: dict[str, dict] = {}
_APPROVAL_BLOCK_TRACES: set[str] = set()
_APPROVAL_HOOK_REGISTERED = False


def _approval_timeout_value() -> float:
    """等待超时秒数：优先模块常量 APPROVAL_TIMEOUT（测试可 monkeypatch 改小），回退 _APPROVAL_TTL。"""
    try:
        v = globals().get("APPROVAL_TIMEOUT", None)
        if v is not None:
            return float(v)
    except Exception:
        pass
    try:
        return float(globals().get("_APPROVAL_TTL", 300))
    except Exception:
        return 300.0


def _build_tasks_preview(tasks_raw: list | None) -> list[dict]:
    """tasks_preview 前10条：{title,planned_start,planned_end,priority}。"""
    preview: list[dict] = []
    try:
        for t in (tasks_raw or [])[:10]:
            if not isinstance(t, dict):
                continue
            preview.append(
                {
                    "title": str(t.get("title", "任务"))[:200],
                    "planned_start": t.get("planned_start"),
                    "planned_end": t.get("planned_end"),
                    "priority": t.get("priority", 3),
                }
            )
    except Exception:
        pass
    return preview


def _mint_approval(trace_id: str, tasks_raw: list | None, user_id: int, ttl: float | int | None = None, goal_id: int | None = None) -> str:
    """生成 approve_token 并存内存 dict {trace_id: {token, tasks_raw, exp, approved}}，TTL 默认 APPROVAL_TIMEOUT(300s)。Redis 优先 plan:approval:{trace}。"""
    now = time.time()
    try:
        for k in [k for k, v in list(_APPROVALS.items()) if float(v.get("exp", 0)) <= now and v.get("approved") is None]:
            _APPROVALS.pop(k, None)
    except Exception:
        pass
    token = secrets.token_urlsafe(32)
    try:
        effective_ttl = float(ttl) if ttl is not None else float(_approval_timeout_value())
    except Exception:
        effective_ttl = 300.0
    entry = {
        "token": token,
        "tasks_raw": list(tasks_raw or []),
        "exp": now + effective_ttl,
        "approved": None,
        "user_id": int(user_id),
        "created_at": now,
        "goal_id": goal_id,
    }
    _APPROVALS[trace_id] = entry
    _enforce_mem_cap(_APPROVALS)
    _approval_redis_set(trace_id, entry, effective_ttl)
    return token


def _approval_get_merged(trace_id: str) -> dict | None:
    """Redis 优先，内存回退（双写保持旧测试直读 _APPROVALS 兼容）。"""
    try:
        r_entry = _approval_redis_get(trace_id)
        if r_entry is not None:
            try:
                mem = _APPROVALS.get(trace_id)
                if mem is not None and r_entry.get("approved") is None and mem.get("approved") is not None:
                    # 内存已有决议但 Redis 尚未同步，回写 Redis
                    try:
                        _approval_redis_set(trace_id, mem, max(1.0, float(mem.get("exp", time.time() + 300)) - time.time()))
                    except Exception:
                        pass
                    return mem
            except Exception:
                pass
            return r_entry
    except Exception:
        pass
    try:
        return _APPROVALS.get(trace_id)
    except Exception:
        return None


async def _wait_approval(trace_id: str, timeout: float | int | None = None) -> bool | None:
    """轮询等待批准（Redis 优先、内存回退）：True=批准，False=拒绝，None=超时未决（调用方视为拒绝）。

    timeout 为 None 时取模块常量 APPROVAL_TIMEOUT（测试可 monkeypatch 改小或传小值）。
    """
    try:
        limit = float(timeout) if timeout is not None else float(_approval_timeout_value())
    except Exception:
        limit = 300.0
    start = time.time()
    while True:
        try:
            entry = _approval_get_merged(trace_id)
            if entry is None:
                return None
            try:
                if float(entry.get("exp", 0)) <= time.time() and entry.get("approved") is None:
                    return None
            except Exception:
                return None
            if entry.get("approved") is True:
                return True
            if entry.get("approved") is False:
                return False
        except Exception:
            return None
        if time.time() - start >= limit:
            return None
        try:
            interval = float(globals().get("_APPROVAL_POLL_INTERVAL", 0.2))
        except Exception:
            interval = 0.2
        if interval <= 0:
            interval = 0.05
        try:
            remaining = limit - (time.time() - start)
        except Exception:
            remaining = interval
        if remaining <= 0:
            return None
        await asyncio.sleep(min(interval, max(0.01, remaining)))


def _rollback_premature_tasks(session: Session, rows: list | None, goal_id: int, trace_id: str) -> int:
    """审批拒绝时回滚 graph 内 write_tasks 已提前落库的行（按 id + source_agent 双保险），返回删除数。"""
    deleted = 0
    try:
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            rid = r.get("id")
            if rid is None:
                continue
            try:
                obj = session.get(Task, int(rid))
                if obj is not None and obj.goal_id == goal_id:
                    session.delete(obj)
                    deleted += 1
            except Exception:
                continue
        try:
            premature = session.exec(select(Task).where(Task.goal_id == goal_id, Task.source_agent == f"planner:{trace_id}")).all()
            for obj in premature:
                try:
                    session.delete(obj)
                    deleted += 1
                except Exception:
                    continue
        except Exception:
            pass
        if deleted:
            session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
    return deleted


def _write_tasks_approval_guard(name: str, args: dict, context) -> dict | None:
    """write_tasks 前置闸门：审批流/ephemeral graph 执行期间拦截落库，降级为 state 透传（plans.py 批准后手动落库）。"""
    try:
        if name != "write_tasks":
            return None
        tasks = (args or {}).get("tasks", [])
        if not isinstance(tasks, list):
            return None
        for t in tasks:
            if not isinstance(t, dict):
                continue
            sa = t.get("source_agent", "")
            if isinstance(sa, str) and sa.startswith("planner:"):
                tid = sa.split(":", 1)[1]
                if _is_approval_blocked(tid):
                    return {"block": True, "reason": "awaiting approval"}
                # ephemeral：无审批也拦截，防 multi 经 executor 直写 DB（落库由外层瞬态回显替代）
                try:
                    if tid in _EPHEMERAL_TRACES:
                        return {"block": True, "reason": "ephemeral no-db"}
                except Exception:
                    pass
        return None
    except Exception:
        return None


async def _try_calendar_sync(tasks_created: list | None, trace_id: str) -> dict:
    """P2 批准后日历同步：P1 calendar 工具存在则尝试调用，否则跳过，永不抛错阻断主流程。

    探测顺序：registry（含 mcp:calendar:*）→ mcp.client；任一含 calendar 即视为存在。
    存在时对前3个任务调 calendar/create_event（3s 超时），失败逐条跳过。
    """
    try:
        has_tool = False
        try:
            from app.agents.tools.registry import list_tools as _list_reg

            _reg_tools = _list_reg() or []
            if any("calendar" in str(t).lower() for t in _reg_tools):
                has_tool = True
        except Exception:
            pass
        if not has_tool:
            try:
                from app.mcp.client import list_tools as _list_mcp

                _mcp_tools = _list_mcp() or []
                for _t in _mcp_tools:
                    try:
                        if not isinstance(_t, dict):
                            if "calendar" in str(_t).lower():
                                has_tool = True
                                break
                            continue
                        if str(_t.get("server", "")).lower() == "calendar" or "calendar" in str(_t.get("full_name", "")).lower():
                            has_tool = True
                            break
                    except Exception:
                        continue
            except Exception:
                pass
        if not has_tool:
            return {"skipped": True, "reason": "no calendar tool"}
        try:
            from app.mcp.client import call_tool as _mcp_call

            synced = 0
            for tr in (tasks_created or [])[:3]:
                try:
                    if isinstance(tr, dict):
                        title = tr.get("title")
                        ps = tr.get("planned_start")
                        pe = tr.get("planned_end")
                    else:
                        title = getattr(tr, "title", "学习任务")
                        ps = getattr(tr, "planned_start", "")
                        pe = getattr(tr, "planned_end", "")
                    try:
                        if hasattr(ps, "isoformat"):
                            ps = ps.isoformat()
                        if hasattr(pe, "isoformat"):
                            pe = pe.isoformat()
                    except Exception:
                        pass
                    await _mcp_call(
                        "calendar",
                        "create_event",
                        {"title": str(title or "学习任务"), "start": str(ps or ""), "end": str(pe or "")},
                        timeout=3.0,
                    )
                    synced += 1
                except Exception:
                    continue
            return {"skipped": False, "synced": synced}
        except Exception as e:
            logger.warning("calendar sync failed (skip): trace_id=%s err=%s", trace_id, e, exc_info=True)
            return {"skipped": True, "reason": f"call failed: {e}"}
    except Exception as e:
        logger.warning("calendar sync probe failed (skip): trace_id=%s", trace_id, exc_info=True)
        return {"skipped": True, "reason": str(e)[:100]}


try:
    from app.agents.tools.registry import add_before_hook as _add_approval_hook

    if not _APPROVAL_HOOK_REGISTERED:
        _add_approval_hook(_write_tasks_approval_guard)
        _APPROVAL_HOOK_REGISTERED = True
except Exception:
    logger.warning("register approval guard hook failed", exc_info=True)

# Wave A：Codex对标 protocol.rs:984 四档 + execpolicy decision 三值
# approval 四档：untrusted/on-request/never/granular，默认 on-request；
# 兼容旧 require_approval=true→untrusted。Decision 三值见 app/services/exec_policy。
_APPROVAL_MODES = ("untrusted", "on-request", "never", "granular")
_DEFAULT_APPROVAL_MODE = "on-request"


def _normalize_approval_mode(payload_or_value=None) -> str:
    """归一化四档：显式 approval 优先（大小写/下划线兼容），否则旧 require_approval=true→untrusted，否则默认 on-request。"""
    try:
        if payload_or_value is not None and hasattr(payload_or_value, "approval"):
            raw = getattr(payload_or_value, "approval", None)
            try:
                req = bool(getattr(payload_or_value, "require_approval", False))
            except Exception:
                req = False
        elif isinstance(payload_or_value, dict):
            raw = payload_or_value.get("approval")
            try:
                req = bool(payload_or_value.get("require_approval", False))
            except Exception:
                req = False
        elif isinstance(payload_or_value, str):
            raw = payload_or_value
            req = False
        elif payload_or_value is None:
            return _DEFAULT_APPROVAL_MODE
        else:
            raw = None
            req = False
        if isinstance(raw, str) and raw.strip():
            v = raw.strip().lower().replace("_", "-")
            if v in ("onrequest", "on request"):
                return "on-request"
            if v in _APPROVAL_MODES:
                return v
            return _DEFAULT_APPROVAL_MODE
        if req:
            return "untrusted"
        return _DEFAULT_APPROVAL_MODE
    except Exception:
        return _DEFAULT_APPROVAL_MODE


def _resolve_need_approval(approval_mode: str | None = None, payload=None) -> bool:
    """need_approval 旧变量兼容映射：显式请求（approval 非空或 require_approval=true）且模式非 never 时 True；默认无显式请求 False。"""
    try:
        explicit = False
        try:
            if payload is not None and hasattr(payload, "approval"):
                _raw = getattr(payload, "approval", None)
                _req = bool(getattr(payload, "require_approval", False))
                explicit = (isinstance(_raw, str) and _raw.strip() != "") or _req
            elif isinstance(payload, dict):
                _raw = payload.get("approval")
                _req = bool(payload.get("require_approval", False))
                explicit = (isinstance(_raw, str) and _raw.strip() != "") or _req
        except Exception:
            explicit = False
        try:
            mode = str(approval_mode or _DEFAULT_APPROVAL_MODE).strip().lower().replace("_", "-")
        except Exception:
            mode = _DEFAULT_APPROVAL_MODE
        if mode == "never":
            return False
        if explicit:
            return mode in ("untrusted", "on-request", "granular")
        return False
    except Exception:
        return False


def _decide_gateway(action: str, approval_mode: str, need_approval: bool) -> tuple[_Decision, str]:
    """决策表：Forbidden→forbidden直接拒（不进Redis）；Prompt→prompt走Redis拦截（需need_approval，否则直行）；Allow→allow直行。

    never 下 Prompt 自动降 Forbidden 由本调用方处理（exec_policy.check 本身不降级）。
    返回 (Decision, handling)，handling∈{allow,prompt,forbidden}。
    """
    try:
        mode = str(approval_mode or _DEFAULT_APPROVAL_MODE).strip().lower().replace("_", "-")
    except Exception:
        mode = _DEFAULT_APPROVAL_MODE
    try:
        dec, _just = _exec_policy.check(action or "write_tasks")
    except Exception:
        dec = _Decision.Prompt
    try:
        if mode == "never" and dec == _Decision.Prompt:
            dec = _Decision.Forbidden
    except Exception:
        pass
    try:
        if dec == _Decision.Forbidden:
            return dec, "forbidden"
        if dec == _Decision.Allow:
            return dec, "allow"
        if bool(need_approval):
            return dec, "prompt"
        return dec, "allow"
    except Exception:
        return dec, "prompt" if bool(need_approval) else "allow"


def _approval_available_decisions(decision=None) -> list[str]:
    """approvals.rs 思想简化：Allow 时 ["approve","reject"]，高危（Prompt/Forbidden）时 ["reject","approve_with_condition"]。"""
    try:
        if isinstance(decision, _Decision):
            dl = str(decision.value or "").strip().lower()
        elif isinstance(decision, str):
            dl = decision.strip().lower()
        elif isinstance(decision, bool):
            dl = "allow" if decision else "prompt"
        else:
            dl = str(decision or "").strip().lower()
        if dl == "allow":
            return ["approve", "reject"]
        return ["reject", "approve_with_condition"]
    except Exception:
        return ["reject", "approve_with_condition"]


# 7节点顺序，对齐 LangGraph graph.py build_graph 7节点
AGENT_ORDER = ["planner", "researcher", "executor", "critic", "reviewer", "mentor", "reflector"]
AGENT_LABEL = {
    "planner": "Planner",
    "researcher": "Researcher",
    "executor": "Executor",
    "critic": "Critic",
    "reviewer": "Reviewer",
    "mentor": "Mentor",
    "reflector": "Reflector",
}


def _safe_parse_dt(value: Any) -> datetime | None:
    """容错解析 planned_start/planned_end，坏数据返回 None 并告警（不再 500）。"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        d = datetime.fromisoformat(str(value))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except Exception:
        logger.warning("planned time unparseable: %r", value)
        return None


def _resolve_trace_user(session: Session, trace_id: str) -> int | None:
    """由 agent_run_log(planner input.goal.id)→LearningGoal 联查 trace 归属用户。

    无日志或无 goal 归属时返回 None（空计划/旧数据），由调用方按环境决定放行策略。
    """
    try:
        logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id)).all()
        for lg in logs:
            inp = lg.input if isinstance(lg.input, dict) else {}
            goal = inp.get("goal")
            if isinstance(goal, dict) and goal.get("id"):
                g = session.get(LearningGoal, goal["id"])
                if g:
                    return g.user_id
    except Exception:
        logger.warning("resolve trace user failed: trace_id=%s", trace_id, exc_info=True)
    return None


def _build_graph_from_logs(logs: list[AgentRunLog], trace_id: str) -> dict:
    """由 agent_run_log 聚合生成 7节点DAG，供 GET /plans/{trace_id}/graph 使用。
    优先走 Redis cache:graph，未命中则本函数聚合重建。
    包含节点态 pending/running/success/error + 回边高亮。
    兼容旧6条trace：缺reviewer日志则pending。
    """
    log_map = {l.agent_name: l for l in logs}
    nodes = []
    for name in AGENT_ORDER:
        lg = log_map.get(name)
        if lg:
            # 根据 output 判断 success/error：若 output 含 error 则 error
            status = "success"
            try:
                out = lg.output or {}
                if isinstance(out, dict) and out.get("error"):
                    status = "error"
            except Exception:
                pass
            # 如果是最后阶段但整体未完成，正在运行的节点标记 running（仅当后续节点 pending 且当前最新）
            # 简化：有日志即 success，未命中即 pending；流式中未完成节点可在前端以 running 模拟
            started = None
            finished = None
            try:
                if lg.created_at:
                    started = lg.created_at.isoformat()
                    finished = started
            except Exception:
                started = None
                finished = None
            nodes.append({"id": name, "name": AGENT_LABEL.get(name, name), "status": status, "started_at": started, "finished_at": finished})
        else:
            # 未产生日志的节点为 pending；若前置已完成则前端可视为 running 态的过渡
            nodes.append({"id": name, "name": AGENT_LABEL.get(name, name), "status": "pending", "started_at": None, "finished_at": None})

    # 整体状态：全7节点 success -> completed，否则 running；若有 error 节点 -> failed
    # 旧6条trace缺reviewer日志则pending（running），新7条全success才completed
    has_error = any(n["status"] == "error" for n in nodes)
    all_success = all(n["status"] == "success" for n in nodes)
    if has_error:
        overall = "failed"
    elif all_success:
        overall = "completed"
    else:
        overall = "running"

    # 构建边：7节点线性 + 回边（P3：critic→reviewer→mentor，旧6条缺reviewer则reviewer pending）
    edges = [
        {"from": "planner", "to": "researcher", "type": "next"},
        {"from": "researcher", "to": "executor", "type": "next"},
        {"from": "executor", "to": "critic", "type": "next"},
        {"from": "critic", "to": "reviewer", "type": "next"},
        {"from": "reviewer", "to": "mentor", "type": "next"},
        {"from": "mentor", "to": "reflector", "type": "next"},
    ]
    # rewrites 回边：critic rewrites>0，或 reflector patch 含重分配类键（曾触发重排）均高亮 replan 回边
    has_patch_replan = False
    rewrites = 0
    try:
        crit = log_map.get("critic")
        if crit and isinstance(crit.output, dict):
            rewrites = int(crit.output.get("rewrites", 0) or 0)
            if rewrites is None:
                rewrites = 0
        # 备用：从 reflector patch 推断是否触发重排
        if rewrites == 0:
            refl = log_map.get("reflector")
            if refl and isinstance(refl.output, dict):
                patch = refl.output.get("patch", {})
                if isinstance(patch, dict) and any(k in patch for k in ("reduce_load", "add_buffer", "reallocate")):
                    has_patch_replan = True
    except Exception:
        rewrites = 0

    if rewrites > 0 or has_patch_replan:
        # 在 critic->planner 回边高亮（前端按 type=replan 红色虚线）
        edges.append({"from": "critic", "to": "planner", "type": "replan"})

    return {"nodes": nodes, "edges": edges, "status": overall, "trace_id": trace_id, "rewrites": rewrites}


def reduce_logs_to_snapshot(logs: list) -> dict:
    """S7 纯函数：reduce(logs)->snapshot{transcript,queues,usage}（无副作用，供 Inspector 直读）。

    - transcript 按 thought/task_created/critic/mentor/review/reflector 拼；
    - queues 空骨架（预留 pending/running/done 三列）；
    - usage 照抄 executor persist 计数（persisted/created/error + count）。
    兼容 AgentRunLog 对象与 dict 两种形态，坏数据跳过不抛错。
    """
    transcript: list[dict] = []
    queues: dict = {"pending": [], "running": [], "done": []}
    usage: dict = {"persisted": False, "created": 0, "error": "", "count": 0}
    try:
        for lg in logs or []:
            try:
                if isinstance(lg, dict):
                    agent = str(lg.get("agent_name") or "")
                    inp = lg.get("input") if isinstance(lg.get("input"), dict) else {}
                    out = lg.get("output") if isinstance(lg.get("output"), dict) else {}
                else:
                    agent = str(getattr(lg, "agent_name", "") or "")
                    inp = getattr(lg, "input", None) or {}
                    out = getattr(lg, "output", None) or {}
                    if not isinstance(inp, dict):
                        inp = {}
                    if not isinstance(out, dict):
                        out = {}
            except Exception:
                continue
            # thought：每步 input.thought
            try:
                th = inp.get("thought") if isinstance(inp, dict) else None
                if isinstance(th, str) and th.strip():
                    transcript.append({"kind": "thought", "agent": agent or "planner", "text": th})
            except Exception:
                pass
            # task_created：planner output.tasks 逐条
            if agent == "planner" and isinstance(out.get("tasks"), list):
                try:
                    for t in out.get("tasks") or []:
                        if not isinstance(t, dict):
                            continue
                        transcript.append(
                            {
                                "kind": "task_created",
                                "task": {
                                    "title": str(t.get("title", "任务")),
                                    "planned_start": t.get("planned_start"),
                                    "planned_end": t.get("planned_end"),
                                    "priority": t.get("priority", 3),
                                },
                            }
                        )
                except Exception:
                    pass
            # critic
            if agent == "critic":
                try:
                    transcript.append(
                        {"kind": "critic", "feedback": str(out.get("feedback", "") or ""), "rewrites": int(out.get("rewrites", 0) or 0)}
                    )
                except Exception:
                    try:
                        transcript.append({"kind": "critic", "feedback": str(out.get("feedback", "") or ""), "rewrites": 0})
                    except Exception:
                        pass
            # mentor
            if agent == "mentor":
                try:
                    transcript.append({"kind": "mentor", "text": str(out.get("mentor_msg", "") or "")})
                except Exception:
                    pass
            # review：reviewer output.review（兼容顶层 score/issues）
            if agent == "reviewer":
                try:
                    rev = out.get("review") if isinstance(out.get("review"), dict) else {}
                    score = rev.get("score", out.get("score", 100)) if isinstance(rev, dict) else out.get("score", 100)
                    issues = rev.get("issues", out.get("issues", [])) if isinstance(rev, dict) else out.get("issues", [])
                    transcript.append({"kind": "review", "score": score, "issues": issues if isinstance(issues, list) else []})
                except Exception:
                    pass
            # reflector
            if agent == "reflector":
                try:
                    transcript.append({"kind": "reflector", "patch": out.get("patch", {}) or {}})
                except Exception:
                    pass
            # usage：照抄 executor persist 计数
            if agent == "executor":
                try:
                    cnt = out.get("count", 0)
                    persist = out.get("persist") if isinstance(out.get("persist"), dict) else {}
                    usage = {
                        "persisted": bool(persist.get("persisted", False)),
                        "created": int(persist.get("created", cnt if isinstance(cnt, int) else 0) or 0),
                        "error": str(persist.get("error", "") or ""),
                        "count": int(cnt or 0) if isinstance(cnt, int) else 0,
                    }
                except Exception:
                    pass
    except Exception:
        pass
    return {"transcript": transcript, "queues": queues, "usage": usage}


def _build_inspector_from_logs(logs: list[AgentRunLog], trace_id: str, session=None) -> dict:
    """复用 logs 聚合 Inspector 所需 {state,logs,patch}。session 可选：传入时反查 Task 行补 citations。"""
    # logs 已按 created_at 排序
    state = {"trace_id": trace_id}
    patch = {}
    try:
        for lg in logs:
            if lg.agent_name == "planner" and isinstance(lg.input, dict):
                state["goal"] = lg.input.get("goal")
                state["preferences"] = lg.input.get("preferences")
            if lg.agent_name == "planner" and isinstance(lg.output, dict):
                state["tasks"] = lg.output.get("tasks", [])
            if lg.agent_name == "researcher" and isinstance(lg.output, dict):
                state["research"] = lg.output
            if lg.agent_name == "critic" and isinstance(lg.output, dict):
                state["critic_feedback"] = lg.output.get("feedback", "")
                state["rewrites"] = lg.output.get("rewrites", 0)
                # v2.0：replan_reasons 透出（critic 跨轮累积已随 run_log 落库），供 Inspector 分区渲染
                try:
                    _rr = lg.output.get("replan_reasons")
                    if isinstance(_rr, list):
                        state["replan_reasons"] = _rr
                except Exception:
                    pass
            if lg.agent_name == "executor" and isinstance(lg.output, dict):
                # v2.0：executor 落库失败即降级标记（前端降级 toast 以 state.degraded 为闸）
                try:
                    _persist = lg.output.get("persist")
                    if isinstance(_persist, dict) and _persist.get("error"):
                        state["degraded"] = True
                except Exception:
                    pass
            if lg.agent_name == "reviewer" and isinstance(lg.output, dict):
                # P3：reviewer输出 {review:{score,issues}} 兼容旧trace缺失则不置
                try:
                    state["review"] = lg.output.get("review", {}) or {}
                except Exception:
                    state["review"] = {}
            if lg.agent_name == "mentor" and isinstance(lg.output, dict):
                state["mentor_msg"] = lg.output.get("mentor_msg", "")
            if lg.agent_name == "reflector" and isinstance(lg.output, dict):
                patch = lg.output.get("patch", {}) or {}
                state["patch"] = patch
            # 保留每步 thought
            if isinstance(lg.input, dict) and lg.input.get("thought"):
                state.setdefault("thoughts", []).append(lg.input.get("thought"))
        # 统一 patch
        if not patch:
            # 兼容从最后一个 reflector 取
            refl = next((l for l in reversed(logs) if l.agent_name == "reflector"), None)
            if refl and isinstance(refl.output, dict):
                patch = refl.output.get("patch", {}) or {}
    except Exception:
        pass

    # v2.0：citations 反查（Task.source_agent="planner:{trace}" 行的 citations 合并，加法字段）
    # H1 兼容旧数据：写侧已统一 trace 式，读侧优先 trace 式；仅当 trace 式 0 行时回退
    # planner:multi 行并按本 trace goal_id 收敛（旧 multi 行无法直接归属 trace，不做全局 IN 防串 trace；
    # 重启/迁移后新写均为 trace 式，回退分支自然不再命中）。
    if session is not None:
        try:
            from app.models.task import Task

            _rows = session.exec(select(Task).where(Task.source_agent == f"planner:{trace_id}")).all()
            if not _rows:
                try:
                    _g = state.get("goal") if isinstance(state.get("goal"), dict) else None
                    _gid = _g.get("id") if isinstance(_g, dict) else None
                except Exception:
                    _gid = None
                if isinstance(_gid, int):
                    try:
                        _rows = session.exec(select(Task).where(Task.source_agent == "planner:multi", Task.goal_id == _gid)).all()
                    except Exception:
                        _rows = []
            _cits: list[dict] = []
            for _t in _rows or []:
                _c = getattr(_t, "citations", None)
                if isinstance(_c, list):
                    _cits.extend([x for x in _c if isinstance(x, dict)])
            if _cits:
                state["citations"] = _cits
        except Exception:
            pass
    state.setdefault("degraded", False)

    # 将 logs 转为可序列化 dict（供前端 tool_calls 展示）
    serial_logs = []
    for lg in logs:
        try:
            serial_logs.append(
                {
                    "id": lg.id,
                    "trace_id": lg.trace_id,
                    "agent_name": lg.agent_name,
                    "input": lg.input,
                    "output": lg.output,
                    "tool_calls": lg.tool_calls,
                    "created_at": lg.created_at.isoformat() if getattr(lg, "created_at", None) else None,
                }
            )
        except Exception:
            serial_logs.append({"trace_id": trace_id, "agent_name": getattr(lg, "agent_name", ""), "created_at": None})

    # state 快照：包含当前可展示的聚合状态
    # S7：内部调用纯函数 reduce_logs_to_snapshot 并附 snapshot 字段（旧字段全保留）
    try:
        _snapshot = reduce_logs_to_snapshot(logs)
    except Exception:
        _snapshot = {"transcript": [], "queues": {"pending": [], "running": [], "done": []}, "usage": {"persisted": False, "created": 0, "error": "", "count": 0}}
    return {"state": state, "logs": serial_logs, "patch": patch, "trace_id": trace_id, "snapshot": _snapshot}


# System Agent 单点对外智能体入口：POST /plans 即 SystemAgent.ainvoke，对内7子Agent
@router.post("/plans")
async def create_plan(payload: PlanCreate, request: Request, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id), mode: str = Query(default="multi")):
    check_rate_limit(request, user_id)
    goal = session.get(LearningGoal, payload.goal_id)
    if not goal or goal.user_id != user_id:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "目标不存在"})
    prefs = payload.preferences or {"hours_per_day": 2}
    h = prefs.get("hours_per_day", 2)
    try:
        h = int(h)
        if h < 1 or h > 8:
            raise ValueError()
    except Exception:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "hours_per_day 需1-8"})
    # 下周 Planner 合并：读取 reflection_report.next_plan_patch 按周 Wxx 并合并到 prefs（02-架构4.0）
    # 在校验之后合并，避免将非法 hours 误合并为合法而绕过 400
    try:
        if not prefs.get("_merged_from_patch"):
            from app.models.reflection import ReflectionReport

            latest = None
            try:
                latest = session.exec(select(ReflectionReport).where(ReflectionReport.user_id == user_id).order_by(ReflectionReport.week.desc())).first()  # type: ignore
            except Exception:
                try:
                    candidates = session.exec(select(ReflectionReport).where(ReflectionReport.user_id == user_id)).all()  # type: ignore
                    if candidates:
                        latest = sorted(candidates, key=lambda r: getattr(r, "week", ""), reverse=True)[0]
                except Exception:
                    latest = None
            if latest is not None and isinstance(getattr(latest, "next_plan_patch", None), dict) and latest.next_plan_patch:
                patch_prev = latest.next_plan_patch  # type: ignore
                try:
                    if "suggested_hours_per_day" in patch_prev:
                        try:
                            sug = int(patch_prev["suggested_hours_per_day"])
                            if 1 <= sug <= 8:
                                prefs = dict(prefs)
                                prefs["hours_per_day"] = sug
                                prefs["_merged_from_patch"] = True
                                prefs["_patch_week"] = getattr(latest, "week", "")
                        except Exception:
                            pass
                    if patch_prev.get("reduce_load") or patch_prev.get("reduce_daily_hours") or patch_prev.get("reduce_weekly"):
                        try:
                            cur = int(prefs.get("hours_per_day", 2))
                            if cur > 1 and "suggested_hours_per_day" not in patch_prev:
                                prefs = dict(prefs)
                                prefs["hours_per_day"] = max(1, cur - 1)
                                prefs["_merged_from_patch"] = True
                                prefs["_patch_reason"] = "reduce_load"
                        except Exception:
                            pass
                    for k in ("prefer_weekday", "focus_subject", "break_down", "add_buffer", "reallocate", "week_load", "next_week_hours"):
                        if k in patch_prev and k not in prefs:
                            prefs = dict(prefs)
                            prefs[k] = patch_prev[k]
                except Exception:
                    pass
    except Exception:
        pass
    # Wave B 会话语义：resume/fork/ephemeral/output_schema（Codex thread/resume + rollout三元组），默认旧语义零变化
    try:
        _resume_raw = getattr(payload, "resume", None)
    except Exception:
        _resume_raw = None
    try:
        _fork_flag = bool(getattr(payload, "fork", False))
    except Exception:
        _fork_flag = False
    try:
        _is_ephemeral = bool(getattr(payload, "ephemeral", False))
    except Exception:
        _is_ephemeral = False
    try:
        _output_schema = getattr(payload, "output_schema", None)
        if isinstance(_output_schema, str) and not _output_schema.strip():
            _output_schema = None
        if _output_schema is not None and not isinstance(_output_schema, str):
            _output_schema = str(_output_schema)
    except Exception:
        _output_schema = None
    citations: list = []
    _schema_fallback: bool = False
    try:
        _calendar_explicit = isinstance(prefs, dict) and ("require_calendar" in prefs)
    except Exception:
        _calendar_explicit = False
    try:
        _calendar_wanted = isinstance(prefs, dict) and prefs.get("require_calendar") is True
    except Exception:
        _calendar_wanted = False
    _forked_from: str | None = None
    _forked_from_seq: int | None = None
    _resolved_trace: str | None = None
    if isinstance(_resume_raw, str) and _resume_raw.strip():
        _resolved = _resolve_resume_trace(_resume_raw, user_id, session)
        if _resolved is None:
            raise HTTPException(status_code=404, detail={"code": 40401, "msg": "resume不存在"})
        _resolved_trace = _resolved
        if _fork_flag:
            _forked_from = _resolved
            try:
                _src_evs = _load_events_for_trace(_resolved, session, user_id)
                _forked_from_seq = len(_src_evs) if isinstance(_src_evs, list) else 0
            except Exception:
                _forked_from_seq = 0
            trace_id = uuid.uuid4().hex
        else:
            trace_id = _resolved
    else:
        trace_id = uuid.uuid4().hex
        if _fork_flag:
            # 无源fork视为普通新会话（forked_from留空，seq记0供可观测）
            _forked_from_seq = 0
    # 所有权绑定：新建/fork 新 id 记 owner；resume 复用已校验同用户，覆盖同值无害
    try:
        _TRACE_OWNERS[trace_id] = int(user_id)
        try:
            _TRACE_OWNERS_TS[trace_id] = time.time() + _TRACE_TTL
        except Exception:
            pass
        try:
            _TRACE_GOALS[trace_id] = int(getattr(goal, "id", 0) or 0)
            _TRACE_GOALS_TS[trace_id] = time.time() + _TRACE_TTL
        except Exception:
            pass
        _enforce_mem_cap(_TRACE_OWNERS)
        if _is_ephemeral:
            _EPHEMERAL_TRACES.add(trace_id)
            try:
                _EPHEMERAL_TS[trace_id] = time.time() + _TRACE_TTL
            except Exception:
                pass
        try:
            _cleanup_mem_boxes()
        except Exception:
            pass
    except Exception:
        pass
    # 一次性 SSE 票据：绑定 trace+user，TTL 60s，供 EventSource/无头场景兼容（ephemeral仅内存不写Redis）
    try:
        stream_ticket = _mint_stream_ticket(trace_id, user_id)
        if _is_ephemeral:
            try:
                _ticket_redis_del(stream_ticket)
            except Exception:
                pass
    except Exception:
        logger.warning("mint stream_ticket failed: trace_id=%s", trace_id, exc_info=True)
        stream_ticket = ""
    goal_dict = {"id": goal.id, "title": goal.title, "deadline": goal.deadline.isoformat(), "description": goal.description, "subject": goal.subject}

    # mode 判定：query ?mode=single 或环境 DISABLE_MULTI
    use_multi = mode != "single" and os.getenv("DISABLE_MULTI", "0") != "1"

    if use_multi:
        # 并行3检索 (Pi并行启示 + H-07 修复：异步走真实 embedding)
        async def _mem():
            try:
                from app.services.memory import asearch_memory

                return await asearch_memory(session, user_id, query=goal.title, top_k=5, type_="memory")
            except Exception:
                try:
                    return search_memory(session, user_id, query=goal.title, top_k=5, type_="memory")
                except Exception:
                    return []

        async def _vec():
            try:
                from app.services.memory import asearch_memory

                return await asearch_memory(session, user_id, query=goal.title, top_k=10, type_="knowledge")
            except Exception:
                try:
                    return search_memory(session, user_id, query=goal.title, top_k=10, type_="knowledge")
                except Exception:
                    return []
        async def _graph():
            try:
                from app.graph.neo import get_graph as _get_graph
                from app.graph.neo import search_prereqs as _search_prereqs
                g = _search_prereqs(goal.title)
                if goal.subject:
                    try: g = _get_graph(goal.subject).get("edges", [])[:10]
                    except Exception: pass
                return g
            except Exception: return []
        mems, vector_deps, graph_deps = await asyncio.gather(_mem(), _vec(), _graph())
        # 多Agent协作
        # S10 abort 透传初值：registry 签名不动，signal/abort_flag 经 state->context 透传（graph 节点转发）
        init_state = {
            "goal": goal_dict,
            "preferences": prefs,
            "trace_id": trace_id,
            "user_id": user_id,
            "memory": mems,
            "graphDeps": graph_deps,
            "vectorDeps": vector_deps,
            "milestones": [],
            "tasks": [],
            "critic_feedback": "",
            "mentor_msg": "",
            "rewrites": 0,
            "signal": {"abort_flag": False},
            "abort_flag": False,
        }
        # Wave B可观测：resume/fork透传（graph节点忽略未知键，旧语义零变化）
        try:
            if isinstance(_resume_raw, str) and _resume_raw.strip() and _resolved_trace:
                init_state["resume_from"] = _resolved_trace
            if _forked_from is not None:
                init_state["forked_from"] = _forked_from
                init_state["forked_from_seq"] = int(_forked_from_seq or 0)
        except Exception:
            pass

        # L1 真实节点事件流：事件按 7 节点真实执行序产出，8 事件契约扩展（reviewer 经 thought 透出，前端兼容）
        def _events_from_final_state(fs: dict) -> list[dict]:
            """astream 不可用时回退：ainvoke 完成后按最终态拼装事件（保持旧契约，追加 reviewer thought）。"""
            evs: list[dict] = []
            evs.append({"event": "thought", "data": {"agent": "planner", "text": fs.get("_thought", f"分析目标「{goal_dict['title']}」剩余时间，启动7节点协作...")}})
            evs.append({"event": "tool_call_start", "data": {"tool": "researcher", "agent": "researcher", "args": {"memory": len(mems), "vector": len(vector_deps), "graph": len(graph_deps)}}})
            evs.append({"event": "tool_call", "data": {"tool": "researcher", "args": {"memory": len(mems), "vector": len(vector_deps), "graph": len(graph_deps)}}})
            if mems:
                evs.append({"event": "tool_call_start", "data": {"tool": "memory_search", "agent": "researcher", "args": {"q": goal.title, "top_k": 5}}})
                evs.append({"event": "tool_call", "data": {"tool": "memory_search", "args": {"q": goal.title, "top_k": 5, "hits": len(mems)}}})
                evs.append({"event": "tool_call_end", "data": {"tool": "memory_search", "agent": "researcher", "result": {"hits": len(mems)}}})
            if vector_deps:
                evs.append({"event": "tool_call_start", "data": {"tool": "rag_search", "agent": "researcher", "args": {"q": goal.title}}})
                evs.append({"event": "tool_call", "data": {"tool": "rag_search", "args": {"q": goal.title, "hits": len(vector_deps)}}})
                evs.append({"event": "tool_call_end", "data": {"tool": "rag_search", "agent": "researcher", "result": {"hits": len(vector_deps)}}})
            if graph_deps:
                evs.append({"event": "tool_call_start", "data": {"tool": "graph_search", "agent": "researcher", "args": {"q": goal.title}}})
                evs.append({"event": "tool_call", "data": {"tool": "graph_search", "args": {"q": goal.title, "hits": len(graph_deps)}}})
                evs.append({"event": "tool_call_end", "data": {"tool": "graph_search", "agent": "researcher", "result": {"hits": len(graph_deps)}}})
            evs.append({"event": "tool_call_end", "data": {"tool": "researcher", "agent": "researcher", "result": {"memory": len(mems), "vector": len(vector_deps), "graph": len(graph_deps)}}})
            evs.append({"event": "tool_call", "data": {"tool": "planner_generate", "args": {"goal_id": goal_dict["id"], "days": len({t.get("date") for t in fs.get("tasks", [])})}}})
            for t in fs.get("tasks", []):
                evs.append({"event": "task_created", "data": {"task": {"title": t["title"], "planned_start": t["planned_start"], "planned_end": t["planned_end"], "priority": t.get("priority", 3)}}})
            evs.append({"event": "critic_feedback", "data": {"feedback": fs.get("critic_feedback", ""), "rewrites": fs.get("rewrites", 0)}})
            # P3 reviewer：经 thought 透出（前端 handleThought 兼容，无新事件类型，不崩旧契约）
            try:
                _rev = fs.get("_review") or {}
                _score = _rev.get("score", 100) if isinstance(_rev, dict) else 100
                _issues = _rev.get("issues", []) if isinstance(_rev, dict) else []
                evs.append({"event": "thought", "data": {"agent": "reviewer", "text": f"复核评分{_score}，问题{len(_issues)}个"}})
            except Exception:
                pass
            evs.append({"event": "mentor_msg", "data": {"text": fs.get("mentor_msg", "")}})
            evs.append({"event": "reflector_patch", "data": {"patch": fs.get("_patch", {}) or {}}})
            return evs

        async def _astream_run() -> tuple[dict, list[dict]]:
            """graph.astream(updates)：每节点完成即实时产出对应 SSE 事件（Pi checkpoint thread_id 可恢复）。

            S10 one-at-a-time 追问：主循环每节点 chunk 处理后检查本 trace steer 排队，
            简化实现为 planner chunk 后取首条拼入 goal.description 续跑一轮（取完即删）。
            S10 abort 透传：每 chunk 后将 request.is_disconnected 经 fs signal/abort_flag 透传，
            graph 节点 execute_tool 经 context={"signal":...} 转发（registry 签名不动）。
            """
            evs: list[dict] = []
            fs: dict = dict(init_state)
            seen_titles: set[str] = set()

            def emit(ev: str, data: dict) -> None:
                evs.append({"event": ev, "data": data})

            def _consume_one_steer() -> str | None:
                """取本 trace 排队首条（取完即删），无则 None。one-at-a-time 单条消费。"""
                try:
                    try:
                        _exp = _STEER_TS.get(trace_id)
                        if _exp is not None and float(_exp) <= time.time():
                            try:
                                _steer_box.pop(trace_id, None)
                            except Exception:
                                pass
                            try:
                                _STEER_TS.pop(trace_id, None)
                            except Exception:
                                pass
                            return None
                    except Exception:
                        pass
                    q = _steer_box.get(trace_id)
                    if not q:
                        return None
                    msg = q.pop(0)
                    if not q:
                        try:
                            _steer_box.pop(trace_id, None)
                        except Exception:
                            pass
                        try:
                            _STEER_TS.pop(trace_id, None)
                        except Exception:
                            pass
                    if isinstance(msg, str) and msg.strip():
                        return msg.strip()
                    return None
                except Exception:
                    return None

            def _inject_steer_to_goal(message: str) -> None:
                try:
                    g = fs.get("goal") or {}
                    if isinstance(g, dict):
                        desc = str(g.get("description") or "")
                        g = dict(g)
                        g["description"] = (desc + f"\n[追问] {message}").strip()
                        fs["goal"] = g
                    emit("thought", {"agent": "planner", "text": f"收到追问已并入目标：{message[:80]}"})
                except Exception:
                    pass

            async def _refresh_abort_flag() -> None:
                try:
                    disc = False
                    try:
                        if request is not None and hasattr(request, "is_disconnected"):
                            disc = bool(await request.is_disconnected())
                    except Exception:
                        disc = False
                    # Wave1 P0 中断盒：显式 abort 接口置位（_ABORT_TRACES），与 disconnect 同等处理
                    try:
                        try:
                            _aexp = _ABORT_TS.get(trace_id)
                            if _aexp is not None and float(_aexp) <= time.time():
                                try:
                                    _ABORT_TRACES.discard(trace_id)
                                except Exception:
                                    pass
                                try:
                                    _ABORT_TS.pop(trace_id, None)
                                except Exception:
                                    pass
                            elif trace_id in _ABORT_TRACES:
                                disc = True
                        except Exception:
                            try:
                                if trace_id in _ABORT_TRACES:
                                    disc = True
                            except Exception:
                                pass
                    except Exception:
                        pass
                    if disc:
                        try:
                            fs["abort_flag"] = True
                            fs["signal"] = {"abort_flag": True}
                        except Exception:
                            pass
                except Exception:
                    pass

            async def _one_pass(state_in: dict) -> None:
                async for chunk in multi_graph.astream(state_in, config={"configurable": {"thread_id": trace_id}}, stream_mode="updates"):
                    if not isinstance(chunk, dict):
                        continue
                    for node_name, update in chunk.items():
                        if not isinstance(update, dict):
                            continue
                        fs.update(update)
                        if node_name == "planner":
                            emit("thought", {"agent": "planner", "text": update.get("_thought", "")})
                            up_tasks = update.get("tasks", []) or []
                            emit("tool_call", {"tool": "planner_generate", "args": {"goal_id": goal_dict["id"], "days": len({t.get("date") for t in up_tasks if isinstance(t, dict) and t.get("date")})}})
                            for t in up_tasks:
                                # replan 重跑 planner 不重复下发 task_created（前端任务预览按 title 累积）
                                if not isinstance(t, dict) or not t.get("title") or t["title"] in seen_titles:
                                    continue
                                seen_titles.add(t["title"])
                                emit("task_created", {"task": {"title": t["title"], "planned_start": t["planned_start"], "planned_end": t["planned_end"], "priority": t.get("priority", 3)}})
                            # S10 one-at-a-time：planner chunk 后检查本 trace steer 排队，首条拼入 goal 续跑（取完即删）
                            try:
                                _msg = _consume_one_steer()
                                if _msg:
                                    _inject_steer_to_goal(_msg)
                            except Exception:
                                pass
                        elif node_name == "researcher":
                            mem_n = len(update.get("memory", []) or [])
                            vec_n = len(update.get("vectorDeps", []) or [])
                            graph_n = len(update.get("graphDeps", []) or [])
                            emit("tool_call_start", {"tool": "researcher", "agent": "researcher", "args": {"memory": mem_n, "vector": vec_n, "graph": graph_n}})
                            emit("tool_call", {"tool": "researcher", "args": {"memory": mem_n, "vector": vec_n, "graph": graph_n}})
                            if mem_n:
                                emit("tool_call_start", {"tool": "memory_search", "agent": "researcher", "args": {"q": goal.title, "top_k": 5}})
                                emit("tool_call", {"tool": "memory_search", "args": {"q": goal.title, "top_k": 5, "hits": mem_n}})
                                emit("tool_call_end", {"tool": "memory_search", "agent": "researcher", "result": {"hits": mem_n}})
                            if vec_n:
                                emit("tool_call_start", {"tool": "rag_search", "agent": "researcher", "args": {"q": goal.title}})
                                emit("tool_call", {"tool": "rag_search", "args": {"q": goal.title, "hits": vec_n}})
                                emit("tool_call_end", {"tool": "rag_search", "agent": "researcher", "result": {"hits": vec_n}})
                            if graph_n:
                                emit("tool_call_start", {"tool": "graph_search", "agent": "researcher", "args": {"q": goal.title}})
                                emit("tool_call", {"tool": "graph_search", "args": {"q": goal.title, "hits": graph_n}})
                                emit("tool_call_end", {"tool": "graph_search", "agent": "researcher", "result": {"hits": graph_n}})
                            emit("tool_call_end", {"tool": "researcher", "agent": "researcher", "result": {"memory": mem_n, "vector": vec_n, "graph": graph_n}})
                        elif node_name == "executor":
                            # 契约中 executor 无专属事件类型，不产出（保持 8 事件数量与旧实现一致）
                            pass
                        elif node_name == "critic":
                            emit("critic_feedback", {"feedback": update.get("critic_feedback", ""), "rewrites": fs.get("rewrites", 0)})
                        elif node_name == "reviewer":
                            # P3：经 thought 透出，前端兼容（handleThought 按 agent 归类，不新增事件类型）
                            try:
                                _r = update.get("_review") or {}
                                _s = _r.get("score", 100) if isinstance(_r, dict) else 100
                                _is = _r.get("issues", []) if isinstance(_r, dict) else []
                                emit("thought", {"agent": "reviewer", "text": update.get("_thought", f"复核评分{_s}，问题{len(_is)}个")})
                            except Exception:
                                emit("thought", {"agent": "reviewer", "text": update.get("_thought", "")})
                        elif node_name == "mentor":
                            emit("mentor_msg", {"text": update.get("mentor_msg", "")})
                        elif node_name == "reflector":
                            emit("reflector_patch", {"patch": update.get("_patch", {}) or {}})
                    # S10 abort 透传：每 chunk 处理后同步 disconnect 到 fs；Pi对标(agent.ts AbortController)：
                    # 中断即停，跳出本轮不再消费后续 chunk（registry 签名不动，context 带 abort_flag）
                    await _refresh_abort_flag()
                    try:
                        if fs.get("abort_flag"):
                            return
                    except Exception:
                        pass

            await _one_pass(init_state)
            try:
                _aborted = bool(fs.get("abort_flag", False))
            except Exception:
                _aborted = False
            if _aborted:
                # 中断闭环：事件落盘可续播，但跳过追问续跑与后续写库（done.cancelled 由调用方追加）
                try:
                    evs[:] = _drop_partial_events(evs)
                except Exception:
                    pass
                try:
                    fs["cancelled"] = True
                except Exception:
                    pass
                try:
                    _ABORT_TRACES.discard(trace_id)
                    _ABORT_TS.pop(trace_id, None)
                except Exception:
                    pass
                return fs, evs
            # S10 追问续跑一轮（one-at-a-time）：主循环后若仍有排队（非 planner 阶段到达），逐条拼入 goal 续跑，最多 2 轮防循环
            try:
                for _round in range(2):
                    _pending = _consume_one_steer()
                    if not _pending:
                        break
                    _inject_steer_to_goal(_pending)
                    try:
                        await _one_pass(dict(fs))
                    except Exception:
                        break
            except Exception:
                pass
            # S7 禁存半包：最终 events 落盘前过滤（_plan_events_set 内亦二次过滤，双保险）
            try:
                evs[:] = _drop_partial_events(evs)
            except Exception:
                pass
            try:
                _ABORT_TRACES.discard(trace_id)
                _ABORT_TS.pop(trace_id, None)
            except Exception:
                pass
            return fs, evs

        async def _ainvoke_run() -> tuple[dict, list[dict]]:
            # Pi checkpoint 启示：带 thread_id 可恢复（对标 SessionState lane）
            try:
                fs = await multi_graph.ainvoke(init_state, config={"configurable": {"thread_id": trace_id}})
            except TypeError:
                # 无 checkpointer 时回退
                fs = await multi_graph.ainvoke(init_state)
            return fs, _events_from_final_state(fs)

        # Wave A 审批网关：四档 + execpolicy 三值决策表；need_approval 旧变量保留做兼容映射
        try:
            approval_mode = _normalize_approval_mode(payload)
        except Exception:
            approval_mode = _DEFAULT_APPROVAL_MODE
        try:
            need_approval = _resolve_need_approval(approval_mode, payload)
        except Exception:
            need_approval = bool(getattr(payload, "require_approval", False))
        # 拦截标记：Prompt 需跨实例可见；never 直拒亦需阻塞防 graph 内提前落库（无 Redis 等待）
        # ephemeral 同样阻塞（guard 按 _EPHEMERAL_TRACES 拦截，防 multi 经 executor 直写 DB）
        try:
            _should_block = bool(need_approval) or (approval_mode == "never") or bool(_is_ephemeral)
        except Exception:
            _should_block = bool(need_approval)
        if _should_block:
            _APPROVAL_BLOCK_TRACES.add(trace_id)
            _block_redis_add(trace_id, _approval_timeout_value())
        try:
            try:
                final_state, events = await _astream_run()
            except TypeError:
                # astream 不可用回退 ainvoke，事件按最终态拼装（契约不变）
                final_state, events = await _ainvoke_run()
        finally:
            if _should_block:
                _APPROVAL_BLOCK_TRACES.discard(trace_id)
                _block_redis_del(trace_id)

        tasks_raw = final_state.get("tasks", [])
        mentor_msg = final_state.get("mentor_msg", "")
        critic_fb = final_state.get("critic_feedback", "")
        rewrites = final_state.get("rewrites", 0)
        source = "multi"
        # Wave B output_schema：非空时终态tasks校验失败则降级mock重算一次（简化：必需键title/planned_start/planned_end）
        if _output_schema:
            try:
                if not _validate_tasks_for_schema(tasks_raw):
                    try:
                        from app.services.planner import mock_generate as _mock_gen

                        _mk_out = _mock_gen(goal_dict, prefs, trace_id)
                        try:
                            if isinstance(_mk_out, (list, tuple)) and len(_mk_out) == 3:
                                _mk_tasks, _mk_mentor, _ = _mk_out  # type: ignore[misc]
                            else:
                                _mk_tasks, _mk_mentor = _mk_out  # type: ignore[misc]
                        except ValueError:
                            _mk_tasks, _mk_mentor = [], ""
                        if isinstance(_mk_tasks, list) and _mk_tasks:
                            tasks_raw = _mk_tasks
                            try:
                                _schema_fallback = True
                            except Exception:
                                pass
                            try:
                                final_state["tasks"] = list(tasks_raw)
                            except Exception:
                                pass
                            if isinstance(_mk_mentor, str) and _mk_mentor:
                                mentor_msg = _mk_mentor
                                try:
                                    final_state["mentor_msg"] = mentor_msg
                                except Exception:
                                    pass
                    except Exception:
                        logger.warning("output_schema mock fallback failed: trace_id=%s", trace_id, exc_info=True)
            except Exception:
                pass
        # 写库审批网关：executor 产出 tasks_raw 后、write_tasks 落库前拦截
        # 决策表：Forbidden 直接拒（不进Redis）；Prompt 走现有Redis拦截；Allow 直行
        approval_approved: bool | None = None
        approval_timed_out = False
        _gw_decision = None
        _gw_handling = "allow"
        try:
            _cancelled_pre = bool(final_state.get("cancelled", False))
        except Exception:
            _cancelled_pre = False
        if _cancelled_pre:
            _gw_handling = "allow"
        else:
            try:
                _plan_action = f"tasks.batch:{len(tasks_raw or [])}" if len(tasks_raw or []) > 50 else "write_tasks"
                _gw_decision, _gw_handling = _decide_gateway(_plan_action, approval_mode, need_approval)
            except Exception:
                _gw_handling = "prompt" if need_approval else "allow"
        _need_prompt_flow = (_gw_handling == "prompt")
        _need_forbidden_reject = (_gw_handling == "forbidden")
        # 显式 Allow 直行（need_approval=True 但决策 Allow）：无需拦截，直接视为批准
        if need_approval and _gw_handling == "allow" and not _cancelled_pre:
            approval_approved = True
        if _need_forbidden_reject and not _cancelled_pre:
            approval_approved = False
            approval_timed_out = False
            try:
                if approval_mode == "never":
                    _rej_note = "never模式下Prompt自动降为Forbidden，直接拒绝写库，仅展示任务预览。"
                else:
                    _rej_note = "命中禁止规则，直接拒绝写库，仅展示任务预览。"
                events.append({"event": "mentor_msg", "data": {"text": _rej_note}})
                try:
                    mentor_msg = f"{mentor_msg} {_rej_note}".strip() if mentor_msg else _rej_note
                except Exception:
                    pass
            except Exception:
                pass
        if _need_prompt_flow:
            try:
                approve_token = _mint_approval(trace_id, tasks_raw, user_id, goal_id=getattr(goal, "id", None))
                # ephemeral：审批态仅内存，不写 Redis（与票据/事件同策略，防 Redis 残留）
                if _is_ephemeral:
                    try:
                        _approval_redis_del(trace_id)
                    except Exception:
                        pass
            except Exception:
                logger.warning("mint approval failed: trace_id=%s", trace_id, exc_info=True)
                approve_token = secrets.token_urlsafe(32)
                _APPROVALS[trace_id] = {"token": approve_token, "tasks_raw": list(tasks_raw or []), "exp": time.time() + float(_approval_timeout_value()), "approved": None, "user_id": int(user_id), "created_at": time.time()}
                try:
                    _enforce_mem_cap(_APPROVALS)
                    if not _is_ephemeral:
                        _approval_redis_set(trace_id, _APPROVALS[trace_id], float(_approval_timeout_value()))
                except Exception:
                    pass
            preview = _build_tasks_preview(tasks_raw)
            total = len(tasks_raw or [])
            try:
                _available = _approval_available_decisions(_gw_decision if _gw_decision is not None else "prompt")
            except Exception:
                _available = ["reject", "approve_with_condition"]
            events.append({"event": "approval_required", "data": {"trace_id": trace_id, "tasks_preview": preview, "approve_token": approve_token, "expires_in": int(float(_approval_timeout_value())), "total_count": total, "total": total, "count": total, "available_decisions": _available}})
            # 中间落盘以便 SSE 续播（approval_required 进 events / cache:workbench / plan:events，ephemeral仅内存）
            try:
                _persist_events_for_trace(trace_id, list(events), _is_ephemeral)
            except Exception:
                pass
            try:
                if not _is_ephemeral:
                    _cache_set_workbench_user(trace_id, list(events), user_id)
                else:
                    # ephemeral仅内存：plan_store已在_persist内写入，不写Redis workbench
                    pass
            except Exception:
                logger.warning("cache_set_workbench failed (approval pending): trace_id=%s", trace_id, exc_info=True)
            try:
                decision = await _wait_approval(trace_id)
            except Exception:
                logger.warning("wait approval failed: trace_id=%s", trace_id, exc_info=True)
                decision = None
            if decision is True:
                approval_approved = True
            elif decision is False:
                approval_approved = False
            else:
                approval_approved = False
                approval_timed_out = True
                try:
                    ent = _approval_get_merged(trace_id)
                    if ent is not None and ent.get("approved") is None:
                        _APPROVALS.pop(trace_id, None)
                        _approval_redis_del(trace_id)
                except Exception:
                    pass
            if not approval_approved:
                if approval_timed_out:
                    reject_note = "审批超时未决（安全默认拒绝），已取消写库，仅展示任务预览。"
                else:
                    reject_note = "审批未通过，已取消写库，仅展示任务预览。"
                events.append({"event": "mentor_msg", "data": {"text": reject_note}})
                try:
                    mentor_msg = f"{mentor_msg} {reject_note}".strip() if mentor_msg else reject_note
                except Exception:
                    pass
        # 事件序列 (ReAct 7节点 + 8事件扩展reviewer thought；审批流追加第10种 approval_required，旧事件语义不动) + 会话压
        from app.agents.compaction import should_compact, summarize
        try:
            _done_cancelled = bool(final_state.get("cancelled", False))
        except Exception:
            _done_cancelled = False
        if _done_cancelled:
            # 中断闭环：done.cancelled 替代常规 done，保证单 done 事件
            events.append({"event": "done", "data": {"trace_id": trace_id, "count": 0, "source": source, "rewrites": rewrites, "cancelled": True}})
        if _done_cancelled:
            pass
        elif need_approval or _need_prompt_flow or _need_forbidden_reject:
            _done_count = len(tasks_raw or []) if approval_approved else 0
            events.append({"event": "done", "data": {"trace_id": trace_id, "count": _done_count, "source": source, "rewrites": rewrites, "approved": bool(approval_approved)}})
        else:
            # P2：非审批流 done 亦带 approved=True（无须审批即视为已批准，保持 SSE 契约一致）
            events.append({"event": "done", "data": {"trace_id": trace_id, "count": len(tasks_raw), "source": source, "rewrites": rewrites, "approved": True}})
        try:
            if _schema_fallback:
                for _de in events:
                    try:
                        if isinstance(_de, dict) and _de.get("event") == "done" and isinstance(_de.get("data"), dict):
                            _de["data"]["schema_fallback"] = True
                    except Exception:
                        continue
        except Exception:
            pass
        # Wave B fork可观测：done.data附forked_from/forked_from_seq（取源events长度），不改旧键
        if _forked_from is not None:
            try:
                _done_ev = next((e for e in reversed(events) if isinstance(e, dict) and e.get("event") == "done"), None)
                if isinstance(_done_ev, dict):
                    _dd = _done_ev.get("data")
                    if isinstance(_dd, dict):
                        _dd["forked_from"] = _forked_from
                        _dd["forked_from_seq"] = int(_forked_from_seq or 0)
            except Exception:
                pass
        # 会话压：超阈值则摘要；审批流需保 approval_required 不被压掉（tail2 会因拒绝追加 mentor_msg 而丢事件）
        if should_compact(events):
            _approval_ev = next((e for e in events if isinstance(e, dict) and e.get("event") == "approval_required"), None) if need_approval else None
            events = summarize(events)
            if need_approval and _approval_ev is not None and not any(isinstance(e, dict) and e.get("event") == "approval_required" for e in events):
                try:
                    _done_idx = max((i for i, e in enumerate(events) if isinstance(e, dict) and e.get("event") == "done"), default=len(events))
                    events.insert(_done_idx, _approval_ev)
                except Exception:
                    pass
            # Wave B：compaction后重附fork标记（summarize可能丢done扩展键）
            if _forked_from is not None:
                try:
                    _done_ev2 = next((e for e in reversed(events) if isinstance(e, dict) and e.get("event") == "done"), None)
                    if isinstance(_done_ev2, dict) and isinstance(_done_ev2.get("data"), dict):
                        _done_ev2["data"].setdefault("forked_from", _forked_from)
                        _done_ev2["data"].setdefault("forked_from_seq", int(_forked_from_seq or 0))
                except Exception:
                    pass
        # Pi PlanStore 启示：内存缓存（DB已在下方7条agent_run_log，Redis cache:workbench另存 + plan:events 3600s；ephemeral仅内存）
        try:
            _persist_events_for_trace(trace_id, events, _is_ephemeral)
        except Exception:
            pass
        # Wave B：rollout persist已在_persist内完成（含过滤+链），不再用未过滤events覆盖plan_store，避免噪音回写
        # Redis cache:workbench:{trace_id} 5m（SSE 断线重放；ephemeral跳过不写Redis；user绑定双写）
        try:
            if not _is_ephemeral:
                _cache_set_workbench_user(trace_id, events, user_id)
        except Exception:
            logger.warning("cache_set_workbench failed: trace_id=%s", trace_id, exc_info=True)

        # 落库 Task batch (带证据引用)，坏时间跳过不中断
        # 优先采信 executor 经 write_tasks 工具（schema校验/before/after/事件生命周期）的落库结果，
        # 失败/降级时回退本端直插（state 内透传，链路不崩溃）
        persist_info = final_state.get("task_persist") or {}
        citations = [{"chunk_id": v["id"], "score": v["score"]} for v in (vector_deps[:2] if vector_deps else [])]
        created = []
        try:
            _cancelled = bool(final_state.get("cancelled", False))
        except Exception:
            _cancelled = False
        if _cancelled:
            # Pi对标abort：中断后不做任何写库（executor已落库行一并回滚），仅保留事件与日志可追溯
            if persist_info.get("persisted"):
                try:
                    _rollback_premature_tasks(session, persist_info.get("rows", []), goal.id, trace_id)
                except Exception:
                    logger.warning("rollback cancelled tasks failed: trace_id=%s", trace_id, exc_info=True)
            created = []
        if _cancelled:
            pass
        elif need_approval and not approval_approved:
            # 拒绝/超时：跳过落库；若 graph 内 write_tasks 已提前落库则回滚，保证无落库
            if persist_info.get("persisted"):
                try:
                    _rollback_premature_tasks(session, persist_info.get("rows", []), goal.id, trace_id)
                except Exception:
                    logger.warning("rollback premature tasks failed: trace_id=%s", trace_id, exc_info=True)
            created = []
        elif _is_ephemeral:
            # Wave B ephemeral：只走内存+SSE，不写DB（executor 若已落库先回滚，再构造瞬态对象供回显）
            if persist_info.get("persisted"):
                try:
                    _rollback_premature_tasks(session, persist_info.get("rows", []), goal.id, trace_id)
                except Exception:
                    logger.warning("rollback ephemeral tasks failed: trace_id=%s", trace_id, exc_info=True)
            for tr in tasks_raw:
                try:
                    s = _safe_parse_dt(tr.get("planned_start"))
                    e = _safe_parse_dt(tr.get("planned_end"))
                    if not s or not e or s >= e:
                        continue
                    t = Task(
                        goal_id=goal.id,
                        title=str(tr.get("title", "任务"))[:200],
                        planned_start=s,
                        planned_end=e,
                        priority=tr.get("priority", 3),
                        status="todo",
                        # H1 写侧统一 trace 式（ephemeral 瞬态亦一致，便于回显归属）。
                        source_agent=f"planner:{trace_id}",
                        citations=citations,
                    )
                    created.append(t)
                except Exception:
                    continue
        elif persist_info.get("persisted"):
            created = [r for r in persist_info.get("rows", []) if isinstance(r, dict)]
        else:
            for tr in tasks_raw:
                s = _safe_parse_dt(tr.get("planned_start"))
                e = _safe_parse_dt(tr.get("planned_end"))
                if not s or not e or s >= e:
                    logger.warning("skip malformed task: %r", tr.get("title"))
                    continue
                t = Task(
                    goal_id=goal.id,
                    title=str(tr.get("title", "任务"))[:200],
                    planned_start=s,
                    planned_end=e,
                    priority=tr.get("priority", 3),
                    status="todo",
                    # H1 写侧统一 trace 式（原 planner:multi 致 inspector 反查 0 行）。
                    source_agent=f"planner:{trace_id}",
                    citations=citations,
                )
                session.add(t)
                created.append(t)
            session.commit()
            for c in created:
                session.refresh(c)

        # P2 批准后自动触发落库已在上分支完成；此处追加日历同步（工具存在则调，否则跳过，永不阻断）
        # 拒绝/超时分支 created=[]，天然跳过；批准分支 created 非空才尝试；ephemeral 跳过外部副作用
        if need_approval and approval_approved and created and not _is_ephemeral:
            try:
                _cal_res = await _try_calendar_sync(created, trace_id)
                try:
                    logger.info("calendar sync after approval: trace_id=%s res=%s", trace_id, _cal_res)
                except Exception:
                    pass
            except Exception:
                logger.warning("calendar sync after approval failed (skip): trace_id=%s", trace_id, exc_info=True)

        # 落库 7 条 agent_run_log (ReAct+双校验+复核+个性化+反思，P3新增reviewer；ephemeral跳过不写DB)
        researcher_out = {"memory": len(mems) if mems is not None else 0, "vector": len(vector_deps) if vector_deps is not None else 0, "graph": len(graph_deps) if graph_deps is not None else 0}
        reflector_patch = final_state.get("_patch", {})
        replan_reasons = final_state.get("replan_reasons", []) or []
        review_out = final_state.get("_review", {}) or {}
        # reviewer 缺失时回退默认满分（executor直通等极端分支兜底，保证7条完整）
        if not isinstance(review_out, dict) or "score" not in review_out:
            try:
                _fb_tmp = critic_fb or ""
                _iss = [s.strip() for s in _fb_tmp.replace("；", ";").split(";") if s.strip()] if _fb_tmp else []
                _sc = 0 if not tasks_raw else max(0, 100 - 20 * len(_iss))
                review_out = {"score": int(_sc), "issues": _iss}
            except Exception:
                review_out = {"score": 100 if tasks_raw else 0, "issues": []}
        logs = [
            AgentRunLog(trace_id=trace_id, agent_name="planner", input={"goal": goal_dict, "preferences": prefs, "thought": final_state.get("_thought","")}, output={"tasks": tasks_raw}, tool_calls=[{"tool": "planner_generate"}]),
            AgentRunLog(trace_id=trace_id, agent_name="researcher", input={"goal": goal_dict}, output=researcher_out, tool_calls=[{"tool": "memory_search"}, {"tool": "rag_search"}, {"tool": "graph_search"}]),
            AgentRunLog(trace_id=trace_id, agent_name="executor", input={"tasks": tasks_raw}, output={"count": len(tasks_raw), "persist": {"persisted": bool(persist_info.get("persisted")), "created": persist_info.get("created", 0), "error": persist_info.get("error", "")}}, tool_calls=[]),
            AgentRunLog(trace_id=trace_id, agent_name="critic", input={"tasks": tasks_raw, "graphDeps": graph_deps if graph_deps is not None else []}, output={"feedback": critic_fb, "rewrites": rewrites, "llm": bool(critic_fb), "replan_reasons": replan_reasons}, tool_calls=[{"tool": "rule_check"}, {"tool": "llm_check"}]),
            AgentRunLog(trace_id=trace_id, agent_name="reviewer", input={"tasks": tasks_raw, "critic_feedback": critic_fb}, output={"review": review_out, "score": review_out.get("score", 100), "issues": review_out.get("issues", [])}, tool_calls=[]),
            AgentRunLog(trace_id=trace_id, agent_name="mentor", input={"feedback": critic_fb, "memory": mems[:2] if mems else []}, output={"mentor_msg": mentor_msg}, tool_calls=[]),
            AgentRunLog(trace_id=trace_id, agent_name="reflector", input={"feedback": critic_fb}, output={"patch": reflector_patch}, tool_calls=[]),
        ]
        if not _is_ephemeral:
            for l in logs:
                session.add(l)
            session.commit()
        else:
            # ephemeral：agent_run_log跳过落库，仅保留内存logs供graph快照
            pass

        # 生成 graph 缓存 cache:graph:{trace_id} 5m（ephemeral跳过不写Redis；user绑定双写）
        try:
            graph_data = _build_graph_from_logs(logs, trace_id)
            if not _is_ephemeral:
                _cache_set_graph_user(trace_id, graph_data, user_id)
        except Exception:
            logger.warning("build/cache graph failed: trace_id=%s", trace_id, exc_info=True)

        # Wave B fork回执：forked_from/forked_from_seq（新trace+源长度），非fork不含（旧契约零变化）
        try:
            _fork_extra: dict = {}
            if _forked_from is not None:
                _fork_extra = {"forked_from": _forked_from, "forked_from_seq": int(_forked_from_seq or 0)}
        except Exception:
            _fork_extra = {}
        if need_approval:
            _data_appr = {"trace_id": trace_id, "tasks": created, "mentor_msg": mentor_msg, "citations": citations, "mode": "multi", "rewrites": rewrites, "critic_feedback": critic_fb, "replan_reasons": replan_reasons, "stream_ticket": stream_ticket, "stream_ticket_expires_in": _STREAM_TICKET_TTL, "approved": bool(approval_approved)}
            try:
                _data_appr.update(_fork_extra)
            except Exception:
                pass
            try:
                if _schema_fallback:
                    _data_appr["schema_fallback"] = True
            except Exception:
                pass
            try:
                _TRACE_CITATIONS[trace_id] = list(citations or [])
                _TRACE_CITATIONS_TS[trace_id] = time.time() + _TRACE_TTL
            except Exception:
                pass
            try:
                if _calendar_explicit:
                    _cal_synced = False
                    try:
                        _cs = (persist_info or {}).get("calendar_sync") or {}
                        if isinstance(_cs, dict) and _cs.get("enabled") and int(_cs.get("ok", 0) or 0) > 0:
                            _cal_synced = True
                    except Exception:
                        pass
                    try:
                        if "_cal_res" in dir() or "_cal_res" in locals():
                            pass
                    except Exception:
                        pass
                    try:
                        _cr = locals().get("_cal_res")
                        if isinstance(_cr, dict) and not _cr.get("skipped") and int(_cr.get("synced", 0) or 0) > 0:
                            _cal_synced = True
                    except Exception:
                        pass
                    _data_appr["calendar"] = {"synced": bool(_cal_synced)}
            except Exception:
                pass
            try:
                _steer_box.pop(trace_id, None)
                _STEER_TS.pop(trace_id, None)
            except Exception:
                pass
            return {"code": 200, "msg": "ok", "data": _data_appr}
        _data_multi = {"trace_id": trace_id, "tasks": created, "mentor_msg": mentor_msg, "citations": citations, "mode": "multi", "rewrites": rewrites, "critic_feedback": critic_fb, "replan_reasons": replan_reasons, "stream_ticket": stream_ticket, "stream_ticket_expires_in": _STREAM_TICKET_TTL}
        try:
            _data_multi.update(_fork_extra)
        except Exception:
            pass
        try:
            if _schema_fallback:
                _data_multi["schema_fallback"] = True
        except Exception:
            pass
        try:
            _TRACE_CITATIONS[trace_id] = list(citations or [])
            _TRACE_CITATIONS_TS[trace_id] = time.time() + _TRACE_TTL
        except Exception:
            pass
        try:
            if _calendar_explicit:
                _cal_synced_m = False
                try:
                    _csm = (persist_info or {}).get("calendar_sync") or {}
                    if isinstance(_csm, dict) and _csm.get("enabled") and int(_csm.get("ok", 0) or 0) > 0:
                        _cal_synced_m = True
                except Exception:
                    pass
                try:
                    _crm = locals().get("_cal_res")
                    if isinstance(_crm, dict) and not _crm.get("skipped") and int(_crm.get("synced", 0) or 0) > 0:
                        _cal_synced_m = True
                except Exception:
                    pass
                _data_multi["calendar"] = {"synced": bool(_cal_synced_m)}
        except Exception:
            pass
        try:
            _steer_box.pop(trace_id, None)
            _STEER_TS.pop(trace_id, None)
        except Exception:
            pass
        return {"code": 200, "msg": "ok", "data": _data_multi}

    else:
        tasks_raw, mentor_msg, source = await generate_plan(goal_dict, prefs, trace_id)
        # Wave B output_schema：单轨同样校验，失败则mock重算一次（generate_plan已mock兜底，此处二次保险）
        if _output_schema:
            try:
                if not _validate_tasks_for_schema(tasks_raw):
                    try:
                        from app.services.planner import mock_generate as _mock_gen_single

                        _mk_out2 = _mock_gen_single(goal_dict, prefs, trace_id)
                        try:
                            if isinstance(_mk_out2, (list, tuple)) and len(_mk_out2) == 3:
                                _mk2, _mm2, _ = _mk_out2  # type: ignore[misc]
                            else:
                                _mk2, _mm2 = _mk_out2  # type: ignore[misc]
                        except ValueError:
                            _mk2, _mm2 = [], ""
                        if isinstance(_mk2, list) and _mk2:
                            tasks_raw = _mk2
                            try:
                                _schema_fallback = True
                            except Exception:
                                pass
                            if isinstance(_mm2, str) and _mm2:
                                mentor_msg = _mm2
                    except Exception:
                        pass
            except Exception:
                pass
        # 构造单轨 8事件（保持与 multi 一致的结构，方便工作台消费）
        events = []
        events.append({"event": "thought", "data": {"agent": "planner", "text": f"单轨规划「{goal_dict['title']}」启动"}})
        events.append({"event": "tool_call_start", "data": {"tool": source, "agent": "planner", "args": {"goal_id": goal_dict["id"]}}})
        events.append({"event": "tool_call", "data": {"tool": source, "args": {"goal_id": goal_dict["id"], "days": len({t.get('date') for t in tasks_raw})}}})
        events.append({"event": "tool_call_end", "data": {"tool": source, "agent": "planner", "result": {"count": len(tasks_raw)}}})
        for t in tasks_raw:
            events.append({"event": "task_created", "data": {"task": {"title": t["title"], "planned_start": t["planned_start"], "planned_end": t["planned_end"], "priority": t.get("priority", 3)}}})
        events.append({"event": "critic_feedback", "data": {"feedback": "", "rewrites": 0}})
        events.append({"event": "mentor_msg", "data": {"text": mentor_msg}})
        events.append({"event": "reflector_patch", "data": {"patch": {}}})
        # P2：单轨 done 补 approved=True（与 multi 审批流一致，compaction 保 done 不被压）
        events.append({"event": "done", "data": {"trace_id": trace_id, "count": len(tasks_raw), "source": source, "rewrites": 0, "approved": True}})
        try:
            if _schema_fallback:
                for _de in events:
                    try:
                        if isinstance(_de, dict) and _de.get("event") == "done" and isinstance(_de.get("data"), dict):
                            _de["data"]["schema_fallback"] = True
                    except Exception:
                        continue
        except Exception:
            pass
        # Wave B fork可观测：单轨done同样附fork标记
        if _forked_from is not None:
            try:
                _sd = events[-1].get("data") if isinstance(events[-1], dict) else None
                if isinstance(_sd, dict):
                    _sd["forked_from"] = _forked_from
                    _sd["forked_from_seq"] = int(_forked_from_seq or 0)
            except Exception:
                pass
        try:
            _persist_events_for_trace(trace_id, events, _is_ephemeral)
        except Exception:
            pass
        try:
            if not _is_ephemeral:
                _cache_set_workbench_user(trace_id, events, user_id)
        except Exception:
            logger.warning("cache_set_workbench failed (single): trace_id=%s", trace_id, exc_info=True)
        created = []
        if _is_ephemeral:
            # Wave B ephemeral单轨：Task/agent_run_log跳过落库，仅内存+SSE
            for tr in tasks_raw:
                try:
                    s = _safe_parse_dt(tr.get("planned_start"))
                    e = _safe_parse_dt(tr.get("planned_end"))
                    if not s or not e or s >= e:
                        continue
                    t = Task(
                        goal_id=goal.id,
                        title=str(tr.get("title", "任务"))[:200],
                        planned_start=s,
                        planned_end=e,
                        priority=tr.get("priority", 3),
                        status="todo",
                        # H1 写侧统一 trace 式（原 planner:{mock|llm} 致 inspector 反查 0 行）。
                        source_agent=f"planner:{trace_id}",
                        citations=[],
                    )
                    created.append(t)
                except Exception:
                    continue
        else:
            for tr in tasks_raw:
                s = _safe_parse_dt(tr.get("planned_start"))
                e = _safe_parse_dt(tr.get("planned_end"))
                if not s or not e or s >= e:
                    logger.warning("skip malformed task (single): %r", tr.get("title"))
                    continue
                t = Task(
                    goal_id=goal.id,
                    title=str(tr.get("title", "任务"))[:200],
                    planned_start=s,
                    planned_end=e,
                    priority=tr.get("priority", 3),
                    status="todo",
                    # H1 写侧统一 trace 式（原 planner:{mock|llm} 致 inspector 反查 0 行）。
                    source_agent=f"planner:{trace_id}",
                    citations=[],
                )
                session.add(t)
                created.append(t)
            session.commit()
            for c in created:
                session.refresh(c)
        log = AgentRunLog(
            trace_id=trace_id,
            agent_name="planner",
            input={"goal": goal_dict, "preferences": prefs},
            output={"tasks": tasks_raw, "mentor_msg": mentor_msg},
            tool_calls=[{"tool": source, "count": len(tasks_raw)}],
        )
        if not _is_ephemeral:
            session.add(log)
            session.commit()
        # 单轨同样缓存 graph（仅 planner 节点，其余 pending；ephemeral跳过Redis；user绑定双写）
        try:
            if not _is_ephemeral:
                logs_for_graph = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at)).all()  # type: ignore
                graph_data = _build_graph_from_logs(list(logs_for_graph), trace_id)
                _cache_set_graph_user(trace_id, graph_data, user_id)
        except Exception:
            logger.warning("build/cache graph failed (single): trace_id=%s", trace_id, exc_info=True)
        try:
            _fork_extra_single: dict = {"forked_from": _forked_from, "forked_from_seq": int(_forked_from_seq or 0)} if _forked_from is not None else {}
        except Exception:
            _fork_extra_single = {}
        _data_single = {"trace_id": trace_id, "tasks": created, "mentor_msg": mentor_msg, "citations": citations, "mode": "single", "stream_ticket": stream_ticket, "stream_ticket_expires_in": _STREAM_TICKET_TTL}
        try:
            _data_single.update(_fork_extra_single)
        except Exception:
            pass
        try:
            if _schema_fallback:
                _data_single["schema_fallback"] = True
        except Exception:
            pass
        try:
            _TRACE_CITATIONS[trace_id] = list(citations or [])
            _TRACE_CITATIONS_TS[trace_id] = time.time() + _TRACE_TTL
        except Exception:
            pass
        try:
            if _calendar_explicit:
                _data_single["calendar"] = {"synced": False}
        except Exception:
            pass
        try:
            _steer_box.pop(trace_id, None)
            _STEER_TS.pop(trace_id, None)
        except Exception:
            pass
        return {"code": 200, "msg": "ok", "data": _data_single}


@router.get("/plans/pending-approvals")
def list_pending_approvals(user_id: int = Depends(get_current_user_id)):
    """待审批发现：POST multi+require_approval 会阻塞等待，客户端先调此接口发现
    trace_id，再经 GET /plans/stream 取 approval_required 事件拿 token，最后调
    approve 接口批准/拒绝。只返回本人的未决项，不含 token。Redis 优先、内存回退。"""
    now = time.time()
    items = []
    merged: dict[str, dict] = {}
    try:
        for tid, ent in list(_APPROVALS.items()):
            if isinstance(ent, dict):
                merged[tid] = ent
    except Exception:
        pass
    try:
        r = _get_redis()
        if r is not None:
            try:
                for k in r.keys("plan:approval:*"):
                    try:
                        tid = k.split("plan:approval:", 1)[1] if ":" in k else k
                        raw = r.get(k)
                        if not raw:
                            continue
                        ent = json.loads(raw)
                        if isinstance(ent, dict) and tid not in merged:
                            merged[tid] = ent
                    except Exception:
                        continue
            except Exception:
                _mark_redis_dead()
    except Exception:
        logger.warning("list pending approvals failed", exc_info=True)
    try:
        for tid, ent in list(merged.items()):
            try:
                if ent.get("approved") is not None:
                    continue
                if float(ent.get("exp", 0)) <= now:
                    continue
                if ent.get("user_id") is not None and int(ent.get("user_id")) != int(user_id):
                    continue
                items.append({
                    "trace_id": tid,
                    "goal_id": ent.get("goal_id"),
                    "preview_count": len(ent.get("tasks_raw") or []),
                    "expires_in": max(0, int(float(ent.get("exp", now)) - now)),
                })
            except Exception:
                continue
    except Exception:
        logger.warning("list pending approvals failed", exc_info=True)
    items.sort(key=lambda x: x["expires_in"])
    return {"code": 200, "msg": "ok", "data": {"items": items, "total": len(items)}}


@router.get("/plans/approve-rules")
def list_approve_rules(session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """Wave A 规则列表：返回内存规则快照，仅需登录（不绑 trace）。

    契约：GET /api/v1/plans/approve-rules → {rules:[{prefix,decision,justification}], total}（包在 data 内）。
    注：必须注册在所有 /plans/{trace_id} 系路由之前，否则被当 trace_id 吃掉。
    """
    try:
        try:
            _exec_policy.load_from_db(session)
        except Exception as e:
            logger.warning("approve-rules load db failed: %s", e)
    except Exception:
        pass
    try:
        snap = _exec_policy.list_rules()
    except Exception:
        snap = {}
    rules = []
    try:
        for prefix in sorted(snap.keys()):
            try:
                ent = snap.get(prefix) or {}
                rules.append({
                    "prefix": prefix,
                    "decision": ent.get("decision"),
                    "justification": ent.get("justification"),
                })
            except Exception:
                continue
    except Exception:
        pass
    return {"code": 200, "msg": "ok", "data": {"rules": rules, "total": len(rules)}}


@router.delete("/plans/approve-rules")
def delete_approve_rule(payload: dict | None = None, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """Wave A 规则删除：body {prefix}，内存幂等删除，仅需登录（不绑 trace）。

    契约：DELETE /api/v1/plans/approve-rules → {deleted:bool}（包在 data 内）；
    prefix 为空 40001；不存在的 prefix 返回 {deleted:false} 200（幂等）。
    注：必须注册在所有 /plans/{trace_id} 系路由之前。
    """
    try:
        body = payload if isinstance(payload, dict) else {}
    except Exception:
        body = {}
    try:
        prefix = str(body.get("prefix") or "").strip()
    except Exception:
        prefix = ""
    if not prefix:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "prefix 不能为空"})
    try:
        try:
            _exec_policy.load_from_db(session)
        except Exception as e:
            logger.warning("approve-rules delete load db failed: %s", e)
    except Exception:
        pass
    try:
        deleted = _exec_policy.remove_rule(prefix)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": str(e)[:200]})
    except Exception as e:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": f"规则删除失败: {e}"[:200]})
    if deleted:
        try:
            try:
                _exec_policy.save_to_db(session)
            except Exception as e:
                logger.warning("approve-rules delete persist failed: %s", e)
        except Exception:
            pass
    return {"code": 200, "msg": "ok", "data": {"deleted": bool(deleted)}}


@router.post("/plans/{trace_id}/approve")
def approve_plan(trace_id: str, payload: ApproveRequest, request: Request, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """写库审批：token 一次性核销，幂等返回首次结果；无效/过期 → 404 {code:40401}。Redis 优先、内存回退。"""
    try:
        _cleanup_mem_boxes()
    except Exception:
        pass
    try:
        check_rate_limit(request, user_id)
    except HTTPException:
        raise
    except Exception:
        pass
    entry = _approval_get_merged(trace_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "token无效或已过期"})
    try:
        if float(entry.get("exp", 0)) <= time.time():
            _APPROVALS.pop(trace_id, None)
            _approval_redis_del(trace_id)
            raise HTTPException(status_code=404, detail={"code": 40401, "msg": "token无效或已过期"})
    except HTTPException:
        raise
    except Exception:
        _APPROVALS.pop(trace_id, None)
        _approval_redis_del(trace_id)
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "token无效或已过期"})
    # 归属校验：复用 _resolve_trace_user；审批等待期日志尚未落库时回退内存 user_id
    try:
        resolved = _resolve_trace_user(session, trace_id)
    except Exception:
        resolved = None
    stored_uid = entry.get("user_id")
    if resolved is not None and resolved != user_id:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    if resolved is None and stored_uid is not None:
        try:
            if int(stored_uid) != int(user_id):
                raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
        except HTTPException:
            raise
        except Exception:
            pass
    try:
        req_token = str(payload.token or "")
    except Exception:
        req_token = ""
    if not req_token or req_token != entry.get("token"):
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "token无效或已过期"})
    if entry.get("approved") is not None:
        return {"code": 200, "msg": "ok", "data": {"approved": bool(entry.get("approved")), "trace_id": trace_id}}
    try:
        approved_bool = bool(payload.approved)
    except Exception:
        approved_bool = False
    entry["approved"] = approved_bool
    entry["decided_at"] = time.time()
    try:
        entry["exp"] = time.time() + float(_approval_timeout_value())
    except Exception:
        pass
    try:
        _APPROVALS[trace_id] = entry
        _enforce_mem_cap(_APPROVALS)
    except Exception:
        pass
    try:
        # ephemeral 审批决议仅内存，不写 Redis
        if trace_id not in _EPHEMERAL_TRACES:
            _approval_redis_set(trace_id, entry, float(_approval_timeout_value()))
    except Exception:
        pass
    return {"code": 200, "msg": "ok", "data": {"approved": approved_bool, "trace_id": trace_id}}


@router.post("/plans/{trace_id}/approve-rule")
def approve_rule(trace_id: str, payload: dict, request: Request, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """Wave A 规则追加：body {prefix, decision[, justification]}，内存幂等追加，全局生效。

    - decision 三值：Allow/Prompt/Forbidden（大小写兼容，deny/reject/blocked 归一为 Forbidden）；
    - 同 prefix+同 decision 重复调用幂等（返回相同结果），同 prefix 不同 decision 后写覆盖；
    - Wave1 P0 鉴权：session 用户==trace 归属（复用 _enforce_trace_owner/_TRACE_OWNERS），跨用户 403；全局表保留。
    """
    try:
        _enforce_trace_owner(trace_id, user_id, session)
    except HTTPException as _oe:
        try:
            if int(getattr(_oe, "status_code", 404) or 404) == 404:
                raise HTTPException(status_code=403, detail={"code": 40301, "msg": "无权限"})
        except HTTPException:
            raise
        raise
    try:
        _cleanup_mem_boxes()
    except Exception:
        pass
    try:
        check_rate_limit(request, user_id)
    except HTTPException:
        raise
    except Exception:
        pass
    try:
        body = payload if isinstance(payload, dict) else {}
    except Exception:
        body = {}
    try:
        prefix = str(body.get("prefix") or "").strip()
    except Exception:
        prefix = ""
    if not prefix:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "prefix 不能为空"})
    try:
        dec_raw = body.get("decision")
    except Exception:
        dec_raw = None
    if not isinstance(dec_raw, str) or not dec_raw.strip():
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "decision 须为 Allow/Prompt/Forbidden"})
    try:
        justification = body.get("justification")
    except Exception:
        justification = None
    try:
        try:
            _exec_policy.load_from_db(session)
        except Exception as e:
            logger.warning("approve-rule load db failed: %s", e)
    except Exception:
        pass
    try:
        dec, just = _exec_policy.add_rule(prefix, dec_raw, justification)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": str(e)[:200]})
    except Exception as e:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": f"规则追加失败: {e}"[:200]})
    try:
        try:
            _exec_policy.save_to_db(session)
        except Exception as e:
            logger.warning("approve-rule persist failed: %s", e)
    except Exception:
        pass
    try:
        dec_str = dec.value if hasattr(dec, "value") else str(dec)
    except Exception:
        dec_str = str(dec_raw).strip()
    return {"code": 200, "msg": "ok", "data": {"trace_id": trace_id, "prefix": prefix, "decision": dec_str, "justification": just}}


@router.post("/plans/{trace_id}/steer")
def steer_plan(trace_id: str, payload: dict, request: Request, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """S10 SSE 追问 one-at-a-time：body {message} 入队，返回 queued=1。

    运行中追问按单条消费注入下轮 planner（见 _astream_run planner chunk 后检查）；
    队列为内存 list，取完即删；空消息 400；归属强制（DB/内存owner/approval 三层，不一致 404）。
    """
    try:
        _cleanup_mem_boxes()
    except Exception:
        pass
    try:
        check_rate_limit(request, user_id)
    except HTTPException:
        raise
    except Exception:
        pass
    _enforce_trace_owner(trace_id, user_id, session)
    try:
        _done_evs = _plan_events_get(trace_id)
        if isinstance(_done_evs, list) and any(isinstance(e, dict) and e.get("event") == "done" for e in _done_evs):
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "trace已结束，拒收追问"})
    except HTTPException:
        raise
    except Exception:
        pass
    try:
        msg = (payload or {}).get("message", "")
        msg = str(msg or "").strip()
    except Exception:
        msg = ""
    if not msg:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "message 不能为空"})
    if len(msg) > 2000:
        msg = msg[:2000]
    try:
        try:
            _sexp = _STEER_TS.get(trace_id)
            if _sexp is not None and float(_sexp) <= time.time():
                try:
                    _steer_box.pop(trace_id, None)
                except Exception:
                    pass
                _STEER_TS.pop(trace_id, None)
        except Exception:
            pass
        q = _steer_box.setdefault(trace_id, [])
        q.append(msg)
        try:
            _STEER_TS[trace_id] = time.time() + _STEER_TTL
        except Exception:
            pass
        # 上限防膨胀：只保留最近 5 条（one-at-a-time 消费首条）
        if len(q) > 5:
            del q[0 : len(q) - 5]
    except Exception:
        try:
            _steer_box[trace_id] = [msg]
            try:
                _STEER_TS[trace_id] = time.time() + _STEER_TTL
            except Exception:
                pass
        except Exception:
            pass
    return {"code": 200, "msg": "ok", "data": {"queued": 1, "trace_id": trace_id}}


@router.get("/plans/{trace_id}/steer")
def get_steer_queue(trace_id: str, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    try:
        _cleanup_mem_boxes()
    except Exception:
        pass
    _enforce_trace_owner(trace_id, user_id, session)
    try:
        _sexp = _STEER_TS.get(trace_id)
        if _sexp is not None and float(_sexp) <= time.time():
            try:
                _steer_box.pop(trace_id, None)
            except Exception:
                pass
            try:
                _STEER_TS.pop(trace_id, None)
            except Exception:
                pass
            return {"code": 200, "msg": "ok", "data": {"queued": [], "trace_id": trace_id}}
    except Exception:
        pass
    try:
        q = list(_steer_box.get(trace_id) or [])
    except Exception:
        q = []
    return {"code": 200, "msg": "ok", "data": {"queued": q, "trace_id": trace_id}}


@router.post("/plans/{trace_id}/abort")
def abort_plan(trace_id: str, payload: dict | None = None, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """Wave1 P0 前端取消：body {}，置该 trace abort_flag（_ABORT_TRACES 内存盒）。

    - 归属校验复用 _enforce_trace_owner（不一致 404）；
    - _astream 每 chunk 检查该盒（见 _refresh_abort_flag），state 不可达故经内存盒透传；
    - 契约固定：POST /api/v1/plans/{trace_id}/abort → {aborted:true}（包在 data 内）。
    """
    try:
        _cleanup_mem_boxes()
    except Exception:
        pass
    _enforce_trace_owner(trace_id, user_id, session)
    try:
        _ABORT_TRACES.add(trace_id)
        try:
            _ABORT_TS[trace_id] = time.time() + _ABORT_TTL
        except Exception:
            pass
        if len(_ABORT_TRACES) > 500:
            # M5：按 _ABORT_TS 时间戳淘汰最早（原 set.pop() 任意淘汰）。
            try:
                _oldest = min(
                    list(_ABORT_TRACES),
                    key=lambda k: float(_ABORT_TS.get(k, 0) or 0),
                )
                _ABORT_TRACES.discard(_oldest)
                _ABORT_TS.pop(_oldest, None)
            except Exception:
                try:
                    _ABORT_TRACES.pop()
                except Exception:
                    pass
        try:
            _cleanup_mem_boxes()
        except Exception:
            pass
    except Exception:
        try:
            _ABORT_TRACES.add(trace_id)
            try:
                _ABORT_TS[trace_id] = time.time() + _ABORT_TTL
            except Exception:
                pass
        except Exception:
            pass
    return {"code": 200, "msg": "ok", "data": {"aborted": True, "trace_id": trace_id}}


@router.get("/plans/stream")
async def stream_plan(
    trace_id: str = Query(...),
    request: Request = None,
    last_event_id: str | None = Query(default=None),
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    ticket: str | None = Query(default=None),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    session: Session = Depends(get_session),
):
    # P0 鉴权优先级：Authorization Bearer 优先 > ticket(一次性) > 原 JWT/X-User-Id 逻辑（ticket 无效不放宽）
    user_id: int | None = _try_bearer_user_id(authorization)
    if user_id is None and ticket:
        _ticket_uid = _consume_stream_ticket(ticket, trace_id)
        if _ticket_uid is not None:
            user_id = _ticket_uid
    if user_id is None:
        user_id = get_current_user_id(authorization, x_user_id)
    # 所有权校验：trace 归属用户联查，不一致 404（防枚举泄露他人轨迹）
    resolved = _resolve_trace_user(session, trace_id)
    if resolved is not None and resolved != user_id:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    if resolved is None:
        # 无归属可判（空计划/旧数据/不存在）：debug/pytest 放行走下方常规 404 流程，prod 直接 404
        from app.core.config import get_settings

        if not (get_settings().debug or os.getenv("PYTEST_CURRENT_TEST")):
            raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    # 优先 Redis cache:workbench user绑定键（miss回读旧键）5m（支持 Last-Event-ID 续播），回退 plan:events/plan_store/DB（Pi SessionState 回退启示）
    events = None
    # 1) Redis cache 优先（user绑定优先新键）
    try:
        events = _cache_get_workbench_user(trace_id, user_id)
    except Exception:
        logger.warning("cache_get_workbench failed: trace_id=%s", trace_id, exc_info=True)
        events = None
    # 1b) plan:events:{trace} 3600s（Redis 优先、内存回退）
    if not events:
        try:
            events = _plan_events_get(trace_id)
        except Exception:
            logger.warning("plan_events fallback failed: trace_id=%s", trace_id, exc_info=True)
            events = None
    # 2) PlanStore DB 回退
    if not events:
        try:
            if hasattr(plan_store, "get_or_reconstruct"):
                events = plan_store.get_or_reconstruct(trace_id, session)  # type: ignore
            else:
                events = plan_store.get(trace_id)  # type: ignore
        except Exception:
            logger.warning("plan_store fallback failed: trace_id=%s", trace_id, exc_info=True)
            events = plan_store.get(trace_id)  # type: ignore
    if not events:
        # DB回退：从 agent_run_log 重建（兼容旧版 plan_store）
        logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at)).all()
        if not logs:
            raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
        planner_log = next((l for l in logs if l.agent_name == "planner"), logs[0])
        out = planner_log.output or {}
        tasks_raw = out.get("tasks", []) if isinstance(out, dict) else []
        events = []
        events.append({"event": "thought", "data": {"agent": "planner", "text": "从DB恢复的规划轨迹..."}})
        for t in tasks_raw:
            if isinstance(t, dict):
                title = t.get("title", "任务")
                ps = t.get("planned_start", "")
                pe = t.get("planned_end", "")
                pri = t.get("priority", 3)
            else:
                title = getattr(t, "title", "任务")
                ps = str(getattr(t, "planned_start", ""))
                pe = str(getattr(t, "planned_end", ""))
                pri = getattr(t, "priority", 3)
            events.append({"event": "task_created", "data": {"task": {"title": title, "planned_start": ps, "planned_end": pe, "priority": pri}}})
        mentor = next((l.output.get("mentor_msg") for l in logs if l.agent_name == "mentor" and isinstance(l.output, dict)), "")
        if mentor:
            events.append({"event": "mentor_msg", "data": {"text": mentor}})
        # P2：DB 恢复 done 补 approved=True（compaction 保 done，SSE 契约一致）
        events.append({"event": "done", "data": {"trace_id": trace_id, "count": len([e for e in events if e["event"]=="task_created"]), "source": "db_recover", "approved": True}})
        try:
            plan_store.put(trace_id, events, session)  # type: ignore
        except Exception:
            logger.warning("plan_store.put failed: trace_id=%s", trace_id, exc_info=True)
            try:
                _plan_events_set(trace_id, events)
            except Exception:
                pass
            try:
                plan_store[trace_id] = events  # type: ignore
            except Exception:
                pass
        try:
            _cache_set_workbench_user(trace_id, events, user_id)
        except Exception:
            logger.warning("cache_set_workbench failed (recover): trace_id=%s", trace_id, exc_info=True)

    # 解析 last_event_id 断点续传：优先标准 Header，回退 Query（EventSource 无法自定义 Header 时前端用 query）
    effective_last = last_event_id_header or last_event_id
    if not effective_last and request is not None:
        try:
            # 兼容大小写及下划线变体（前端用 last_event_id）
            effective_last = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")  # type: ignore
            if not effective_last:
                # 兼容 query 别名 lastEventId
                qp = request.query_params
                effective_last = qp.get("last_event_id") or qp.get("lastEventId") or qp.get("Last-Event-ID")
        except Exception:
            pass
    start_idx = 0
    if effective_last and str(effective_last).isdigit():
        start_idx = int(effective_last) + 1

    async def gen():
        idx = start_idx
        for ev in events[start_idx:]:  # type: ignore
            # SSE 格式: event + data + id (ensure_ascii=False 保留中文，charset=utf-8)，带 retry:3000
            yield {
                "event": ev["event"],
                "data": json.dumps(ev["data"], ensure_ascii=False),
                "id": str(idx),
                "retry": 3000,
            }
            idx += 1
        # 心跳结束

    return EventSourceResponse(gen(), headers={"Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/plans/sessions")
def list_plan_sessions(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    try:
        _cleanup_mem_boxes()
    except Exception:
        pass
    # M8：先按当前用户 goal_ids 过滤 trace 再查日志（原全表 select AgentRunLog 内存分页 OOM）；返回结构不变，DB 分页语义由 trace 级 IN 查询+内存页切片保持。
    try:
        _user_gids: set[int] = set()
        try:
            _gid_rows = session.exec(select(LearningGoal.id).where(LearningGoal.user_id == user_id)).all()
            for _g in (_gid_rows or []):
                try:
                    _gi = int(_g[0] if isinstance(_g, (list, tuple)) else _g)
                    _user_gids.add(_gi)
                except Exception:
                    continue
        except Exception:
            _user_gids = set()
    except Exception:
        _user_gids = set()
    # 候选 trace：Task(trace式 source_agent + 用户 goal) ∪ planner 日志(goal归属用户)；避免全表拉其他用户日志。
    _candidate_traces: set[str] = set()
    try:
        if _user_gids:
            try:
                _trows = session.exec(select(Task.source_agent).where(Task.goal_id.in_(list(_user_gids)))).all()
                for _r in (_trows or []):
                    try:
                        _sa = _r[0] if isinstance(_r, (list, tuple)) else _r
                        if isinstance(_sa, str) and _sa.startswith("planner:") and _sa != "planner:multi":
                            _candidate_traces.add(_sa.split(":", 1)[1])
                    except Exception:
                        continue
            except Exception:
                pass
            try:
                _plogs = session.exec(select(AgentRunLog.trace_id, AgentRunLog.input).where(AgentRunLog.agent_name == "planner")).all()
                for _pr in (_plogs or []):
                    try:
                        _tid, _inp = (_pr[0], _pr[1]) if isinstance(_pr, (list, tuple)) else (getattr(_pr, "trace_id", None), getattr(_pr, "input", None))
                        _gg = _inp.get("goal") if isinstance(_inp, dict) else None
                        _gid2 = _gg.get("id") if isinstance(_gg, dict) else None
                        if isinstance(_gid2, int) and _gid2 in _user_gids and isinstance(_tid, str):
                            _candidate_traces.add(_tid)
                    except Exception:
                        continue
            except Exception:
                pass
    except Exception:
        pass
    try:
        if _candidate_traces:
            logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id.in_(list(_candidate_traces))).order_by(AgentRunLog.created_at, AgentRunLog.id)).all()
        else:
            logs = []
    except Exception:
        logs = []
    if logs is None:
        logs = []
    trace_logs: dict[str, list[AgentRunLog]] = {}
    for lg in (logs or []):
        try:
            trace_logs.setdefault(lg.trace_id, []).append(lg)
        except Exception:
            continue
    try:
        from app.services.planner import plan_store as _ps_sess
        try:
            _mem_keys = list(_ps_sess.keys())
        except Exception:
            _mem_keys = []
    except Exception:
        _mem_keys = []
    try:
        for _k in list(_TRACE_OWNERS.keys()) + list(_TRACE_GOALS.keys()):
            if _k not in trace_logs and _k not in _mem_keys:
                _mem_keys.append(_k)
    except Exception:
        pass
    try:
        for _k in list(_mem_keys):
            try:
                if _k in trace_logs:
                    continue
                _owner = _TRACE_OWNERS.get(_k)
                if _owner is not None and int(_owner) != int(user_id):
                    continue
                _gid = _TRACE_GOALS.get(_k)
                if _gid is None:
                    try:
                        _ent = _approval_get_merged(_k)
                        if isinstance(_ent, dict) and isinstance(_ent.get("goal_id"), int):
                            _gid = _ent.get("goal_id")
                    except Exception:
                        pass
                if _gid is None:
                    continue
                trace_logs[_k] = []
            except Exception:
                continue
    except Exception:
        pass
    if not trace_logs:
        return {"code": 200, "msg": "ok", "data": {"items": [], "total": 0, "page": page, "size": size}}
    goal_ids: set[int] = set()
    trace_candidates: dict[str, list[tuple[int | None, str | None]]] = {}
    for trace_id, tlogs in trace_logs.items():
        candidates: list[tuple[int | None, str | None]] = []
        for l in (tlogs or []):
            try:
                if l.agent_name == "planner" and isinstance(l.input, dict):
                    g = l.input.get("goal")
                    if isinstance(g, dict):
                        gid = g.get("id") if isinstance(g.get("id"), int) else None
                        title = g.get("title") if isinstance(g.get("title"), str) else None
                        candidates.append((gid, title))
                        if gid is not None:
                            goal_ids.add(gid)
            except Exception:
                continue
        if not candidates:
            try:
                _mg = _TRACE_GOALS.get(trace_id)
                if isinstance(_mg, int):
                    candidates.append((_mg, None))
                    goal_ids.add(_mg)
                else:
                    try:
                        _ent2 = _approval_get_merged(trace_id)
                        if isinstance(_ent2, dict) and isinstance(_ent2.get("goal_id"), int):
                            candidates.append((_ent2.get("goal_id"), None))
                            goal_ids.add(_ent2.get("goal_id"))
                    except Exception:
                        pass
            except Exception:
                pass
        trace_candidates[trace_id] = candidates
    goal_map: dict[int, LearningGoal] = {}
    if goal_ids:
        try:
            goal_rows = session.exec(select(LearningGoal).where(LearningGoal.id.in_(list(goal_ids)))).all()
            goal_map = {g.id: g for g in goal_rows if g.id is not None}
        except Exception:
            goal_map = {}
    items: list[dict] = []
    for trace_id, tlogs in trace_logs.items():
        goal_id = None
        for gid, _title in trace_candidates[trace_id]:
            if gid is not None and gid in goal_map:
                goal_id = gid
                break
        if goal_id is None:
            continue
        try:
            goal = goal_map[goal_id]
        except Exception:
            continue
        try:
            if goal.user_id != user_id:
                continue
        except Exception:
            continue
        try:
            _is_eph = trace_id in _EPHEMERAL_TRACES
        except Exception:
            _is_eph = False
        _degraded = False
        try:
            for l in (tlogs or []):
                try:
                    if getattr(l, "agent_name", "") != "executor":
                        continue
                    _out = getattr(l, "output", None) or {}
                    if not isinstance(_out, dict):
                        continue
                    _persist = _out.get("persist")
                    if isinstance(_persist, dict) and _persist.get("error"):
                        _degraded = True
                        break
                except Exception:
                    continue
        except Exception:
            pass
        _cits: list = []
        try:
            _c = _TRACE_CITATIONS.get(trace_id)
            if isinstance(_c, list):
                _cits = [x for x in _c if isinstance(x, dict)]
        except Exception:
            _cits = []
        if tlogs:
            try:
                times = [l.created_at for l in tlogs if getattr(l, "created_at", None) is not None]
            except Exception:
                times = []
            try:
                started_at = min(times).isoformat() if times else None
            except Exception:
                started_at = None
            try:
                last_event_at = max(times).isoformat() if times else None
            except Exception:
                last_event_at = None
            try:
                agent_names = {l.agent_name for l in tlogs}
            except Exception:
                agent_names = set()
            mode = "multi" if agent_names - {"planner"} else "single"
            rewrites = 0
            for l in tlogs:
                try:
                    if l.agent_name != "critic":
                        continue
                    out = l.output if isinstance(l.output, dict) else {}
                    val = out.get("rewrites", 0)
                    if isinstance(val, int) and not isinstance(val, bool) and val > rewrites:
                        rewrites = val
                except Exception:
                    continue
            patch_replan = False
            for l in tlogs:
                try:
                    if l.agent_name != "reflector":
                        continue
                    out = l.output if isinstance(l.output, dict) else {}
                    patch = out.get("patch")
                    if isinstance(patch, dict) and any(k in patch for k in ("reduce_load", "add_buffer", "reallocate")):
                        patch_replan = True
                except Exception:
                    continue
            node_summary: dict[str, dict] = {}
            for name in AGENT_ORDER:
                entry = {"has_log": name in agent_names}
                if name == "critic":
                    entry["rewrites"] = rewrites
                if name == "reflector":
                    entry["replan"] = patch_replan
                node_summary[name] = entry
            if "reflector" in agent_names:
                status = "completed"
            elif rewrites > 0 or patch_replan:
                status = "replan"
            else:
                status = "running"
            _ev_count = len(tlogs)
        else:
            try:
                _mem_evs = _plan_events_get(trace_id)
                if not isinstance(_mem_evs, list):
                    try:
                        from app.services.planner import plan_store as _ps2
                        _mem_evs = _ps2.get(trace_id)
                    except Exception:
                        _mem_evs = None
            except Exception:
                _mem_evs = None
            try:
                _ev_list = _mem_evs if isinstance(_mem_evs, list) else []
            except Exception:
                _ev_list = []
            _ev_count = len(_ev_list)
            try:
                _has_multi = any(isinstance(e, dict) and (e.get("event") in ("approval_required",) or (isinstance(e.get("data"), dict) and e.get("data").get("tool") in ("researcher", "planner_generate"))) for e in _ev_list)
            except Exception:
                _has_multi = True
            mode = "multi" if _has_multi else "single"
            try:
                _has_done = any(isinstance(e, dict) and e.get("event") == "done" for e in _ev_list)
            except Exception:
                _has_done = False
            status = "completed" if _has_done else "running"
            node_summary = {}
            try:
                for name in AGENT_ORDER:
                    entry = {"has_log": False}
                    if name == "planner":
                        entry["has_log"] = True
                    if name == "critic":
                        entry["rewrites"] = 0
                    if name == "reflector":
                        entry["replan"] = False
                    node_summary[name] = entry
            except Exception:
                node_summary = {}
            try:
                from datetime import UTC as _UTC, datetime as _DT
                _now_iso = _DT.now(_UTC).isoformat()
            except Exception:
                _now_iso = None
            started_at = _now_iso
            last_event_at = _now_iso
        items.append(
            {
                "trace_id": trace_id,
                "mode": mode,
                "goal_id": goal_id,
                "goal_title": goal.title,
                "started_at": started_at,
                "last_event_at": last_event_at,
                "event_count": _ev_count,
                "node_summary": node_summary,
                "status": status,
                "ephemeral": bool(_is_eph),
                "degraded": bool(_degraded),
                "citations": list(_cits),
                "citations_count": len(_cits),
            }
        )
    items.sort(key=lambda it: it["last_event_at"] or "", reverse=True)
    total = len(items)
    page_items = items[(page - 1) * size : page * size]
    return {"code": 200, "msg": "ok", "data": {"items": page_items, "total": total, "page": page, "size": size}}



@router.delete("/plans/sessions/{trace_id}")
def delete_plan_session(trace_id: str, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    try:
        _cleanup_mem_boxes()
    except Exception:
        pass
    _enforce_trace_owner(trace_id, user_id, session)
    try:
        logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id)).all()
    except Exception:
        logs = []
    if not logs:
        try:
            _ev = _plan_events_get(trace_id)
            if not isinstance(_ev, list) or not _ev:
                try:
                    from app.services.planner import plan_store as _ps_del
                    _ev2 = _ps_del.get(trace_id)
                    if not isinstance(_ev2, list) or not _ev2:
                        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
                except HTTPException:
                    raise
                except Exception:
                    raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    try:
        for lg in (logs or []):
            try:
                session.delete(lg)
            except Exception:
                continue
        # H3：同步删该 trace 的 Task（trace 式 source_agent 行）；旧 planner:multi 行无法归属 trace，删不动（见注释）。
        try:
            _tasks = session.exec(select(Task).where(Task.source_agent == f"planner:{trace_id}")).all()
            for _t in (_tasks or []):
                try:
                    session.delete(_t)
                except Exception:
                    continue
        except Exception:
            pass
        try:
            session.commit()
        except Exception:
            # H3：commit 失败必须 rollback 后 500（原 pass 仍返 deleted:true 为假成功）。
            try:
                session.rollback()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail={"code": 50001, "msg": "删除会话失败"})
    except HTTPException:
        raise
    except Exception:
        # H3：未知异常亦 rollback 后 500，不返假成功。
        try:
            session.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail={"code": 50001, "msg": "删除会话失败"})
    try:
        try:
            from app.services.planner import plan_store as _ps_del2
            _ps_del2.pop(trace_id, None)
        except Exception:
            pass
        try:
            _plan_events_ts.pop(trace_id, None)
        except Exception:
            pass
        try:
            _redis_del(f"plan:events:{trace_id}")
        except Exception:
            pass
        try:
            _APPROVALS.pop(trace_id, None)
        except Exception:
            pass
        try:
            _approval_redis_del(trace_id)
        except Exception:
            pass
        try:
            _block_redis_del(trace_id)
        except Exception:
            pass
        try:
            _APPROVAL_BLOCK_TRACES.discard(trace_id)
        except Exception:
            pass
        try:
            _steer_box.pop(trace_id, None)
            _STEER_TS.pop(trace_id, None)
        except Exception:
            pass
        try:
            _ABORT_TRACES.discard(trace_id)
            _ABORT_TS.pop(trace_id, None)
        except Exception:
            pass
        try:
            _TRACE_OWNERS.pop(trace_id, None)
            _TRACE_OWNERS_TS.pop(trace_id, None)
        except Exception:
            pass
        try:
            _EPHEMERAL_TRACES.discard(trace_id)
            _EPHEMERAL_TS.pop(trace_id, None)
        except Exception:
            pass
        try:
            _TRACE_GOALS.pop(trace_id, None)
            _TRACE_GOALS_TS.pop(trace_id, None)
        except Exception:
            pass
        try:
            _TRACE_CITATIONS.pop(trace_id, None)
            _TRACE_CITATIONS_TS.pop(trace_id, None)
        except Exception:
            pass
        try:
            _cache_set_workbench_user(trace_id, [], user_id)
        except Exception:
            pass
        try:
            from app.core.cache import set_graph as _sg
            try:
                _sg(trace_id, {"nodes": [], "edges": [], "status": "deleted", "trace_id": trace_id}, user_id=int(user_id))
            except Exception:
                pass
            try:
                _sg(trace_id, {"nodes": [], "edges": [], "status": "deleted", "trace_id": trace_id})
            except Exception:
                pass
        except Exception:
            pass
    except Exception:
        pass
    return {"code": 200, "msg": "ok", "data": {"deleted": True, "trace_id": trace_id}}


@router.get("/plans/{trace_id}/logs")
def get_logs(trace_id: str, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    resolved = _resolve_trace_user(session, trace_id)
    if resolved is not None and resolved != user_id:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at, AgentRunLog.id)).all()
    if not logs:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "日志不存在"})
    return {"code": 200, "msg": "ok", "data": logs}


@router.get("/plans/{trace_id}/graph")
def get_graph_api(trace_id: str, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    resolved = _resolve_trace_user(session, trace_id)
    if resolved is not None and resolved != user_id:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    # 优先 Redis cache:graph user绑定键（miss回读旧键）5m，未命中则由 agent_run_log 聚合重建并回写（双写）
    try:
        cached = _cache_get_graph_user(trace_id, user_id)
        if cached and isinstance(cached, dict) and "nodes" in cached:
            return {"code": 200, "msg": "ok", "data": cached}
    except Exception:
        logger.warning("cache_get_graph failed: trace_id=%s", trace_id, exc_info=True)
    logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at, AgentRunLog.id)).all()
    if not logs:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    graph_data = _build_graph_from_logs(list(logs), trace_id)
    try:
        _cache_set_graph_user(trace_id, graph_data, user_id)
    except Exception:
        logger.warning("cache_set_graph failed: trace_id=%s", trace_id, exc_info=True)
    return {"code": 200, "msg": "ok", "data": graph_data}


@router.get("/plans/{trace_id}/inspector")
def get_inspector(trace_id: str, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    resolved = _resolve_trace_user(session, trace_id)
    if resolved is not None and resolved != user_id:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at, AgentRunLog.id)).all()
    if not logs:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "日志不存在"})
    data = _build_inspector_from_logs(list(logs), trace_id, session)
    return {"code": 200, "msg": "ok", "data": data}


@router.get("/plans/{trace_id}/events")
def get_plan_events(trace_id: str, after_seq: int = Query(default=0, ge=0), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """Wave B增量续播：seq为events下标，返回events[after_seq:]（含next_seq/total供续播）。"""
    _enforce_trace_owner(trace_id, user_id, session)
    events = _load_events_for_trace(trace_id, session, user_id)
    if not events:
        # 无归属可判且无事件：debug/pytest外直接404，与stream一致防枚举
        try:
            logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id)).all()
            if not logs:
                raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
        except HTTPException:
            raise
        except Exception:
            pass
        if not events:
            raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    try:
        total = len(events)
    except Exception:
        total = 0
    try:
        idx = int(after_seq or 0)
        if idx < 0:
            idx = 0
    except Exception:
        idx = 0
    try:
        sliced = list(events[idx:]) if idx < total else []
    except Exception:
        sliced = []
    return {"code": 200, "msg": "ok", "data": {"trace_id": trace_id, "events": sliced, "after_seq": idx, "next_seq": total, "total": total}}


@router.get("/plans/{trace_id}/last")
def get_plan_last(trace_id: str, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """Wave B终态聚合：task_created聚合+done（供thread/resume终态直读）。"""
    _enforce_trace_owner(trace_id, user_id, session)
    events = _load_events_for_trace(trace_id, session, user_id)
    if not events:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    tasks: list[dict] = []
    try:
        for e in events or []:
            if not isinstance(e, dict) or e.get("event") != "task_created":
                continue
            try:
                t = (e.get("data") or {}).get("task")
                if isinstance(t, dict):
                    tasks.append(t)
            except Exception:
                continue
    except Exception:
        pass
    done_data: dict = {}
    try:
        done_ev = next((e for e in reversed(events) if isinstance(e, dict) and e.get("event") == "done"), None)
        if isinstance(done_ev, dict) and isinstance(done_ev.get("data"), dict):
            done_data = dict(done_ev.get("data") or {})
    except Exception:
        done_data = {}
    return {"code": 200, "msg": "ok", "data": {"trace_id": trace_id, "tasks": tasks, "done": done_data, "count": len(tasks)}}
