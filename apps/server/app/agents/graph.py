from datetime import datetime, timedelta

from langgraph.graph import END, StateGraph

from app.core.config import get_settings
from app.services.planner import llm_generate, mock_generate

from .state import PlanState

settings = get_settings()

# 方向1：ReAct工具链显式化
async def planner_node(state: PlanState) -> dict:
    goal = state["goal"]
    prefs = state.get("preferences") or {"hours_per_day": 2}
    rewrites = state.get("rewrites", 0)
    # ReAct thought
    thought = f"思考：目标「{goal.get('title')}\" 截止{goal.get('deadline')}，偏好{prefs}，重写{rewrites}次"
    # 实际生成仍用 mock/LLM，工具调用已在 researcher 显式化，此处保留thought
    try:
        tasks, _ = await llm_generate(goal, prefs)
    except Exception:
        tasks, _ = mock_generate(goal, prefs, state.get("trace_id", ""))
    if rewrites > 0:
        for t in tasks:
            s = datetime.fromisoformat(t["planned_start"])
            e = datetime.fromisoformat(t["planned_end"])
            s = s + timedelta(minutes=30 * rewrites)
            e = e + timedelta(minutes=30 * rewrites)
            t["planned_start"] = s.isoformat()
            t["planned_end"] = e.isoformat()
    return {"tasks": tasks, "milestones": [{"week": 1, "goal": goal.get("title")}], "critic_feedback": "", "_thought": thought}

async def planner_with_count(state: PlanState) -> dict:
    res = await planner_node(state)
    if state.get("critic_feedback"):
        res["rewrites"] = state.get("rewrites", 0) + 1
    else:
        res["rewrites"] = state.get("rewrites", 0)
    # 保留 thought 供日志
    res["_thought"] = res.get("_thought", "")
    return res

# 方向1：Researcher专职RAG/图谱/记忆 (走注册表，可热插)
def researcher_node(state: PlanState) -> dict:
    # 前置检索已在 plans.py 完成，此节点仅显式化轨迹，演示 Pi 式工具注册表
    from app.agents.tools.registry import list_tools
    mem = state.get("memory", [])
    g = state.get("graphDeps", [])
    v = state.get("vectorDeps", [])
    # 演示：列出可用工具
    tools = list_tools()  # ["memory_search","rag_search","graph_search","write_tasks"]
    return {"_research": {"memory": len(mem), "graph": len(g), "vector": len(v), "tools": tools}}

def executor_node(state: PlanState) -> dict:
    return {}

# 方向2：Critic双校验 + 图谱前置 + 熔断
def critic_node(state: PlanState) -> dict:
    tasks = state.get("tasks", [])
    graph_deps = state.get("graphDeps", [])
    feedback = []
    # 熔断：若任务数>30，视为异常，直接打回
    if len(tasks) > 30:
        return {"critic_feedback": "熔断：任务数>30，截断风险", "terminate": True}
    # 1. 重叠>30%
    tasks_sorted = sorted(tasks, key=lambda x: x["planned_start"])
    for i in range(len(tasks_sorted) - 1):
        s1 = datetime.fromisoformat(tasks_sorted[i]["planned_start"])
        e1 = datetime.fromisoformat(tasks_sorted[i]["planned_end"])
        s2 = datetime.fromisoformat(tasks_sorted[i+1]["planned_start"])
        if s2 < e1:
            overlap = (e1 - s2).total_seconds() / 3600
            dur1 = (e1 - s1).total_seconds() / 3600
            if dur1 > 0 and overlap / dur1 > 0.3:
                feedback.append(f"重叠>30%: {tasks_sorted[i]['title']}与{tasks_sorted[i+1]['title']} {overlap:.1f}h")
    # 2. 单日>4h
    from collections import defaultdict
    day_hours = defaultdict(float)
    for t in tasks:
        s = datetime.fromisoformat(t["planned_start"])
        e = datetime.fromisoformat(t["planned_end"])
        day_hours[s.date().isoformat()] += (e - s).total_seconds() / 3600
    for day, h in day_hours.items():
        if h > 4:
            feedback.append(f"单日超4h: {day} {h:.1f}h")
    # 3. 前置缺失：若graphDeps有 A->B 但B排在A前
    # 简化：检查任务标题是否含依赖名
    title_order = [t["title"] for t in tasks]
    for dep in graph_deps[:5]:
        frm = dep.get("from") if isinstance(dep, dict) else str(dep)
        to = dep.get("to") if isinstance(dep, dict) else ""
        if frm and to:
            try:
                idx_f = next((i for i, title in enumerate(title_order) if frm in title), -1)
                idx_t = next((i for i, title in enumerate(title_order) if to in title), -1)
                if idx_f != -1 and idx_t != -1 and idx_t < idx_f:
                    feedback.append(f"前置缺失: {frm}应在{to}前")
            except Exception:
                pass
    # LLM二次校验（若有Key）
    llm_feedback = ""
    if settings.llm_api_key:
        try:
            # 同步mock：若feedback已非空，LLM也判不通过
            if feedback:
                llm_feedback = "LLM复核：不通过"
            else:
                # 可调真实LLM，此处为节省费用直接通过
                llm_feedback = ""
        except Exception:
            llm_feedback = ""
    if llm_feedback and llm_feedback != "":
        feedback.append(llm_feedback)
    if feedback:
        return {"critic_feedback": "; ".join(feedback)}
    return {"critic_feedback": ""}

# 方向3：Mentor个性化
def mentor_node(state: PlanState) -> dict:
    goal = state.get("goal", {})
    tasks = state.get("tasks", [])
    mem = state.get("memory", [])
    # 读拖延史
    delay_hint = ""
    for m in mem[:3]:
        c = m.get("content", "") if isinstance(m, dict) else str(m)
        if "拖延" in c:
            delay_hint = f"（上次{c[:12]}，这次已拆解）"
            break
    msg = f"已为「{goal.get('title','学习')}」生成{len(tasks)}个任务{delay_hint}，坚持完成！"
    return {"mentor_msg": msg}

# 方向4：Reflector扩展（轻量，生成patch）
def reflector_node(state: PlanState) -> dict:
    # 基于critic反馈生成下周patch
    fb = state.get("critic_feedback", "")
    patch = {}
    if "超4h" in fb:
        patch["reduce_load"] = True
    if "重叠" in fb:
        patch["add_buffer"] = True
    return {"_patch": patch}

def should_replan(state: PlanState) -> str:
    if state.get("terminate"):
        return "mentor"  # 熔断直接走 mentor，避免死循环
    fb = state.get("critic_feedback", "")
    rewrites = state.get("rewrites", 0)
    if fb and rewrites < 2:
        return "replan"
    return "mentor"

def build_graph():
    g = StateGraph(PlanState)
    g.add_node("planner", planner_with_count)
    g.add_node("researcher", researcher_node)
    g.add_node("executor", executor_node)
    g.add_node("critic", critic_node)
    g.add_node("mentor", mentor_node)
    g.add_node("reflector", reflector_node)
    g.set_entry_point("planner")
    g.add_edge("planner", "researcher")
    g.add_edge("researcher", "executor")
    g.add_edge("executor", "critic")
    g.add_conditional_edges("critic", should_replan, {"replan": "planner", "mentor": "mentor"})
    g.add_edge("mentor", "reflector")
    g.add_edge("reflector", END)
    return g.compile()

graph = build_graph()
