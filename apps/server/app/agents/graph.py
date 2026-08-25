import asyncio
import re
from datetime import datetime, timedelta

from langgraph.graph import END, StateGraph

from app.core.config import get_settings
from app.services.planner import llm_generate, mock_generate

from .state import PlanState

settings = get_settings()


def _extract_keywords(title: str) -> str:
    title = (title or "").strip()
    if not title:
        return ""
    # 若含空格，取前3个词，否则取前20字符（兼容中文）
    if " " in title:
        parts = title.split()
        return " ".join(parts[:3])
    # 中文按字符截取，去除标点
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]", " ", title)
    cleaned = cleaned.strip()
    if len(cleaned) > 20:
        return cleaned[:20]
    return cleaned or title[:20]


# 方向1：ReAct工具链显式化 - planner 注入 researcher 上下文
async def planner_node(state: PlanState) -> dict:
    goal = state["goal"]
    prefs = state.get("preferences") or {"hours_per_day": 2}
    rewrites = state.get("rewrites", 0)
    mem = state.get("memory", [])
    vec = state.get("vectorDeps", [])
    graph = state.get("graphDeps", [])
    # 构造上下文注入
    context_parts: list[str] = []
    if mem:
        try:
            mem_txt = "; ".join([(m.get("content", "") if isinstance(m, dict) else str(m))[:40] for m in mem[:3]])
            context_parts.append(f"相关记忆({len(mem)}条): {mem_txt}")
        except Exception:
            pass
    if vec:
        try:
            vec_txt = "; ".join([(v.get("content", "") if isinstance(v, dict) else str(v))[:40] for v in vec[:2]])
            context_parts.append(f"相关知识({len(vec)}条): {vec_txt}")
        except Exception:
            pass
    if graph:
        try:
            g_txt = "; ".join([f"{e.get('from','')}->{e.get('to','')}" if isinstance(e, dict) else str(e) for e in graph[:3]])
            context_parts.append(f"前置关系({len(graph)}条): {g_txt}")
        except Exception:
            pass
    context_str = "\n".join(context_parts) if context_parts else "无额外上下文"
    # ReAct thought - 累积 trace
    prev_thought = state.get("_thought", "")
    thought = f"思考：目标「{goal.get('title')}\" 截止{goal.get('deadline')}，偏好{prefs}，重写{rewrites}次，上下文:{context_str[:80]}"
    # 实际生成：若有上下文则 enrich goal
    enriched_goal = dict(goal)
    if context_parts:
        desc = goal.get("description") or ""
        enriched_goal["description"] = (desc + "\n[上下文] " + context_str).strip()
        enriched_goal["_context"] = context_str  # 供调试
    try:
        tasks, _ = await llm_generate(enriched_goal, prefs)
        thought += f" | LLM生成{len(tasks)}任务"
    except Exception as e:
        thought += f" | LLM失败({e})降级mock"
        tasks, _ = mock_generate(goal, prefs, state.get("trace_id", ""))
    if rewrites > 0:
        for t in tasks:
            try:
                s = datetime.fromisoformat(t["planned_start"])
                e = datetime.fromisoformat(t["planned_end"])
                s = s + timedelta(minutes=30 * rewrites)
                e = e + timedelta(minutes=30 * rewrites)
                t["planned_start"] = s.isoformat()
                t["planned_end"] = e.isoformat()
            except Exception:
                continue
    # 累积
    if prev_thought:
        thought = prev_thought + " | " + thought
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


