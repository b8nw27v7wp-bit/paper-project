import uuid
import json
import asyncio
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.models.goal import LearningGoal
from app.models.task import Task
from app.models.log import AgentRunLog
from app.models.plan import PlanCreate
from app.services.planner import generate_plan, plan_store
from app.agents.graph import graph as multi_graph

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
        # 多Agent协作
        init_state = {
            "goal": goal_dict,
            "preferences": prefs,
            "trace_id": trace_id,
            "memory": [],
            "graphDeps": [],
            "vectorDeps": [],
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
        # 事件序列
        events = []
        events.append({"event": "thought", "data": {"agent": "planner", "text": f"分析目标「{goal_dict['title']}」剩余时间，启动多Agent协作..."}})
        events.append({"event": "tool_call", "data": {"tool": "planner_generate", "args": {"goal_id": goal_dict["id"], "days": len(set(t.get("date") for t in tasks_raw))}}})
        for t in tasks_raw:
            events.append({"event": "task_created", "data": {"task": {"title": t["title"], "planned_start": t["planned_start"], "planned_end": t["planned_end"], "priority": t.get("priority", 3)}}})
        if critic_fb:
            events.append({"event": "critic_feedback", "data": {"feedback": critic_fb, "rewrites": rewrites}})
        events.append({"event": "mentor_msg", "data": {"text": mentor_msg}})
        events.append({"event": "done", "data": {"trace_id": trace_id, "count": len(tasks_raw), "source": source, "rewrites": rewrites}})
        plan_store[trace_id] = events

        # 落库 Task batch
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
                citations=[],
            )
            session.add(t)
            created.append(t)
        session.commit()
        for c in created:
            session.refresh(c)

        # 落库 4 条 agent_run_log
        logs = [
            AgentRunLog(trace_id=trace_id, agent_name="planner", input={"goal": goal_dict, "preferences": prefs}, output={"tasks": tasks_raw}, tool_calls=[{"tool": "planner"}]),
            AgentRunLog(trace_id=trace_id, agent_name="executor", input={"tasks": tasks_raw}, output={"count": len(tasks_raw)}, tool_calls=[]),
            AgentRunLog(trace_id=trace_id, agent_name="critic", input={"tasks": tasks_raw}, output={"feedback": critic_fb, "rewrites": rewrites}, tool_calls=[]),
            AgentRunLog(trace_id=trace_id, agent_name="mentor", input={"feedback": critic_fb}, output={"mentor_msg": mentor_msg}, tool_calls=[]),
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
async def stream_plan(trace_id: str = Query(...), request: Request = None, last_event_id: str = None):
    # 重放内存事件，支持 Last-Event-ID
    events = plan_store.get(trace_id)
    if not events:
        # 尝试从 DB 恢复最近一次
        raise HTTPException(status_code=404, detail={"code": 40401, "msg": "trace不存在"})

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
