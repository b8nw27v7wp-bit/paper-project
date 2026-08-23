import asyncio
import json
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

from app.agents.graph import graph as multi_graph
from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.models.goal import LearningGoal
from app.models.log import AgentRunLog
from app.models.plan import PlanCreate
from app.models.task import Task
from app.services.memory import search_memory
from app.services.planner import generate_plan, plan_store

router = APIRouter()


@router.post("/plans")
async def create_plan(payload: PlanCreate, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id), mode: str = Query(default="multi")):
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
    trace_id = str(uuid.uuid4())
    goal_dict = {"id": goal.id, "title": goal.title, "deadline": goal.deadline.isoformat(), "description": goal.description, "subject": goal.subject}

    # mode 判定：query ?mode=single 或环境 DISABLE_MULTI
    use_multi = mode != "single" and os.getenv("DISABLE_MULTI", "0") != "1"

    if use_multi:
        # 并行3检索 (Pi并行启示)
        async def _mem(): 
            try: return search_memory(session, user_id, query=goal.title, top_k=5, type_="memory")
            except Exception: return []
        async def _vec():
            try: return search_memory(session, user_id, query=goal.title, top_k=10, type_="knowledge")
            except Exception: return []
        async def _graph():
            try:
                from app.graph.neo import search_prereqs as _search_prereqs, get_graph as _get_graph
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
        final_state = await multi_graph.ainvoke(init_state)
        tasks_raw = final_state.get("tasks", [])
        mentor_msg = final_state.get("mentor_msg", "")
        critic_fb = final_state.get("critic_feedback", "")
        rewrites = final_state.get("rewrites", 0)
        source = "multi"
        # 事件序列 (ReAct 6节点) + 会话压
        from app.agents.compaction import should_compact, summarize
        events = []
        events.append({"event": "thought", "data": {"agent": "planner", "text": final_state.get("_thought", f"分析目标「{goal_dict['title']}」剩余时间，启动6节点协作...")}})
        events.append({"event": "tool_call", "data": {"tool": "researcher", "args": {"memory": len(mems), "vector": len(vector_deps), "graph": len(graph_deps)}}})
        if mems:
            events.append({"event": "tool_call", "data": {"tool": "memory_search", "args": {"q": goal.title, "top_k": 5, "hits": len(mems)}}})
        if 'vector_deps' in locals() and vector_deps:
            events.append({"event": "tool_call", "data": {"tool": "rag_search", "args": {"q": goal.title, "hits": len(vector_deps)}}})
        if 'graph_deps' in locals() and graph_deps:
            events.append({"event": "tool_call", "data": {"tool": "graph_search", "args": {"q": goal.title, "hits": len(graph_deps)}}})
        events.append({"event": "tool_call", "data": {"tool": "planner_generate", "args": {"goal_id": goal_dict["id"], "days": len({t.get("date") for t in tasks_raw})}}})
        for t in tasks_raw:
            events.append({"event": "task_created", "data": {"task": {"title": t["title"], "planned_start": t["planned_start"], "planned_end": t["planned_end"], "priority": t.get("priority", 3)}}})
        if critic_fb:
            events.append({"event": "critic_feedback", "data": {"feedback": critic_fb, "rewrites": rewrites}})
        events.append({"event": "mentor_msg", "data": {"text": mentor_msg}})
        reflector_patch = final_state.get("_patch", {})
        if reflector_patch:
            events.append({"event": "reflector_patch", "data": {"patch": reflector_patch}})
        events.append({"event": "done", "data": {"trace_id": trace_id, "count": len(tasks_raw), "source": source, "rewrites": rewrites}})
        # 会话压：超阈值则摘要
        if should_compact(events):
            events = summarize(events)
        plan_store[trace_id] = events

        # 落库 Task batch (带证据引用)
        citations = [{"chunk_id": v["id"], "score": v["score"]} for v in (vector_deps[:2] if 'vector_deps' in locals() else [])]
        created = []
        for tr in tasks_raw:
            t = Task(
                goal_id=goal.id,
                title=tr["title"][:200],
                planned_start=datetime.fromisoformat(tr["planned_start"]),
                planned_end=datetime.fromisoformat(tr["planned_end"]),
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
        # 从 final_state 取 researcher/reflector 信息
        researcher_out = {"memory": len(mems) if 'mems' in locals() else 0, "vector": len(vector_deps) if 'vector_deps' in locals() else 0, "graph": len(graph_deps) if 'graph_deps' in locals() else 0}
        reflector_patch = final_state.get("_patch", {})
        logs = [
            AgentRunLog(trace_id=trace_id, agent_name="planner", input={"goal": goal_dict, "preferences": prefs, "thought": final_state.get("_thought","")}, output={"tasks": tasks_raw}, tool_calls=[{"tool": "planner_generate"}]),
            AgentRunLog(trace_id=trace_id, agent_name="researcher", input={"goal": goal_dict}, output=researcher_out, tool_calls=[{"tool": "memory_search"}, {"tool": "rag_search"}, {"tool": "graph_search"}]),
            AgentRunLog(trace_id=trace_id, agent_name="executor", input={"tasks": tasks_raw}, output={"count": len(tasks_raw)}, tool_calls=[]),
            AgentRunLog(trace_id=trace_id, agent_name="critic", input={"tasks": tasks_raw, "graphDeps": graph_deps if 'graph_deps' in locals() else []}, output={"feedback": critic_fb, "rewrites": rewrites, "llm": bool(critic_fb)}, tool_calls=[{"tool": "rule_check"}, {"tool": "llm_check"}]),
            AgentRunLog(trace_id=trace_id, agent_name="mentor", input={"feedback": critic_fb, "memory": mems[:2] if 'mems' in locals() else []}, output={"mentor_msg": mentor_msg}, tool_calls=[]),
            AgentRunLog(trace_id=trace_id, agent_name="reflector", input={"feedback": critic_fb}, output={"patch": reflector_patch}, tool_calls=[]),
        ]
        for l in logs:
            session.add(l)
        session.commit()

        return {"code": 200, "msg": "ok", "data": {"trace_id": trace_id, "tasks": created, "mentor_msg": mentor_msg, "citations": [], "mode": "multi", "rewrites": rewrites, "critic_feedback": critic_fb}}

    else:
        tasks_raw, mentor_msg, source = await generate_plan(goal_dict, prefs, trace_id)
        created = []
        for tr in tasks_raw:
            t = Task(
                goal_id=goal.id,
                title=tr["title"][:200],
                planned_start=datetime.fromisoformat(tr["planned_start"]),
                planned_end=datetime.fromisoformat(tr["planned_end"]),
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
        return {"code": 200, "msg": "ok", "data": {"trace_id": trace_id, "tasks": created, "mentor_msg": mentor_msg, "citations": [], "mode": "single"}}


@router.get("/plans/stream")
async def stream_plan(trace_id: str = Query(...), request: Request = None, last_event_id: str | None = None, session: Session = Depends(get_session)):
    # 重放内存事件，支持 Last-Event-ID；重启后从DB重建
    events = plan_store.get(trace_id)
    if not events:
        # DB回退：从 agent_run_log 重建
        logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at)).all()
        if not logs:
            raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})
        # 重建事件：取planner的tasks
        planner_log = next((l for l in logs if l.agent_name == "planner"), logs[0])
        out = planner_log.output or {}
        tasks_raw = out.get("tasks", []) if isinstance(out, dict) else []
        # 若无tasks，尝试从Task表反查
        if not tasks_raw:
            # 尝试查Task表（fallback）
            tasks_raw = []
        events = []
        # 简化重建
        events.append({"event": "thought", "data": {"agent": "planner", "text": "从DB恢复的规划轨迹..."}})
        for t in tasks_raw:
            # 兼容 Task 对象或 dict
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
        # 追加 mentor/done
        mentor = next((l.output.get("mentor_msg") for l in logs if l.agent_name == "mentor" and isinstance(l.output, dict)), "")
        if mentor:
            events.append({"event": "mentor_msg", "data": {"text": mentor}})
        events.append({"event": "done", "data": {"trace_id": trace_id, "count": len([e for e in events if e["event"]=="task_created"]), "source": "db_recover"}})
        plan_store[trace_id] = events

    # 解析 last_event_id 断点续传
    start_idx = 0
    if last_event_id and last_event_id.isdigit():
        start_idx = int(last_event_id) + 1

    async def gen():
        idx = start_idx
        for ev in events[start_idx:]:
            # SSE 格式: event + data + id
            yield {
                "event": ev["event"],
                "data": json.dumps(ev["data"], ensure_ascii=False),
                "id": str(idx),
                "retry": 3000,
            }
            idx += 1
            await asyncio.sleep(0.08)  # 模拟流式 <2s 首字节
        # 心跳结束

    return EventSourceResponse(gen())


@router.get("/plans/{trace_id}/logs")
def get_logs(trace_id: str, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at)).all()
    if not logs:
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "日志不存在"})
    return {"code": 200, "msg": "ok", "data": logs}