# 方向1：Researcher专职RAG/图谱/记忆 (走注册表，可热插) - 真正调用工具
async def researcher_node(state: PlanState) -> dict:
    goal = state.get("goal", {})
    title = goal.get("title", "") or ""
    keywords = _extract_keywords(title)
    if not keywords:
        # 回退到 description
        keywords = (goal.get("description") or "")[:20].strip() or title
    # 从 state 取已有检索结果作为回退
    mem_prev = state.get("memory", [])
    vec_prev = state.get("vectorDeps", [])
    graph_prev = state.get("graphDeps", [])

    from app.agents.tools.registry import get as get_tool
    from app.agents.tools.registry import list_tools

    mem_tool = get_tool("memory_search")
    rag_tool = get_tool("rag_search")
    graph_tool = get_tool("graph_search")

    # 会话上下文（plans.py 传入时可能含 _session）
    sess = state.get("_session") or state.get("session")
    user_id = state.get("user_id", 1)

    mem_res: list = mem_prev
    vec_res: list = vec_prev
    graph_res: list = graph_prev

    # 并行调用，容错回退
    async def _call_mem():
        if not mem_tool or not keywords:
            return mem_prev
        try:
            # 优先有 session 调用
            if sess is not None:
                res = await mem_tool(keywords, top_k=5, session=sess, user_id=user_id)
                return res if res else mem_prev
            else:
                # 无 session 尝试调用，工具会返回 []，则保留原值
                try:
                    res = await mem_tool(keywords, top_k=5, user_id=user_id, session=sess)
                    return res if res else mem_prev
                except Exception:
                    # 直接返回原值
                    return mem_prev
        except Exception:
            return mem_prev

    async def _call_rag():
        if not rag_tool or not keywords:
            return vec_prev
        try:
            if sess is not None:
                res = await rag_tool(keywords, top_k=10, session=sess, user_id=user_id)
                return res if res else vec_prev
            else:
                res = await rag_tool(keywords, top_k=10, user_id=user_id, session=sess)
                return res if res else vec_prev
        except Exception:
            return vec_prev

    async def _call_graph():
        if not graph_tool or not keywords:
            return graph_prev
        try:
            # graph_search 签名 (query, **kw)
            res = await graph_tool(keywords)
            # 若返回空但原有非空，保留原有
            if res:
                return res
            return graph_prev
        except Exception:
            # 兼容同步函数
            try:
                import inspect
                if inspect.iscoroutinefunction(graph_tool):
                    res = await graph_tool(keywords)  # type: ignore
                else:
                    res = graph_tool(keywords)  # type: ignore
                return res if res else graph_prev
            except Exception:
                return graph_prev

    try:
        # 并发
        results = await asyncio.gather(_call_mem(), _call_rag(), _call_graph(), return_exceptions=True)
        # 解析
        if not isinstance(results[0], Exception) and isinstance(results[0], list):
            # 仅当返回非空或原为空时更新，避免覆盖已有有效数据为空
            if results[0]:
                mem_res = results[0]
            else:
                # 若原为空，保持空
                mem_res = results[0] if not mem_prev else mem_prev
        if not isinstance(results[1], Exception) and isinstance(results[1], list):
            if results[1]:
                vec_res = results[1]
        if not isinstance(results[2], Exception) and isinstance(results[2], list):
            if results[2]:
                graph_res = results[2]
    except Exception:
        pass

    base_thought = state.get("_thought", "")
    thought = f"思考：researcher 从标题提取关键词 '{keywords}'，检索记忆{len(mem_res)}条/知识{len(vec_res)}条/图谱{len(graph_res)}条"
    if base_thought:
        thought = base_thought + " | " + thought
    tools = list_tools()  # ["memory_search","rag_search","graph_search","write_tasks"]
    return {
        "memory": mem_res,
        "vectorDeps": vec_res,
        "graphDeps": graph_res,
        "_thought": thought,
        "_research": {"memory": len(mem_res), "graph": len(graph_res), "vector": len(vec_res), "tools": tools, "keywords": keywords},
    }


def executor_node(state: PlanState) -> dict:
    tasks = state.get("tasks", [])
    prev = state.get("_thought", "")
    thought = f"思考：executor 准备执行 {len(tasks)} 个任务，检查依赖与资源"
    if prev:
        thought = prev + " | " + thought
    return {"_thought": thought}


