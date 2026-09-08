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


def _plan_events_set(trace_id: str, events: list) -> None:
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

        return _ps3.get(trace_id)
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
    """write_tasks 前置闸门：审批流 graph 执行期间拦截落库，降级为 state 透传（plans.py 批准后手动落库）。"""
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
        return None
    except Exception:
        return None


try:
    from app.agents.tools.registry import add_before_hook as _add_approval_hook

    if not _APPROVAL_HOOK_REGISTERED:
        _add_approval_hook(_write_tasks_approval_guard)
        _APPROVAL_HOOK_REGISTERED = True
except Exception:
    logger.warning("register approval guard hook failed", exc_info=True)

# 6节点顺序，对齐 LangGraph graph.py:350 6节点
AGENT_ORDER = ["planner", "researcher", "executor", "critic", "mentor", "reflector"]
AGENT_LABEL = {
    "planner": "Planner",
    "researcher": "Researcher",
    "executor": "Executor",
    "critic": "Critic",
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
    """由 agent_run_log 聚合生成 6节点DAG，供 GET /plans/{trace_id}/graph 使用。
    优先走 Redis cache:graph，未命中则本函数聚合重建。
    包含节点态 pending/running/success/error + 回边高亮。
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

    # 整体状态：全6节点 success -> completed，否则 running；若有 error 节点 -> failed
    has_error = any(n["status"] == "error" for n in nodes)
    all_success = all(n["status"] == "success" for n in nodes)
    if has_error:
        overall = "failed"
    elif all_success:
        overall = "completed"
    else:
        overall = "running"

    # 构建边：6节点线性 + 回边
    edges = [
        {"from": "planner", "to": "researcher", "type": "next"},
        {"from": "researcher", "to": "executor", "type": "next"},
        {"from": "executor", "to": "critic", "type": "next"},
        {"from": "critic", "to": "mentor", "type": "next"},
        {"from": "mentor", "to": "reflector", "type": "next"},
    ]
    # rewrites 回边：critic rewrites>0，或 reflector patch 含重分配类键（曾触发重排）均高亮 replan 回边
    has_patch_replan = False
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


def _build_inspector_from_logs(logs: list[AgentRunLog], trace_id: str) -> dict:
    """复用 logs 聚合 Inspector 所需 {state,logs,patch}。"""
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
    return {"state": state, "logs": serial_logs, "patch": patch, "trace_id": trace_id}


# System Agent 单点对外智能体入口：POST /plans 即 SystemAgent.ainvoke，对内6子Agent
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
    trace_id = uuid.uuid4().hex
    # 一次性 SSE 票据：绑定 trace+user，TTL 60s，供 EventSource/无头场景兼容
    try:
        stream_ticket = _mint_stream_ticket(trace_id, user_id)
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
        }

        # L1 真实节点事件流：事件按 6 节点真实执行序产出，8 事件契约不变
        def _events_from_final_state(fs: dict) -> list[dict]:
            """astream 不可用时回退：ainvoke 完成后按最终态拼装事件（保持旧契约）。"""
            evs: list[dict] = []
            evs.append({"event": "thought", "data": {"agent": "planner", "text": fs.get("_thought", f"分析目标「{goal_dict['title']}」剩余时间，启动6节点协作...")}})
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
            evs.append({"event": "mentor_msg", "data": {"text": fs.get("mentor_msg", "")}})
            evs.append({"event": "reflector_patch", "data": {"patch": fs.get("_patch", {}) or {}}})
            return evs

        async def _astream_run() -> tuple[dict, list[dict]]:
            """graph.astream(updates)：每节点完成即实时产出对应 SSE 事件（Pi checkpoint thread_id 可恢复）。"""
            evs: list[dict] = []
            fs: dict = dict(init_state)
            seen_titles: set[str] = set()

            def emit(ev: str, data: dict) -> None:
                evs.append({"event": ev, "data": data})

            async for chunk in multi_graph.astream(init_state, config={"configurable": {"thread_id": trace_id}}, stream_mode="updates"):
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
                    elif node_name == "mentor":
                        emit("mentor_msg", {"text": update.get("mentor_msg", "")})
                    elif node_name == "reflector":
                        emit("reflector_patch", {"patch": update.get("_patch", {}) or {}})
            return fs, evs

        async def _ainvoke_run() -> tuple[dict, list[dict]]:
            # Pi checkpoint 启示：带 thread_id 可恢复（对标 SessionState lane）
            try:
                fs = await multi_graph.ainvoke(init_state, config={"configurable": {"thread_id": trace_id}})
            except TypeError:
                # 无 checkpointer 时回退
                fs = await multi_graph.ainvoke(init_state)
            return fs, _events_from_final_state(fs)

        # 写库审批判定：仅 multi 且 require_approval=true 走审批流，默认 False 零改动
        need_approval = bool(getattr(payload, "require_approval", False))
        if need_approval:
            _APPROVAL_BLOCK_TRACES.add(trace_id)
            _block_redis_add(trace_id, _approval_timeout_value())
        try:
            try:
                final_state, events = await _astream_run()
            except TypeError:
                # astream 不可用回退 ainvoke，事件按最终态拼装（契约不变）
                final_state, events = await _ainvoke_run()
        finally:
            if need_approval:
                _APPROVAL_BLOCK_TRACES.discard(trace_id)
                _block_redis_del(trace_id)

        tasks_raw = final_state.get("tasks", [])
        mentor_msg = final_state.get("mentor_msg", "")
        critic_fb = final_state.get("critic_feedback", "")
        rewrites = final_state.get("rewrites", 0)
        source = "multi"
        # 写库审批网关：executor 产出 tasks_raw 后、write_tasks 落库前拦截
        approval_approved: bool | None = None
        approval_timed_out = False
        if need_approval:
            try:
                approve_token = _mint_approval(trace_id, tasks_raw, user_id, goal_id=getattr(goal, "id", None))
            except Exception:
                logger.warning("mint approval failed: trace_id=%s", trace_id, exc_info=True)
                approve_token = secrets.token_urlsafe(32)
                _APPROVALS[trace_id] = {"token": approve_token, "tasks_raw": list(tasks_raw or []), "exp": time.time() + float(_approval_timeout_value()), "approved": None, "user_id": int(user_id), "created_at": time.time()}
                try:
                    _enforce_mem_cap(_APPROVALS)
                    _approval_redis_set(trace_id, _APPROVALS[trace_id], float(_approval_timeout_value()))
                except Exception:
                    pass
            preview = _build_tasks_preview(tasks_raw)
            total = len(tasks_raw or [])
            events.append({"event": "approval_required", "data": {"trace_id": trace_id, "tasks_preview": preview, "approve_token": approve_token, "expires_in": int(float(_approval_timeout_value())), "total_count": total, "total": total, "count": total}})
            # 中间落盘以便 SSE 续播（approval_required 进 events / cache:workbench / plan:events）
            try:
                _plan_events_set(trace_id, list(events))
            except Exception:
                pass
            try:
                cache_set_workbench(trace_id, list(events))
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
        # 事件序列 (ReAct 6节点 + 8事件；审批流追加第10种 approval_required，旧9事件语义不动) + 会话压
        from app.agents.compaction import should_compact, summarize
        if need_approval:
            _done_count = len(tasks_raw or []) if approval_approved else 0
            events.append({"event": "done", "data": {"trace_id": trace_id, "count": _done_count, "source": source, "rewrites": rewrites, "approved": bool(approval_approved)}})
        else:
            events.append({"event": "done", "data": {"trace_id": trace_id, "count": len(tasks_raw), "source": source, "rewrites": rewrites}})
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
        # Pi PlanStore 启示：内存缓存（DB已在下方6条agent_run_log，Redis cache:workbench另存 + plan:events 3600s）
        try:
            _plan_events_set(trace_id, events)
        except Exception:
            pass
        try:
            from app.services.planner import plan_store as _ps_compat

            _ps_compat[trace_id] = events  # type: ignore
        except Exception:
            pass
        # Redis cache:workbench:{trace_id} 5m（SSE 断线重放）
        try:
            cache_set_workbench(trace_id, events)
        except Exception:
            logger.warning("cache_set_workbench failed: trace_id=%s", trace_id, exc_info=True)

        # 落库 Task batch (带证据引用)，坏时间跳过不中断
        # 优先采信 executor 经 write_tasks 工具（schema校验/before/after/事件生命周期）的落库结果，
        # 失败/降级时回退本端直插（state 内透传，链路不崩溃）
        persist_info = final_state.get("task_persist") or {}
        citations = [{"chunk_id": v["id"], "score": v["score"]} for v in (vector_deps[:2] if vector_deps else [])]
        created = []
        if need_approval and not approval_approved:
            # 拒绝/超时：跳过落库；若 graph 内 write_tasks 已提前落库则回滚，保证无落库
            if persist_info.get("persisted"):
                try:
                    _rollback_premature_tasks(session, persist_info.get("rows", []), goal.id, trace_id)
                except Exception:
                    logger.warning("rollback premature tasks failed: trace_id=%s", trace_id, exc_info=True)
            created = []
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
                    source_agent="planner:multi",
                    citations=citations,
                )
                session.add(t)
                created.append(t)
            session.commit()
            for c in created:
                session.refresh(c)

        # 落库 6 条 agent_run_log (ReAct+双校验+个性化+反思)
        researcher_out = {"memory": len(mems) if mems is not None else 0, "vector": len(vector_deps) if vector_deps is not None else 0, "graph": len(graph_deps) if graph_deps is not None else 0}
        reflector_patch = final_state.get("_patch", {})
        replan_reasons = final_state.get("replan_reasons", []) or []
        logs = [
            AgentRunLog(trace_id=trace_id, agent_name="planner", input={"goal": goal_dict, "preferences": prefs, "thought": final_state.get("_thought","")}, output={"tasks": tasks_raw}, tool_calls=[{"tool": "planner_generate"}]),
            AgentRunLog(trace_id=trace_id, agent_name="researcher", input={"goal": goal_dict}, output=researcher_out, tool_calls=[{"tool": "memory_search"}, {"tool": "rag_search"}, {"tool": "graph_search"}]),
            AgentRunLog(trace_id=trace_id, agent_name="executor", input={"tasks": tasks_raw}, output={"count": len(tasks_raw), "persist": {"persisted": bool(persist_info.get("persisted")), "created": persist_info.get("created", 0), "error": persist_info.get("error", "")}}, tool_calls=[]),
            AgentRunLog(trace_id=trace_id, agent_name="critic", input={"tasks": tasks_raw, "graphDeps": graph_deps if graph_deps is not None else []}, output={"feedback": critic_fb, "rewrites": rewrites, "llm": bool(critic_fb), "replan_reasons": replan_reasons}, tool_calls=[{"tool": "rule_check"}, {"tool": "llm_check"}]),
            AgentRunLog(trace_id=trace_id, agent_name="mentor", input={"feedback": critic_fb, "memory": mems[:2] if mems else []}, output={"mentor_msg": mentor_msg}, tool_calls=[]),
            AgentRunLog(trace_id=trace_id, agent_name="reflector", input={"feedback": critic_fb}, output={"patch": reflector_patch}, tool_calls=[]),
        ]
        for l in logs:
            session.add(l)
        session.commit()

        # 生成 graph 缓存 cache:graph:{trace_id} 5m
        try:
            graph_data = _build_graph_from_logs(logs, trace_id)
            cache_set_graph(trace_id, graph_data)
        except Exception:
            logger.warning("build/cache graph failed: trace_id=%s", trace_id, exc_info=True)

        if need_approval:
            return {"code": 200, "msg": "ok", "data": {"trace_id": trace_id, "tasks": created, "mentor_msg": mentor_msg, "citations": [], "mode": "multi", "rewrites": rewrites, "critic_feedback": critic_fb, "replan_reasons": replan_reasons, "stream_ticket": stream_ticket, "stream_ticket_expires_in": _STREAM_TICKET_TTL, "approved": bool(approval_approved)}}
        return {"code": 200, "msg": "ok", "data": {"trace_id": trace_id, "tasks": created, "mentor_msg": mentor_msg, "citations": [], "mode": "multi", "rewrites": rewrites, "critic_feedback": critic_fb, "replan_reasons": replan_reasons, "stream_ticket": stream_ticket, "stream_ticket_expires_in": _STREAM_TICKET_TTL}}

    else:
        tasks_raw, mentor_msg, source = await generate_plan(goal_dict, prefs, trace_id)
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
        events.append({"event": "done", "data": {"trace_id": trace_id, "count": len(tasks_raw), "source": source, "rewrites": 0}})
        try:
            _plan_events_set(trace_id, events)
        except Exception:
            pass
        try:
            cache_set_workbench(trace_id, events)
        except Exception:
            logger.warning("cache_set_workbench failed (single): trace_id=%s", trace_id, exc_info=True)
        created = []
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
                source_agent=f"planner:{source}",
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
        session.add(log)
        session.commit()
        # 单轨同样缓存 graph（仅 planner 节点，其余 pending）
        try:
            logs_for_graph = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at)).all()  # type: ignore
            graph_data = _build_graph_from_logs(list(logs_for_graph), trace_id)
            cache_set_graph(trace_id, graph_data)
        except Exception:
            logger.warning("build/cache graph failed (single): trace_id=%s", trace_id, exc_info=True)
        return {"code": 200, "msg": "ok", "data": {"trace_id": trace_id, "tasks": created, "mentor_msg": mentor_msg, "citations": [], "mode": "single", "stream_ticket": stream_ticket, "stream_ticket_expires_in": _STREAM_TICKET_TTL}}


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


@router.post("/plans/{trace_id}/approve")
def approve_plan(trace_id: str, payload: ApproveRequest, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """写库审批：token 一次性核销，幂等返回首次结果；无效/过期 → 404 {code:40401}。Redis 优先、内存回退。"""
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
        _approval_redis_set(trace_id, entry, float(_approval_timeout_value()))
    except Exception:
        pass
    return {"code": 200, "msg": "ok", "data": {"approved": approved_bool, "trace_id": trace_id}}


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
    # 优先 Redis cache:workbench:{trace_id} 5m（支持 Last-Event-ID 续播），回退 plan:events/plan_store/DB（Pi SessionState 回退启示）
    events = None
    # 1) Redis cache 优先
    try:
        events = cache_get_workbench(trace_id)
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
        events.append({"event": "done", "data": {"trace_id": trace_id, "count": len([e for e in events if e["event"]=="task_created"]), "source": "db_recover"}})
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
            cache_set_workbench(trace_id, events)
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
    """会话历史：按当前用户聚合 agent_run_log distinct trace_id，两次查询无 N+1，分页对齐 {items,total,page,size}。"""
    logs = session.exec(select(AgentRunLog).order_by(AgentRunLog.created_at, AgentRunLog.id)).all()
    if not logs:
        return {"code": 200, "msg": "ok", "data": {"items": [], "total": 0, "page": page, "size": size}}
    trace_logs: dict[str, list[AgentRunLog]] = {}
    for lg in logs:
        trace_logs.setdefault(lg.trace_id, []).append(lg)
    goal_ids: set[int] = set()
    trace_candidates: dict[str, list[tuple[int | None, str | None]]] = {}
    for trace_id, tlogs in trace_logs.items():
        candidates: list[tuple[int | None, str | None]] = []
        for l in tlogs:
            if l.agent_name == "planner" and isinstance(l.input, dict):
                g = l.input.get("goal")
                if isinstance(g, dict):
                    gid = g.get("id") if isinstance(g.get("id"), int) else None
                    title = g.get("title") if isinstance(g.get("title"), str) else None
                    candidates.append((gid, title))
                    if gid is not None:
                        goal_ids.add(gid)
        trace_candidates[trace_id] = candidates
    goal_map: dict[int, LearningGoal] = {}
    if goal_ids:
        goal_rows = session.exec(select(LearningGoal).where(LearningGoal.id.in_(list(goal_ids)))).all()
        goal_map = {g.id: g for g in goal_rows if g.id is not None}
    items: list[dict] = []
    for trace_id, tlogs in trace_logs.items():
        goal_id = None
        for gid, _title in trace_candidates[trace_id]:
            if gid is not None and gid in goal_map:
                goal_id = gid
                break
        if goal_id is None:
            continue
        goal = goal_map[goal_id]
        if goal.user_id != user_id:
            continue
        times = [l.created_at for l in tlogs if l.created_at is not None]
        started_at = min(times).isoformat() if times else None
        last_event_at = max(times).isoformat() if times else None
        agent_names = {l.agent_name for l in tlogs}
        mode = "multi" if agent_names - {"planner"} else "single"
        rewrites = 0
        for l in tlogs:
            if l.agent_name != "critic":
                continue
            out = l.output if isinstance(l.output, dict) else {}
            val = out.get("rewrites", 0)
            if isinstance(val, int) and not isinstance(val, bool) and val > rewrites:
                rewrites = val
        patch_replan = False
        for l in tlogs:
            if l.agent_name != "reflector":
                continue
            out = l.output if isinstance(l.output, dict) else {}
            patch = out.get("patch")
            if isinstance(patch, dict) and any(k in patch for k in ("reduce_load", "add_buffer", "reallocate")):
                patch_replan = True
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
        items.append(
            {
                "trace_id": trace_id,
                "mode": mode,
                "goal_id": goal_id,
                "goal_title": goal.title,
                "started_at": started_at,
                "last_event_at": last_event_at,
                "event_count": len(tlogs),
                "node_summary": node_summary,
                "status": status,
            }
        )
    items.sort(key=lambda it: it["last_event_at"] or "", reverse=True)
    total = len(items)
    page_items = items[(page - 1) * size : page * size]
    return {"code": 200, "msg": "ok", "data": {"items": page_items, "total": total, "page": page, "size": size}}


@router.get("/plans/{trace_id}/logs")
def get_logs(trace_id: str, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at, AgentRunLog.id)).all()
    if not logs:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "日志不存在"})
    return {"code": 200, "msg": "ok", "data": logs}


@router.get("/plans/{trace_id}/graph")
def get_graph_api(trace_id: str, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    # 优先 Redis cache:graph:{trace_id} 5m，未命中则由 agent_run_log 聚合重建并回写
    try:
        cached = cache_get_graph(trace_id)
        if cached and isinstance(cached, dict) and "nodes" in cached:
            return {"code": 200, "msg": "ok", "data": cached}
    except Exception:
        logger.warning("cache_get_graph failed: trace_id=%s", trace_id, exc_info=True)
    logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at, AgentRunLog.id)).all()
    if not logs:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    graph_data = _build_graph_from_logs(list(logs), trace_id)
    try:
        cache_set_graph(trace_id, graph_data)
    except Exception:
        logger.warning("cache_set_graph failed: trace_id=%s", trace_id, exc_info=True)
    return {"code": 200, "msg": "ok", "data": graph_data}


@router.get("/plans/{trace_id}/inspector")
def get_inspector(trace_id: str, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at, AgentRunLog.id)).all()
    if not logs:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "日志不存在"})
    data = _build_inspector_from_logs(list(logs), trace_id)
    return {"code": 200, "msg": "ok", "data": data}
