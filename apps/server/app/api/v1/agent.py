from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from app.agents.system_agent import SystemAgent
from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.models.goal import LearningGoal
from app.models.plan import PlanCreate

router = APIRouter()


@router.get("/agent/manifest", tags=["agent"], summary="System Agent manifest")
def get_manifest():
    """System Agent 单点对外智能体清单，供 hermes/pi 发现（公开但脱敏：tools 仅暴露 name/label）。"""
    m = SystemAgent.get_manifest()
    try:
        tools = m.get("tools", []) if isinstance(m, dict) else []
        safe_tools = [{"name": t.get("name"), "label": t.get("label")} for t in tools if isinstance(t, dict)]
        data = dict(m) if isinstance(m, dict) else {}
        data["tools"] = safe_tools
        return {"code": 200, "msg": "ok", "data": data}
    except Exception:
        return {"code": 200, "msg": "ok", "data": m}


@router.get("/agent/health", tags=["agent"], summary="System Agent health")
def agent_health(user_id: int = Depends(get_current_user_id)):
    m = SystemAgent.get_manifest()
    return {"code": 200, "msg": "ok", "data": {"name": m["name"], "version": m["version"], "status": "ok", "sub_agents": m["sub_agents"]}}


@router.get("/agent/tools", tags=["agent"], summary="Agent tools manifest")
def list_agent_tools(user_id: int = Depends(get_current_user_id)):
    """返回 list_tools_detailed()，供前端 Manifest 弹窗展示工具清单."""
    try:
        from app.agents.tools.registry import list_tools_detailed

        tools = list_tools_detailed()
        # 确保 schema 可 JSON 序列化（ToolSchema dataclass -> dict）
        serial = []
        for t in tools:
            schema = t.get("schema")
            if schema is not None and not isinstance(schema, dict):
                try:
                    # ToolSchema dataclass
                    schema = {"type": getattr(schema, "type", "object"), "properties": getattr(schema, "properties", {}), "required": getattr(schema, "required", [])}
                except Exception:
                    schema = str(schema)
            serial.append({"name": t.get("name"), "label": t.get("label"), "description": t.get("description"), "schema": schema})
        return {"code": 200, "msg": "ok", "data": serial}
    except Exception:
        # 回退走 SystemAgent 包装
        return {"code": 200, "msg": "ok", "data": SystemAgent.get_tools_manifest()}


