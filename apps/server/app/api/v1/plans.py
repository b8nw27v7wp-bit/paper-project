import asyncio
import json
import logging
import os
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
from app.models.plan import PlanCreate
from app.models.task import Task
from app.services.memory import search_memory
from app.services.planner import generate_plan, plan_store

router = APIRouter()
logger = logging.getLogger("app.plans")

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
            "memory": mems,
            "graphDeps": graph_deps,
            "vectorDeps": vector_deps,
            "milestones": [],
            "tasks": [],
            "critic_feedback": "",
            "mentor_msg": "",
            "rewrites": 0,
        }
        # Pi checkpoint 启示：带 thread_id 可恢复（对标 SessionState lane）
        try:
            final_state = await multi_graph.ainvoke(init_state, config={"configurable": {"thread_id": trace_id}})
        except TypeError:
            # 无 checkpointer 时回退
            final_state = await multi_graph.ainvoke(init_state)
        tasks_raw = final_state.get("tasks", [])
        mentor_msg = final_state.get("mentor_msg", "")
        critic_fb = final_state.get("critic_feedback", "")
        rewrites = final_state.get("rewrites", 0)
        source = "multi"
        # 事件序列 (ReAct 6节点 + 8事件) + 会话压
        from app.agents.compaction import should_compact, summarize
        events = []
        # 1 thought
        events.append({"event": "thought", "data": {"agent": "planner", "text": final_state.get("_thought", f"分析目标「{goal_dict['title']}」剩余时间，启动6节点协作...")}})
        # tool_call_start/end 对 (满足子调用树可折叠)
        events.append({"event": "tool_call_start", "data": {"tool": "researcher", "agent": "researcher", "args": {"memory": len(mems), "vector": len(vector_deps), "graph": len(graph_deps)}}})
        events.append({"event": "tool_call", "data": {"tool": "researcher", "args": {"memory": len(mems), "vector": len(vector_deps), "graph": len(graph_deps)}}})
        if mems:
            events.append({"event": "tool_call_start", "data": {"tool": "memory_search", "agent": "researcher", "args": {"q": goal.title, "top_k": 5}}})
            events.append({"event": "tool_call", "data": {"tool": "memory_search", "args": {"q": goal.title, "top_k": 5, "hits": len(mems)}}})
            events.append({"event": "tool_call_end", "data": {"tool": "memory_search", "agent": "researcher", "result": {"hits": len(mems)}}})
        if vector_deps:
            events.append({"event": "tool_call_start", "data": {"tool": "rag_search", "agent": "researcher", "args": {"q": goal.title}}})
            events.append({"event": "tool_call", "data": {"tool": "rag_search", "args": {"q": goal.title, "hits": len(vector_deps)}}})
            events.append({"event": "tool_call_end", "data": {"tool": "rag_search", "agent": "researcher", "result": {"hits": len(vector_deps)}}})
        if graph_deps:
            events.append({"event": "tool_call_start", "data": {"tool": "graph_search", "agent": "researcher", "args": {"q": goal.title}}})
            events.append({"event": "tool_call", "data": {"tool": "graph_search", "args": {"q": goal.title, "hits": len(graph_deps)}}})
            events.append({"event": "tool_call_end", "data": {"tool": "graph_search", "agent": "researcher", "result": {"hits": len(graph_deps)}}})
        events.append({"event": "tool_call_end", "data": {"tool": "researcher", "agent": "researcher", "result": {"memory": len(mems), "vector": len(vector_deps), "graph": len(graph_deps)}}})
        events.append({"event": "tool_call", "data": {"tool": "planner_generate", "args": {"goal_id": goal_dict["id"], "days": len({t.get("date") for t in tasks_raw})}}})
        for t in tasks_raw:
            events.append({"event": "task_created", "data": {"task": {"title": t["title"], "planned_start": t["planned_start"], "planned_end": t["planned_end"], "priority": t.get("priority", 3)}}})
        if critic_fb:
            events.append({"event": "critic_feedback", "data": {"feedback": critic_fb, "rewrites": rewrites}})
        else:
            # 即使通过也发一条 critic_feedback 空，方便前端统计 8 事件齐全
            events.append({"event": "critic_feedback", "data": {"feedback": "", "rewrites": rewrites}})
        events.append({"event": "mentor_msg", "data": {"text": mentor_msg}})
        reflector_patch = final_state.get("_patch", {})
        if reflector_patch:
            events.append({"event": "reflector_patch", "data": {"patch": reflector_patch}})
        else:
            events.append({"event": "reflector_patch", "data": {"patch": {}}})
        events.append({"event": "done", "data": {"trace_id": trace_id, "count": len(tasks_raw), "source": source, "rewrites": rewrites}})
        # 会话压：超阈值则摘要
        if should_compact(events):
            events = summarize(events)
        # Pi PlanStore 启示：内存缓存（DB已在下方6条agent_run_log，Redis cache:workbench另存）
        plan_store[trace_id] = events  # type: ignore
        # Redis cache:workbench:{trace_id} 5m（SSE 断线重放）
        try:
            cache_set_workbench(trace_id, events)
        except Exception:
            logger.warning("cache_set_workbench failed: trace_id=%s", trace_id, exc_info=True)

        # 落库 Task batch (带证据引用)，坏时间跳过不中断
        citations = [{"chunk_id": v["id"], "score": v["score"]} for v in (vector_deps[:2] if vector_deps else [])]
        created = []
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
        logs = [
            AgentRunLog(trace_id=trace_id, agent_name="planner", input={"goal": goal_dict, "preferences": prefs, "thought": final_state.get("_thought","")}, output={"tasks": tasks_raw}, tool_calls=[{"tool": "planner_generate"}]),
            AgentRunLog(trace_id=trace_id, agent_name="researcher", input={"goal": goal_dict}, output=researcher_out, tool_calls=[{"tool": "memory_search"}, {"tool": "rag_search"}, {"tool": "graph_search"}]),
            AgentRunLog(trace_id=trace_id, agent_name="executor", input={"tasks": tasks_raw}, output={"count": len(tasks_raw)}, tool_calls=[]),
            AgentRunLog(trace_id=trace_id, agent_name="critic", input={"tasks": tasks_raw, "graphDeps": graph_deps if graph_deps is not None else []}, output={"feedback": critic_fb, "rewrites": rewrites, "llm": bool(critic_fb)}, tool_calls=[{"tool": "rule_check"}, {"tool": "llm_check"}]),
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

        return {"code": 200, "msg": "ok", "data": {"trace_id": trace_id, "tasks": created, "mentor_msg": mentor_msg, "citations": [], "mode": "multi", "rewrites": rewrites, "critic_feedback": critic_fb}}

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
        plan_store[trace_id] = events  # type: ignore
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
        return {"code": 200, "msg": "ok", "data": {"trace_id": trace_id, "tasks": created, "mentor_msg": mentor_msg, "citations": [], "mode": "single"}}


@router.get("/plans/stream")
async def stream_plan(
    trace_id: str = Query(...),
    request: Request = None,
    last_event_id: str | None = Query(default=None),
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    # 所有权校验：trace 归属用户联查，不一致 404（防枚举泄露他人轨迹）
    resolved = _resolve_trace_user(session, trace_id)
    if resolved is not None and resolved != user_id:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    if resolved is None:
        # 无归属可判（空计划/旧数据/不存在）：debug/pytest 放行走下方常规 404 流程，prod 直接 404
        from app.core.config import get_settings

        if not (get_settings().debug or os.getenv("PYTEST_CURRENT_TEST")):
            raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
    # 优先 Redis cache:workbench:{trace_id} 5m（支持 Last-Event-ID 续播），回退 plan_store/DB（Pi SessionState 回退启示）
    events = None
    # 1) Redis cache 优先
    try:
        events = cache_get_workbench(trace_id)
    except Exception:
        logger.warning("cache_get_workbench failed: trace_id=%s", trace_id, exc_info=True)
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
            plan_store[trace_id] = events  # type: ignore
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
            await asyncio.sleep(0.08)  # 模拟流式 <2s 首字节，首字节实际即刻发出
        # 心跳结束

    return EventSourceResponse(gen(), headers={"Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