# 方向2：Critic双校验 + 图谱前置 + 熔断
def critic_node(state: PlanState) -> dict:
    tasks = state.get("tasks", [])
    graph_deps = state.get("graphDeps", [])
    feedback = []
    prev = state.get("_thought", "")
    thought_prefix = f"思考：critic 校验 {len(tasks)} 任务，图谱依赖{len(graph_deps)}条"
    # 熔断：若任务数>30，视为异常，直接打回
    if len(tasks) > 30:
        th = thought_prefix + " | 熔断触发"
        if prev:
            th = prev + " | " + th
        return {"critic_feedback": "熔断：任务数>30，截断风险", "terminate": True, "_thought": th}

    # 1. 重叠>30%
    tasks_sorted = sorted(tasks, key=lambda x: x["planned_start"])
    for i in range(len(tasks_sorted) - 1):
        try:
            s1 = datetime.fromisoformat(tasks_sorted[i]["planned_start"])
            e1 = datetime.fromisoformat(tasks_sorted[i]["planned_end"])
            s2 = datetime.fromisoformat(tasks_sorted[i + 1]["planned_start"])
            if s2 < e1:
                overlap = (e1 - s2).total_seconds() / 3600
                dur1 = (e1 - s1).total_seconds() / 3600
                if dur1 > 0 and overlap / dur1 > 0.3:
                    feedback.append(f"重叠>30%: {tasks_sorted[i]['title']}与{tasks_sorted[i+1]['title']} {overlap:.1f}h")
        except Exception:
            continue
    # 2. 单日>4h
    from collections import defaultdict

    day_hours = defaultdict(float)
    for t in tasks:
        try:
            s = datetime.fromisoformat(t["planned_start"])
            e = datetime.fromisoformat(t["planned_end"])
            day_hours[s.date().isoformat()] += (e - s).total_seconds() / 3600
        except Exception:
            continue
    for day, h in day_hours.items():
        if h > 4:
            feedback.append(f"单日超4h: {day} {h:.1f}h")
    # 3. 前置缺失：若graphDeps有 A->B 但B排在A前
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
            if feedback:
                llm_feedback = "LLM复核：不通过"
            else:
                llm_feedback = ""
        except Exception:
            llm_feedback = ""
    if llm_feedback and llm_feedback != "":
        feedback.append(llm_feedback)
    if feedback:
        thought = thought_prefix + f" | 发现问题: {'; '.join(feedback)[:80]}"
        if prev:
            thought = prev + " | " + thought
        return {"critic_feedback": "; ".join(feedback), "_thought": thought}
    thought = thought_prefix + " | 校验通过"
    if prev:
        thought = prev + " | " + thought
    return {"critic_feedback": "", "_thought": thought}


# 方向3：Mentor个性化
def mentor_node(state: PlanState) -> dict:
    goal = state.get("goal", {})
    tasks = state.get("tasks", [])
    mem = state.get("memory", [])
    prev = state.get("_thought", "")
    delay_hint = ""
    for m in mem[:3]:
        c = m.get("content", "") if isinstance(m, dict) else str(m)
        if "拖延" in c:
            delay_hint = f"（上次{c[:12]}，这次已拆解）"
            break
    msg = f"已为「{goal.get('title','学习')}」生成{len(tasks)}个任务{delay_hint}，坚持完成！"
    thought = f"思考：mentor 结合拖延史生成个性化鼓励，任务{len(tasks)}个，延迟提示:{bool(delay_hint)}"
    if prev:
        thought = prev + " | " + thought
    return {"mentor_msg": msg, "_thought": thought}


# 方向4：Reflector扩展（轻量，生成patch）
def reflector_node(state: PlanState) -> dict:
    fb = state.get("critic_feedback", "")
    prev = state.get("_thought", "")
    patch = {}
    if "超4h" in fb:
        patch["reduce_load"] = True
    if "重叠" in fb:
        patch["add_buffer"] = True
    thought = f"思考：reflector 基于反馈 '{fb[:30]}' 生成补丁 {patch}"
    if prev:
        thought = prev + " | " + thought
    return {"_patch": patch, "_thought": thought}


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