@router.post("/agent/plan", tags=["agent"], summary="SystemAgent plan proxy")
async def agent_plan(payload: PlanCreate, request: Request, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """代理到 SystemAgent.ainvoke，复用 plans 逻辑但返回 SystemAgent 包装.

    参数 goal_id, preferences，需鉴权 get_current_user_id.
    内部即 SystemAgent.ainvoke(goal,prefs) -> 6子Agent协作，trace_id 贯穿。
    """
    # 复用 plans 的限流与校验（429 需透传，不吞）
    from app.core.ratelimit import check_rate_limit

    try:
        check_rate_limit(request, user_id)
    except HTTPException:
        raise
    except Exception:
        pass
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
    goal_dict = {"id": goal.id, "title": goal.title, "deadline": goal.deadline.isoformat(), "description": goal.description, "subject": goal.subject}
    import uuid

    trace_id = uuid.uuid4().hex
    # 单点 ainvoke：内部走 LangGraph 6节点（带 researcher 3检索）
    final = await SystemAgent.ainvoke(goal_dict, prefs, trace_id=trace_id, session=session, user_id=user_id)
    # 提取结果
    tasks_raw = final.get("tasks", []) if isinstance(final, dict) else []
    mentor_msg = final.get("mentor_msg", "") if isinstance(final, dict) else ""
    critic_feedback = final.get("critic_feedback", "") if isinstance(final, dict) else ""
    rewrites = final.get("rewrites", 0) if isinstance(final, dict) else 0
    patch = final.get("_patch", {}) if isinstance(final, dict) else {}
    if not isinstance(patch, dict):
        patch = {}
    # 写入 reflection_report.next_plan_patch（复用 SystemAgent.plan_project 的语义，此处同步保证）
    try:
        if isinstance(patch, dict) and patch:
            from datetime import datetime, timezone

            from app.models.reflection import ReflectionReport

            now = datetime.now(timezone.utc)
            try:
                from app.scheduler.reflector import _week_str

                week = _week_str(now)
            except Exception:
                iso = now.isocalendar()
                week = f"{iso[0]}-W{iso[1]:02d}"
            existing = session.exec(select(ReflectionReport).where(ReflectionReport.user_id == user_id, ReflectionReport.week == week)).first()
            if existing is not None:
                existing.next_plan_patch = patch
                session.add(existing)
                session.commit()
                try:
                    session.refresh(existing)
                except Exception:
                    pass
            else:
                report = ReflectionReport(
                    user_id=user_id,
                    week=week,
                    completion_rate=0,
                    delay_rate=0,
                    avg_load=0,
                    analysis=f"agent/plan auto patch trace={trace_id}",
                    next_plan_patch=patch,
                )
                session.add(report)
                session.commit()
                try:
                    session.refresh(report)
                except Exception:
                    pass
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
    # 落库 Task batch（复用 plans 逻辑，带 citations）
    vector_deps = final.get("vectorDeps", []) if isinstance(final, dict) else []
    citations: list[dict] = []
    try:
        if isinstance(vector_deps, list) and vector_deps:
            citations = [{"chunk_id": v.get("id"), "score": v.get("score")} for v in vector_deps[:2] if isinstance(v, dict)]
    except Exception:
        citations = []
    from datetime import datetime as _dt

    from app.models.task import Task

    created: list[Task] = []
    try:
        for tr in tasks_raw:
            if not isinstance(tr, dict):
                continue
            try:
                t = Task(
                    goal_id=goal.id,
                    title=str(tr.get("title", "任务"))[:200],
                    planned_start=_dt.fromisoformat(tr["planned_start"]),
                    planned_end=_dt.fromisoformat(tr["planned_end"]),
                    priority=int(tr.get("priority", 3)),
                    status="todo",
                    source_agent="system_agent:plan",
                    citations=citations,
                )
                session.add(t)
                created.append(t)
            except Exception:
                continue
        session.commit()
        for c in created:
            try:
                session.refresh(c)
            except Exception:
                pass
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        created = []
    # 落库 6 条 agent_run_log（简化复用 plans，支撑 graph/inspector 可追溯）
    try:
        from app.models.log import AgentRunLog

        researcher_out = {}
        try:
            mems = final.get("memory", []) if isinstance(final, dict) else []
            vecs = vector_deps if isinstance(vector_deps, list) else []
            graph_deps = final.get("graphDeps", []) if isinstance(final, dict) else []
            researcher_out = {"memory": len(mems) if isinstance(mems, list) else 0, "vector": len(vecs) if isinstance(vecs, list) else 0, "graph": len(graph_deps) if isinstance(graph_deps, list) else 0}
        except Exception:
            researcher_out = {}
        logs = [
            AgentRunLog(trace_id=trace_id, agent_name="planner", input={"goal": goal_dict, "preferences": prefs, "thought": final.get("_thought", "") if isinstance(final, dict) else ""}, output={"tasks": tasks_raw}, tool_calls=[{"tool": "planner_generate"}]),
            AgentRunLog(trace_id=trace_id, agent_name="researcher", input={"goal": goal_dict}, output=researcher_out, tool_calls=[{"tool": "memory_search"}, {"tool": "rag_search"}, {"tool": "graph_search"}]),
            AgentRunLog(trace_id=trace_id, agent_name="executor", input={"tasks": tasks_raw}, output={"count": len(tasks_raw)}, tool_calls=[]),
            AgentRunLog(trace_id=trace_id, agent_name="critic", input={"tasks": tasks_raw, "graphDeps": final.get("graphDeps", []) if isinstance(final, dict) else []}, output={"feedback": critic_feedback, "rewrites": rewrites, "llm": bool(critic_feedback)}, tool_calls=[{"tool": "rule_check"}, {"tool": "llm_check"}]),
            AgentRunLog(trace_id=trace_id, agent_name="mentor", input={"feedback": critic_feedback, "memory": (final.get("memory", [])[:2] if isinstance(final.get("memory", []), list) else [])}, output={"mentor_msg": mentor_msg}, tool_calls=[]),
            AgentRunLog(trace_id=trace_id, agent_name="reflector", input={"feedback": critic_feedback}, output={"patch": patch}, tool_calls=[]),
        ]
        for lg in logs:
            session.add(lg)
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
    # plan_store + cache（支撑 SSE/Graph 复用）
    try:
        from app.services.planner import plan_store

        events: list[dict] = []
        events.append({"event": "thought", "data": {"agent": "planner", "text": final.get("_thought", f"SystemAgent 规划「{goal_dict['title']}」") if isinstance(final, dict) else f"SystemAgent 规划「{goal_dict['title']}」"}})
        for t in tasks_raw:
            if isinstance(t, dict):
                events.append({"event": "task_created", "data": {"task": {"title": t.get("title"), "planned_start": t.get("planned_start"), "planned_end": t.get("planned_end"), "priority": t.get("priority", 3)}}})
        events.append({"event": "critic_feedback", "data": {"feedback": critic_feedback, "rewrites": rewrites}})
        events.append({"event": "mentor_msg", "data": {"text": mentor_msg}})
        events.append({"event": "reflector_patch", "data": {"patch": patch}})
        events.append({"event": "done", "data": {"trace_id": trace_id, "count": len(tasks_raw), "source": "system_agent", "rewrites": rewrites}})
        try:
            plan_store[trace_id] = events  # type: ignore
        except Exception:
            plan_store[trace_id] = events  # type: ignore
        try:
            from app.core.cache import set_graph as cache_set_graph
            from app.core.cache import set_workbench as cache_set_workbench

            cache_set_workbench(trace_id, events)
            # 生成 graph 缓存
            from app.api.v1.plans import _build_graph_from_logs

            # 构造临时 logs 供 graph 聚合（复用已落库的 6 条）
            graph_data = _build_graph_from_logs(logs, trace_id)  # type: ignore
            cache_set_graph(trace_id, graph_data)
        except Exception:
            pass
    except Exception:
        pass
    # 返回 SystemAgent 包装（兼容 plans 的 trace_id/tasks，同时暴露 final）
    return {"code": 200, "msg": "ok", "data": {"trace_id": trace_id, "tasks": created, "mentor_msg": mentor_msg, "critic_feedback": critic_feedback, "rewrites": rewrites, "patch": patch, "mode": "system_agent", "final": final}}
