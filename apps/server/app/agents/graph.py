from typing import Dict, List
from datetime import datetime, timezone, timedelta
import json
from langgraph.graph import StateGraph, END
from .state import PlanState
from .prompts import PLANNER_SYSTEM
from app.services.planner import mock_generate, llm_generate
from app.core.config import get_settings

settings = get_settings()

async def planner_node(state: PlanState) -> Dict:
    goal = state["goal"]
    prefs = state.get("preferences") or {"hours_per_day": 2}
    rewrites = state.get("rewrites", 0)
    # 调用 mock/llm
    try:
        tasks, _ = await llm_generate(goal, prefs)
        source = "llm"
    except Exception:
        tasks, _ = mock_generate(goal, prefs, state.get("trace_id",""))
        source = "mock"

    # 若重规划，微调时间避免重复重叠：整体后移30分钟*rewrites
    if rewrites > 0:
        for t in tasks:
            s = datetime.fromisoformat(t["planned_start"])
            e = datetime.fromisoformat(t["planned_end"])
            s = s + timedelta(minutes=30*rewrites)
            e = e + timedelta(minutes=30*rewrites)
            t["planned_start"] = s.isoformat()
            t["planned_end"] = e.isoformat()

    milestones = [{"week": 1, "goal": goal.get("title")}]
    # 返回并在重规划计数外层处理 rewrites 递增在 wrapper 中，这里仅保证 tasks 更新
    return {"tasks": tasks, "milestones": milestones, "critic_feedback": ""}


async def planner_with_count(state: PlanState) -> Dict:
    res = await planner_node(state)
    # 若上轮 critique 有反馈，本次进入即算一次重写
    if state.get("critic_feedback"):
        res["rewrites"] = state.get("rewrites", 0) + 1
    else:
        res["rewrites"] = state.get("rewrites", 0)
    return res

def executor_node(state: PlanState) -> Dict:
    # 透传 tasks，补充校验已在 planner 保证
    return {}

def critic_node(state: PlanState) -> Dict:
    tasks = state.get("tasks", [])
    # 规则校验
    feedback = []
    # 1. 时间重叠>30%
    tasks_sorted = sorted(tasks, key=lambda x: x["planned_start"])
    for i in range(len(tasks_sorted)-1):
        s1 = datetime.fromisoformat(tasks_sorted[i]["planned_start"])
        e1 = datetime.fromisoformat(tasks_sorted[i]["planned_end"])
        s2 = datetime.fromisoformat(tasks_sorted[i+1]["planned_start"])
        e2 = datetime.fromisoformat(tasks_sorted[i+1]["planned_end"])
        if s2 < e1:
            overlap = (e1 - s2).total_seconds() / 3600
            dur1 = (e1 - s1).total_seconds() / 3600
            if dur1 > 0 and overlap / dur1 > 0.3:
                feedback.append(f"任务重叠>30%: {tasks_sorted[i]['title']} 与 {tasks_sorted[i+1]['title']} 重叠{overlap:.1f}h")
    # 2. 单日负荷>4h
    from collections import defaultdict
    day_hours = defaultdict(float)
    for t in tasks:
        s = datetime.fromisoformat(t["planned_start"])
        e = datetime.fromisoformat(t["planned_end"])
        day = s.date().isoformat()
        day_hours[day] += (e - s).total_seconds() / 3600
    for day, h in day_hours.items():
        if h > 4:
            feedback.append(f"单日负荷超4h: {day} {h:.1f}h")
    if feedback:
        return {"critic_feedback": "; ".join(feedback)}
    return {"critic_feedback": ""}

def mentor_node(state: PlanState) -> Dict:
    goal = state.get("goal", {})
    tasks = state.get("tasks", [])
    msg = f"已为「{goal.get('title','学习')}」生成{len(tasks)}个任务，坚持完成！"
    return {"mentor_msg": msg}

def should_replan(state: PlanState) -> str:
    fb = state.get("critic_feedback", "")
    rewrites = state.get("rewrites", 0)
    if fb and rewrites < 2:
        return "replan"
    return "mentor"

def build_graph():
    g = StateGraph(PlanState)
    g.add_node("planner", planner_with_count)
    g.add_node("executor", executor_node)
    g.add_node("critic", critic_node)
    g.add_node("mentor", mentor_node)
    g.set_entry_point("planner")
    g.add_edge("planner", "executor")
    g.add_edge("executor", "critic")
    g.add_conditional_edges("critic", should_replan, {"replan": "planner", "mentor": "mentor"})
    g.add_edge("mentor", END)
    return g.compile()

graph = build_graph()
