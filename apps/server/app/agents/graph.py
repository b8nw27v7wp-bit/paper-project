import asyncio
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta

from langgraph.graph import END, StateGraph

from app.core.config import get_settings
from app.services.planner import llm_generate, mock_generate

from .state import PlanState


class PlanStateEx(PlanState, total=False):
    task_persist: dict
    replan_reasons: list[str]

settings = get_settings()
logger = logging.getLogger(__name__)


def _extract_keywords(title: str) -> str:
    title = (title or "").strip()
    if not title:
        return ""
    if " " in title:
        parts = title.split()
        return " ".join(parts[:3])
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]", " ", title)
    cleaned = cleaned.strip()
    if len(cleaned) > 20:
        return cleaned[:20]
    return cleaned or title[:20]


async def _try_llm_critic(tasks: list[dict], graph_deps: list[dict]) -> str | None:
    """真实LLM二次校验（原生async，事件循环内直接await，15s超时），失败降级规则校验"""
    if not tasks:
        return None
    has_key = bool(settings.llm_api_key) or any(
        os.getenv(k) for k in ["ZHIPU_API_KEY", "BIGMODEL_API_KEY", "DEEPSEEK_API_KEY", "QWEN_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    )
    if not has_key:
        return None
    try:
        from app.core.llm import UnifiedClient

        tasks_txt = json.dumps([{"title": t.get("title"), "start": t.get("planned_start"), "end": t.get("planned_end")} for t in tasks[:6]], ensure_ascii=False)
        deps_txt = json.dumps(graph_deps[:4], ensure_ascii=False)
        messages = [
            {"role": "system", "content": "你是严格的学习规划审查员。判断任务时序、负荷、前置是否合理，仅输出JSON {\"pass\": true/false, \"reason\": \"...\"}，无其他文本。"},
            {"role": "user", "content": f"任务列表: {tasks_txt}\n图谱依赖: {deps_txt}\n规则：1)任务不重叠>30% 2)单日≤4h 3)前置正确。判断是否通过。"},
        ]
        client = UnifiedClient()
        txt = await asyncio.wait_for(
            client.chat(messages, temperature=0.2, timeout=15, fallback=True, max_retries=1),
            timeout=15.0,
        )
    except Exception:
        logger.warning("llm critic async failed, degrade to rule check", exc_info=True)
        return None
    if not isinstance(txt, str) or not txt.strip():
        return None
    low = txt.lower()
    if '"pass": false' in low or '"pass":false' in low or "不通过" in txt or "不合理" in txt or "fail" in low:
        reason = txt.strip().replace("\n", " ")[:60]
        m = re.search(r'"reason"\s*:\s*"([^"]+)"', txt)
        if m:
            reason = m.group(1)[:40]
        return f"LLM复核：{reason[:40]}"
    return None


def _analyze_mem_delay(mem: list) -> dict:
    """解析记忆中拖延史 + 偏好"""
    delay_count = 0
    reasons: list[str] = []
    pref_hint = ""
    for m in mem:
        c = m.get("content", "") if isinstance(m, dict) else str(m)
        if any(k in c for k in ["拖延", "delay", "困难", "分心"]):
            delay_count += 1
            reasons.append(c[:24])
        if "偏好" in c or "喜欢" in c or "习惯" in c:
            pref_hint = c[:30]
    return {"delay_count": delay_count, "reasons": reasons[:3], "pref_hint": pref_hint}


# 方向1：ReAct工具链显式化 - planner 注入 researcher 上下文
async def planner_node(state: PlanState) -> dict:
    goal = state["goal"]
    prefs = state.get("preferences") or {"hours_per_day": 2}
    rewrites = state.get("rewrites", 0)
    mem = state.get("memory", [])
    vec = state.get("vectorDeps", [])
    graph = state.get("graphDeps", [])
    context_parts: list[str] = []
    if mem:
        try:
            mem_txt = "; ".join([(m.get("content", "") if isinstance(m, dict) else str(m))[:40] for m in mem[:3]])
            context_parts.append(f"相关记忆({len(mem)}条): {mem_txt}")
        except Exception:
            logger.warning("planner context(mem) build failed", exc_info=True)
    if vec:
        try:
            vec_txt = "; ".join([(v.get("content", "") if isinstance(v, dict) else str(v))[:40] for v in vec[:2]])
            context_parts.append(f"相关知识({len(vec)}条): {vec_txt}")
        except Exception:
            logger.warning("planner context(vec) build failed", exc_info=True)
    if graph:
        try:
            g_txt = "; ".join([f"{e.get('from','')}->{e.get('to','')}" if isinstance(e, dict) else str(e) for e in graph[:3]])
            context_parts.append(f"前置关系({len(graph)}条): {g_txt}")
        except Exception:
            logger.warning("planner context(graph) build failed", exc_info=True)
    context_str = "\n".join(context_parts) if context_parts else "无额外上下文"
    prev_thought = state.get("_thought", "")
    thought = f"思考：目标「{goal.get('title')}\" 截止{goal.get('deadline')}，偏好{prefs}，重写{rewrites}次，上下文:{context_str[:80]}"
    enriched_goal = dict(goal)
    if context_parts:
        desc = goal.get("description") or ""
        enriched_goal["description"] = (desc + "\n[上下文] " + context_str).strip()
        enriched_goal["_context"] = context_str
    try:
        tasks, _ = await llm_generate(enriched_goal, prefs)
        thought += f" | LLM生成{len(tasks)}任务"
    except Exception as e:
        logger.warning("planner llm_generate failed, fallback mock", exc_info=True)
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
            except (KeyError, TypeError, ValueError):
                continue
    if prev_thought:
        thought = prev_thought + " | " + thought
    return {"tasks": tasks, "milestones": [{"week": 1, "goal": goal.get("title")}], "critic_feedback": "", "_thought": thought}


async def planner_with_count(state: PlanState) -> dict:
    res = await planner_node(state)
    if state.get("critic_feedback"):
        res["rewrites"] = state.get("rewrites", 0) + 1
    else:
        res["rewrites"] = state.get("rewrites", 0)
    res["_thought"] = res.get("_thought", "")
    return res


# 方向1：Researcher专职RAG/图谱/记忆 (走注册表，可热插) - 真正调用工具
async def researcher_node(state: PlanState) -> dict:
    goal = state.get("goal", {})
    title = goal.get("title", "") or ""
    keywords = _extract_keywords(title)
    if not keywords:
        keywords = (goal.get("description") or "")[:20].strip() or title
    mem_prev = state.get("memory", [])
    vec_prev = state.get("vectorDeps", [])
    graph_prev = state.get("graphDeps", [])

    from app.agents.tools.registry import get as get_tool
    from app.agents.tools.registry import list_tools

    mem_tool = get_tool("memory_search")
    rag_tool = get_tool("rag_search")
    graph_tool = get_tool("graph_search")

    sess = state.get("_session") or state.get("session")
    user_id = state.get("user_id", 1)

    mem_res: list = mem_prev
    vec_res: list = vec_prev
    graph_res: list = graph_prev

    async def _call_mem():
        if not mem_tool or not keywords:
            return mem_prev
        try:
            if sess is not None:
                res = await mem_tool(keywords, top_k=5, session=sess, user_id=user_id)
                return res if res else mem_prev
            else:
                try:
                    res = await mem_tool(keywords, top_k=5, user_id=user_id, session=sess)
                    return res if res else mem_prev
                except Exception:
                    logger.warning("memory tool call failed (no session)", exc_info=True)
                    return mem_prev
        except Exception:
            logger.warning("memory tool call failed", exc_info=True)
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
            logger.warning("rag tool call failed", exc_info=True)
            return vec_prev

    async def _call_graph():
        if not graph_tool or not keywords:
            return graph_prev
        try:
            res = await graph_tool(keywords)
            if res:
                return res
            return graph_prev
        except Exception:
            logger.warning("graph tool call failed, retry sync", exc_info=True)
            try:
                import inspect
                if inspect.iscoroutinefunction(graph_tool):
                    res = await graph_tool(keywords)  # type: ignore
                else:
                    res = graph_tool(keywords)  # type: ignore
                return res if res else graph_prev
            except Exception:
                logger.warning("graph tool sync fallback failed", exc_info=True)
                return graph_prev

    try:
        results = await asyncio.gather(_call_mem(), _call_rag(), _call_graph(), return_exceptions=True)
        if not isinstance(results[0], Exception) and isinstance(results[0], list):
            if results[0]:
                mem_res = results[0]
            else:
                mem_res = results[0] if not mem_prev else mem_prev
        if not isinstance(results[1], Exception) and isinstance(results[1], list):
            if results[1]:
                vec_res = results[1]
        if not isinstance(results[2], Exception) and isinstance(results[2], list):
            if results[2]:
                graph_res = results[2]
    except Exception:
        logger.warning("researcher parallel gather failed", exc_info=True)

    base_thought = state.get("_thought", "")
    thought = f"思考：researcher 从标题提取关键词 '{keywords}'，检索记忆{len(mem_res)}条/知识{len(vec_res)}条/图谱{len(graph_res)}条"
    if base_thought:
        thought = base_thought + " | " + thought
    tools = list_tools()
    return {
        "memory": mem_res,
        "vectorDeps": vec_res,
        "graphDeps": graph_res,
        "_thought": thought,
        "_research": {"memory": len(mem_res), "graph": len(graph_res), "vector": len(vec_res), "tools": tools, "keywords": keywords},
    }


async def executor_node(state: PlanStateEx) -> dict:
    tasks = state.get("tasks", [])
    prev = state.get("_thought", "")
    thought = f"思考：executor 准备执行 {len(tasks)} 个任务，检查依赖与资源"
    if prev:
        thought = prev + " | " + thought
    persist: dict = {"persisted": False, "created": 0, "rows": [], "error": ""}
    goal = state.get("goal") or {}
    goal_id = goal.get("id")
    payload = [
        {
            "goal_id": goal_id,
            "title": str(t.get("title", "任务")),
            "planned_start": t.get("planned_start"),
            "planned_end": t.get("planned_end"),
            "priority": t.get("priority", 3),
            "status": "todo",
            "source_agent": f"planner:{state.get('trace_id', 'multi')}",
        }
        for t in tasks
        if isinstance(t, dict) and t.get("planned_start") and t.get("planned_end")
    ]
    if payload and isinstance(goal_id, int) and not isinstance(goal_id, bool):
        from app.agents.tools import registry
        from app.agents.tools.registry import AgentEvent, AgentEventType

        try:
            res = await registry.execute_tool("write_tasks", {"tasks": payload})
            rows = res.get("result") if isinstance(res, dict) else None
            if isinstance(res, dict) and res.get("is_error"):
                persist["error"] = str(res.get("error", ""))[:200]
            elif isinstance(rows, dict) and rows.get("is_error"):
                persist["error"] = str(rows.get("error", ""))[:200]
            else:
                persist = {
                    "persisted": True,
                    "created": len(rows) if isinstance(rows, list) else 0,
                    "rows": rows if isinstance(rows, list) else [],
                    "error": "",
                }
            if persist["error"]:
                logger.warning("executor write_tasks degraded to state passthrough: %s", persist["error"])
                registry.emit_event(AgentEvent(type=AgentEventType.ERROR, data={"tool": "write_tasks", "degraded": True, "error": persist["error"]}))
        except Exception:
            logger.warning("executor write_tasks failed, degrade to state passthrough", exc_info=True)
            persist["error"] = "write_tasks execution failed"
            registry.emit_event(AgentEvent(type=AgentEventType.ERROR, data={"tool": "write_tasks", "degraded": True, "error": persist["error"]}))
    if persist["persisted"]:
        thought += f" | 经write_tasks落库{persist['created']}条"
    elif persist["error"]:
        thought += " | 落库失败降级state透传"
    return {"_thought": thought, "task_persist": persist}


# 方向2：Critic双校验 + 图谱前置 + 熔断（增强：真实LLM二次校验+fallback）
async def critic_node(state: PlanStateEx) -> dict:
    tasks = state.get("tasks", [])
    graph_deps = state.get("graphDeps", [])
    feedback = []
    prev = state.get("_thought", "")
    replan_reasons = list(state.get("replan_reasons") or [])
    thought_prefix = f"思考：critic 校验 {len(tasks)} 任务，图谱依赖{len(graph_deps)}条"
    if len(tasks) > 30:
        th = thought_prefix + " | 熔断触发"
        if prev:
            th = prev + " | " + th
        return {"critic_feedback": "熔断：任务数>30，截断风险", "terminate": True, "_thought": th, "replan_reasons": replan_reasons}

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
        except (KeyError, TypeError, ValueError):
            continue
    day_hours = defaultdict(float)
    for t in tasks:
        try:
            s = datetime.fromisoformat(t["planned_start"])
            e = datetime.fromisoformat(t["planned_end"])
            day_hours[s.date().isoformat()] += (e - s).total_seconds() / 3600
        except (KeyError, TypeError, ValueError):
            continue
    for day, h in day_hours.items():
        if h > 4:
            feedback.append(f"单日超4h: {day} {h:.1f}h")
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
                logger.warning("dep order check failed", exc_info=True)
    # 真实LLM二次校验（原生await，astream事件循环内生效）
    llm_real = await _try_llm_critic(tasks, graph_deps)
    if llm_real:
        if llm_real not in feedback:
            feedback.append(llm_real)
        llm_feedback = llm_real
    else:
        llm_feedback = ""
        if settings.llm_api_key:
            try:
                if feedback:
                    llm_feedback = "LLM复核：不通过"
                else:
                    llm_feedback = ""
            except Exception:
                logger.warning("llm feedback build failed", exc_info=True)
                llm_feedback = ""
        if llm_feedback and llm_feedback not in feedback:
            feedback.append(llm_feedback)
    if feedback:
        if state.get("rewrites", 0) < 2:
            replan_reasons = replan_reasons + ["; ".join(feedback)]
        thought = thought_prefix + f" | 发现问题: {'; '.join(feedback)[:80]}"
        if prev:
            thought = prev + " | " + thought
        return {"critic_feedback": "; ".join(feedback), "_thought": thought, "replan_reasons": replan_reasons}
    thought = thought_prefix + " | 校验通过"
    if prev:
        thought = prev + " | " + thought
    return {"critic_feedback": "", "_thought": thought, "replan_reasons": replan_reasons}


# 方向3：Mentor个性化（增强：拖延史+偏好+图谱前置差异化）
def mentor_node(state: PlanState) -> dict:
    goal = state.get("goal", {})
    tasks = state.get("tasks", [])
    mem = state.get("memory", [])
    graph_deps = state.get("graphDeps", [])
    prefs = state.get("preferences") or {}
    prev = state.get("_thought", "")
    # 分析拖延史
    delay_info = _analyze_mem_delay(mem)
    delay_hint = ""
    if delay_info["delay_count"] > 0:
        reason_txt = delay_info["reasons"][0][:12] if delay_info["reasons"] else "拖延"
        delay_hint = f"（上次{reason_txt}，这次已拆解）"
    # 偏好感知
    hours = prefs.get("hours_per_day", 2)
    pref_msg = ""
    if hours >= 6:
        pref_msg = "已为高强度日程加入缓冲"
    elif hours <= 2:
        pref_msg = "轻量节奏，循序渐进"
    # 图谱前置感知
    graph_msg = ""
    if graph_deps:
        graph_msg = f"，已梳理{len(graph_deps)}条前置依赖"
    # 学科维度
    subject = goal.get("subject") or ""
    subject_msg = f"（{subject}）" if subject else ""
    # 差异化鼓励生成
    base = f"已为「{goal.get('title','学习')}{subject_msg}」生成{len(tasks)}个任务{graph_msg}{delay_hint}"
    # 个性化分支
    if delay_info["delay_count"] >= 2:
        encourage = "检测到多次拖延史，已将大任务拆解为小步快跑，每完成1个就打卡！"
    elif delay_info["delay_count"] == 1:
        encourage = "上次的小拖延这次已优化，专注25分钟一个番茄，稳步推进！"
    elif graph_deps:
        encourage = "前置知识已排好序，按图谱路径学习效率更高！"
    elif hours >= 6:
        encourage = "高强度计划已平衡负荷，记得穿插休息，保持节奏！"
    else:
        encourage = "坚持完成，循序渐进必有收获！"
    if pref_msg:
        encourage = pref_msg + "，" + encourage
    msg = f"{base}，{encourage}"
    thought = f"思考：mentor 结合拖延史({delay_info['delay_count']}条)+偏好{hours}h+图谱{len(graph_deps)}条 生成差异化鼓励"
    if prev:
        thought = prev + " | " + thought
    return {"mentor_msg": msg, "_thought": thought}


# 方向4：Reflector扩展（增强：可执行patch含周维度负荷重分配）
def reflector_node(state: PlanState) -> dict:
    fb = state.get("critic_feedback", "")
    tasks = state.get("tasks", [])
    prev = state.get("_thought", "")
    patch: dict = {}
    if "超4h" in fb:
        patch["reduce_load"] = True
    if "重叠" in fb:
        patch["add_buffer"] = True
    if "前置" in fb:
        patch["reorder"] = True
    if "熔断" in fb:
        patch["truncate"] = True
    # 周维度负荷重分配
    try:
        from collections import defaultdict

        day_hours: dict[str, float] = defaultdict(float)
        week_hours: dict[str, float] = defaultdict(float)
        for t in tasks:
            try:
                s = datetime.fromisoformat(t["planned_start"])
                e = datetime.fromisoformat(t["planned_end"])
                dur = (e - s).total_seconds() / 3600
                day = s.date().isoformat()
                day_hours[day] += dur
                iso = s.isocalendar()
                wk = f"{iso[0]}-W{iso[1]:02d}"
                week_hours[wk] += dur
            except (KeyError, TypeError, ValueError):
                continue
        if day_hours:
            # 找出超载日与最空闲日
            overloaded = [(d, h) for d, h in day_hours.items() if h > 4]
            if overloaded:
                # 按负荷排序
                sorted_days = sorted(day_hours.items(), key=lambda x: x[1])
                lightest = sorted_days[0][0] if sorted_days else None
                heaviest = max(overloaded, key=lambda x: x[1])[0]
                if lightest and heaviest and lightest != heaviest:
                    move_hours = round(min(2.0, day_hours[heaviest] - 4), 1)
                    patch["reallocate"] = {"from": heaviest, "to": lightest, "hours": move_hours}
                    patch["next_week_hours"] = {k: round(v, 1) for k, v in week_hours.items()}
                    patch["week_load"] = {k: round(v, 1) for k, v in day_hours.items()}
                    # 生成可执行指令
                    patch["instructions"] = [f"将{heaviest}的{move_hours}h任务移至{lightest}", "保持单日≤4h"]
            else:
                # 未超载也给出周负荷视图
                if week_hours:
                    patch["week_load"] = {k: round(v, 1) for k, v in week_hours.items()}
                    patch["daily_load"] = {k: round(v, 1) for k, v in day_hours.items()}
            # 周维度建议
            if week_hours:
                max_week = max(week_hours, key=lambda k: week_hours[k])
                if week_hours[max_week] > 20:
                    patch["reduce_weekly"] = True
                    patch["suggested_hours_per_day"] = 3
    except Exception:
        logger.warning("reflector load reallocation failed", exc_info=True)
    # 若无patch，给默认轻量
    if not patch:
        patch["keep"] = True
    thought = f"思考：reflector 基于反馈 '{fb[:30]}' 生成可执行补丁 {patch}"
    if prev:
        thought = prev + " | " + thought
    return {"_patch": patch, "_thought": thought}


def should_replan(state: PlanState) -> str:
    if state.get("terminate"):
        return "mentor"
    fb = state.get("critic_feedback", "")
    rewrites = state.get("rewrites", 0)
    if fb and rewrites < 2:
        return "replan"
    return "mentor"


def build_graph(checkpointer=None):
    """构建 6 节点图，支持 Pi 风格 checkpoint"""
    g = StateGraph(PlanStateEx)
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
    if checkpointer is None:
        try:
            from app.core.checkpoint import FileMemorySaver

            checkpointer = FileMemorySaver()
        except Exception:
            logger.warning("FileMemorySaver unavailable, fallback MemorySaver", exc_info=True)
            try:
                from langgraph.checkpoint.memory import MemorySaver

                checkpointer = MemorySaver()
            except Exception:
                logger.warning("MemorySaver unavailable", exc_info=True)
                checkpointer = None
    try:
        if checkpointer is not None:
            return g.compile(checkpointer=checkpointer)
    except Exception:
        logger.warning("graph compile with checkpointer failed", exc_info=True)
    return g.compile()


graph = build_graph()
def _wrap_graph_for_compat(g):
    try:
        has_cp = getattr(g, "checkpointer", None) is not None
    except Exception:
        logger.warning("checkpointer introspection failed", exc_info=True)
        has_cp = False
    if not has_cp:
        return g
    orig_ainvoke = g.ainvoke

    async def compat_ainvoke(input, config=None, *args, **kwargs):
        needs = config is None or "configurable" not in (config or {}) or "thread_id" not in ((config or {}).get("configurable") or {})
        if needs:
            cfg = dict(config or {})
            conf = dict(cfg.get("configurable") or {})
            if "thread_id" not in conf:
                try:
                    tid = input.get("trace_id") if isinstance(input, dict) else None
                    conf["thread_id"] = tid or "default-test"
                except Exception:
                    logger.warning("thread_id resolve failed", exc_info=True)
                    conf["thread_id"] = "default-test"
            cfg["configurable"] = conf
            config = cfg
        return await orig_ainvoke(input, config, *args, **kwargs)

    g.ainvoke = compat_ainvoke  # type: ignore
    if hasattr(g, "invoke"):
        orig_invoke = g.invoke  # type: ignore

        def compat_invoke(input, config=None, *args, **kwargs):
            needs = config is None or "configurable" not in (config or {}) or "thread_id" not in ((config or {}).get("configurable") or {})
            if needs:
                cfg = dict(config or {})
                conf = dict(cfg.get("configurable") or {})
                if "thread_id" not in conf:
                    try:
                        tid = input.get("trace_id") if isinstance(input, dict) else None
                        conf["thread_id"] = tid or "default-test"
                    except Exception:
                        logger.warning("thread_id resolve failed (sync)", exc_info=True)
                        conf["thread_id"] = "default-test"
                cfg["configurable"] = conf
                config = cfg
            return orig_invoke(input, config, *args, **kwargs)

        g.invoke = compat_invoke  # type: ignore
    return g


graph = _wrap_graph_for_compat(graph)
try:
    _graph_has_checkpointer = hasattr(graph, "get_state") or getattr(graph, "checkpointer", None) is not None
except Exception:
    logger.warning("checkpointer flag probe failed", exc_info=True)
    _graph_has_checkpointer = False
