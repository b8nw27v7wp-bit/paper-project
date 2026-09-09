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

from .compaction import truncate_head
from .state import PlanState


class PlanStateEx(PlanState, total=False):
    task_persist: dict
    replan_reasons: list[str]
    # S10 followUp/abort：追问续跑标记 + 中断透传（经 state->context signal，不改 registry 签名）
    _followup: str
    followup_msg: str
    signal: dict
    abort_flag: bool

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


async def _try_llm_critic(tasks: list[dict], graph_deps: list[dict]) -> tuple[str | None, bool]:
    """真实LLM二次校验（原生async，事件循环内直接await，15s超时），失败降级规则校验。

    返回 (feedback, degraded)：feedback 非空表示 LLM 明确不通过；
    degraded=True 表示已尝试 LLM 但失败（异常/空响应），调用方不得拼伪造
    “LLM复核:不通过”，改为 state 标记 llm:degraded 并走规则校验降级。
    """
    if not tasks:
        return None, False
    has_key = bool(settings.llm_api_key) or any(
        os.getenv(k) for k in ["ZHIPU_API_KEY", "BIGMODEL_API_KEY", "DEEPSEEK_API_KEY", "QWEN_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    )
    if not has_key:
        return None, False
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
        return None, True
    if not isinstance(txt, str) or not txt.strip():
        return None, True
    low = txt.lower()
    if '"pass": false' in low or '"pass":false' in low or "不通过" in txt or "不合理" in txt or "fail" in low:
        reason = txt.strip().replace("\n", " ")[:60]
        m = re.search(r'"reason"\s*:\s*"([^"]+)"', txt)
        if m:
            reason = m.group(1)[:40]
        return f"LLM复核：{reason[:40]}", False
    return None, False


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
    # Pi对标abort：已中断不再发LLM，直接空任务快返（调用方按cancelled跳过落库）
    try:
        if bool(state.get("abort_flag", False)):
            _pt = state.get("_thought", "")
            _th = f"{_pt} | 中断已请求，跳过LLM" if _pt else "中断已请求，跳过LLM"
            # S10 followUp消费即清：避免 reflector->planner 复用后旧标记残留致无限续跑
            return {"tasks": [], "milestones": [], "critic_feedback": "", "_thought": _th, "_followup": "", "followup_msg": ""}
    except Exception:
        pass
    prefs = state.get("preferences") or {"hours_per_day": 2}
    rewrites = state.get("rewrites", 0)
    mem = state.get("memory", [])
    vec = state.get("vectorDeps", [])
    graph = state.get("graphDeps", [])
    context_parts: list[str] = []
    if mem:
        try:
            mem_txt = truncate_head("; ".join([(m.get("content", "") if isinstance(m, dict) else str(m))[:40] for m in mem[:3]]))
            context_parts.append(f"相关记忆({len(mem)}条): {mem_txt}")
        except Exception:
            logger.warning("planner context(mem) build failed", exc_info=True)
    if vec:
        try:
            vec_txt = truncate_head("; ".join([(v.get("content", "") if isinstance(v, dict) else str(v))[:40] for v in vec[:2]]))
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
        _llm_out = await llm_generate(enriched_goal, prefs)
        # S2: 兼容 2 元/3 元返回，透出 finish_reason；length 则丢弃本批不写落库
        _meta: dict = {}
        _tasks: list = []
        try:
            if isinstance(_llm_out, (list, tuple)) and len(_llm_out) == 3:
                _tasks, _, _meta = _llm_out  # type: ignore[misc]
                if not isinstance(_meta, dict):
                    _meta = {}
            elif isinstance(_llm_out, (list, tuple)) and len(_llm_out) == 2:
                _tasks, _ = _llm_out  # type: ignore[misc]
                try:
                    from app.services import planner as _planner_mod

                    _lm = getattr(_planner_mod, "LAST_LLM_META", None)
                    if isinstance(_lm, dict) and _lm:
                        _meta = _lm
                    else:
                        _lm2 = getattr(llm_generate, "last_meta", None)
                        if isinstance(_lm2, dict) and _lm2:
                            _meta = _lm2
                except Exception:
                    _meta = {}
            else:
                _tasks = []
        except Exception:
            logger.warning("planner llm meta unpack failed", exc_info=True)
            _tasks, _meta = [], {}
        # 加固：裸任务列表误判（3任务list曾被误解包为2/3元）时回退空，避免下游迭代dict键
        if not isinstance(_tasks, list):
            _tasks = []
        tasks = _tasks
        if isinstance(_meta, dict) and _meta.get("finish_reason") == "length":
            # Pi对标(agent-loop length整批失败)：截断batch不可信，重发一次mock兜底而非空计划
            try:
                tasks, _ = mock_generate(enriched_goal, prefs, state.get("trace_id", ""))
                thought += " | 截断丢弃已重发mock"
            except Exception:
                logger.warning("length fallback mock_generate failed", exc_info=True)
                tasks = []
                thought += " | 截断丢弃待重发"
        else:
            thought += f" | LLM生成{len(tasks)}任务"
    except Exception as e:
        logger.warning("planner llm_generate failed, fallback mock", exc_info=True)
        thought += f" | LLM失败({e})降级mock"
        tasks, _ = mock_generate(enriched_goal, prefs, state.get("trace_id", ""))
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
        # P1 真重分配：按 patch 语义逐项落地（mock/真LLM双分支共用同一后处理，保证一致；
        # critic 下一轮按规则二次校验冲突/负荷，rewrites<3 上限语义，见 should_replan；
        # P2 第3轮(rewrites>=2)仅允许轻patch(reorder/add_buffer)，重任务不再移周）。
        try:
            from app.services.planner import apply_patch_reallocation as _apply_patch

            try:
                _rw_eff = int(state.get("rewrites", 0) or 0)
            except (TypeError, ValueError):
                _rw_eff = 0
            _is_light_round = _rw_eff >= 2
            _eff: dict = {}
            _raw = state.get("_patch")
            if isinstance(_raw, dict):
                _eff.update(_raw)
            # 首轮重排时 reflector 尚未执行（末节点），从 critic_feedback 派生等价 patch，避免空转
            # P2：第3轮仅派生轻量（重叠→add_buffer，前置→reorder），不再派生重分配/截断
            _fb = state.get("critic_feedback", "") or ""
            if _fb:
                if not _is_light_round and ("超4h" in _fb or "超载" in _fb or "负荷" in _fb) and "reduce_load" not in _eff:
                    _eff["reduce_load"] = True
                if "重叠" in _fb and "add_buffer" not in _eff:
                    _eff["add_buffer"] = True
                if "前置" in _fb and "reorder" not in _eff:
                    _eff["reorder"] = True
                if not _is_light_round and "熔断" in _fb and "truncate" not in _eff:
                    _eff["truncate"] = True
            # 周反思 patch 经 plans.py 合并进 preferences，回注到本次重分配
            for _k in ("reduce_load", "add_buffer", "reorder", "reallocate", "truncate", "buffer_minutes", "reduce_daily_hours", "reduce_weekly"):
                try:
                    if _k not in _eff and isinstance(prefs, dict) and _k in prefs:
                        _eff[_k] = prefs[_k]
                except (TypeError, AttributeError):
                    continue
            # P2 第3轮过滤：仅保留轻量键+幂等元信息，重键丢弃以杜绝跨周搬移
            if _is_light_round:
                _LIGHT_KEEP = {"reorder", "add_buffer", "buffer_minutes", "patch_id", "auto_execute", "retry_policy", "keep"}
                _eff = {k: v for k, v in _eff.items() if k in _LIGHT_KEEP}
            if _eff and not _eff.get("keep"):
                _before = len(tasks)
                tasks = _apply_patch(tasks, _eff, prefs)
                thought += f" | patch重分配{sorted(_eff.keys())}({_before}任务)"
            else:
                thought += " | 空patch保持平移(旧行为)"
        except Exception:
            logger.warning("planner patch reallocation failed, keep shifted tasks", exc_info=True)
    if prev_thought:
        thought = prev_thought + " | " + thought
    # S10 followUp消费即清（默认空即无op，旧流零变化；置位时恰好续跑一轮后清零防循环）
    return {"tasks": tasks, "milestones": [{"week": 1, "goal": goal.get("title")}], "critic_feedback": "", "_thought": thought, "_followup": "", "followup_msg": ""}


async def planner_with_count(state: PlanState) -> dict:
    res = await planner_node(state)
    if state.get("critic_feedback"):
        res["rewrites"] = state.get("rewrites", 0) + 1
    else:
        res["rewrites"] = state.get("rewrites", 0)
    res["_thought"] = res.get("_thought", "")
    return res


# 方向1：Researcher专职RAG/图谱/记忆 (走注册表 execute_tool，可热插) - 真正调用工具
async def researcher_node(state: PlanState) -> dict:
    goal = state.get("goal", {})
    title = goal.get("title", "") or ""
    keywords = _extract_keywords(title)
    if not keywords:
        keywords = (goal.get("description") or "")[:20].strip() or title
    mem_prev = state.get("memory", [])
    vec_prev = state.get("vectorDeps", [])
    graph_prev = state.get("graphDeps", [])

    from app.agents.tools.registry import execute_tool
    from app.agents.tools.registry import list_tools

    sess = state.get("_session") or state.get("session")
    user_id = state.get("user_id", 1)
    # S10 abort 透传：registry 签名冻结，abort 经 context 透传（signal/abort_flag=is_disconnected 初值，plans.py 每 chunk 刷新）
    try:
        _abort = bool(state.get("abort_flag", False))
        _sig = state.get("signal") if isinstance(state.get("signal"), dict) else {"abort_flag": _abort}
        _sig_ctx: dict = dict(state) if isinstance(state, dict) else {}
        _sig_ctx["signal"] = _sig if isinstance(_sig, dict) else {"abort_flag": _abort}
        _sig_ctx["abort_flag"] = _abort
    except Exception:
        _sig_ctx = state  # type: ignore

    mem_res: list = mem_prev
    vec_res: list = vec_prev
    graph_res: list = graph_prev

    async def _call_mem():
        if not keywords:
            return mem_prev
        try:
            args: dict = {"query": keywords, "top_k": 5, "user_id": user_id}
            if sess is not None:
                args["session"] = sess
            res = await execute_tool("memory_search", args, context=_sig_ctx)
            if isinstance(res, dict) and not res.get("is_error"):
                data = res.get("result")
                return data if isinstance(data, list) and data else mem_prev
            return mem_prev
        except Exception:
            logger.warning("memory tool call failed", exc_info=True)
            return mem_prev

    async def _call_rag():
        if not keywords:
            return vec_prev
        try:
            args: dict = {"query": keywords, "top_k": 10, "user_id": user_id}
            if sess is not None:
                args["session"] = sess
            res = await execute_tool("rag_search", args, context=_sig_ctx)
            if isinstance(res, dict) and not res.get("is_error"):
                data = res.get("result")
                return data if isinstance(data, list) and data else vec_prev
            return vec_prev
        except Exception:
            logger.warning("rag tool call failed", exc_info=True)
            return vec_prev

    async def _call_graph():
        if not keywords:
            return graph_prev
        try:
            res = await execute_tool("graph_search", {"query": keywords}, context=_sig_ctx)
            if isinstance(res, dict) and not res.get("is_error"):
                data = res.get("result")
                if isinstance(data, list) and data:
                    return data
            return graph_prev
        except Exception:
            logger.warning("graph tool call failed", exc_info=True)
            return graph_prev

    try:
        # S10：researcher 三检索并行 gather 已带 return_exceptions=True（异常单路降级，不断整批），此处仅注释不断言行为
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
    # 全链透传：user_id/session 必填（write_tasks 已改为调用方必填，默认不再回退 user_id=1）
    _sess = state.get("_session") or state.get("session")
    _uid = state.get("user_id")
    if not isinstance(_uid, int) or isinstance(_uid, bool):
        _uid = None
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

        # S10 abort 透传：registry 签名不动，只在 context 里带 signal/abort_flag（=is_disconnected）
        _e_ctx: dict = state  # type: ignore[assignment]
        try:
            _e_abort = bool(state.get("abort_flag", False))
            _e_sig = state.get("signal") if isinstance(state.get("signal"), dict) else {"abort_flag": _e_abort}
            _e_ctx: dict = dict(state) if isinstance(state, dict) else {}
            _e_ctx["signal"] = _e_sig if isinstance(_e_sig, dict) else {"abort_flag": _e_abort}
            _e_ctx["abort_flag"] = _e_abort
        except Exception:
            _e_ctx = state  # type: ignore
        if _uid is None:
            persist["error"] = "user_id必填(调用方透传)"
            registry.emit_event(AgentEvent(type=AgentEventType.ERROR, data={"tool": "write_tasks", "degraded": True, "error": persist["error"]}))
        else:
            try:
                _args: dict = {"tasks": payload, "user_id": _uid}
                if _sess is not None:
                    _args["session"] = _sess
                res = await registry.execute_tool("write_tasks", _args, context=_e_ctx)
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
    elif tasks:
        # 避免静默跳过：payload 为空或 goal_id 非法时给出明确 error
        if not payload:
            persist["error"] = "no valid tasks(payload empty, missing planned_start/planned_end)"
        elif not isinstance(goal_id, int) or isinstance(goal_id, bool):
            persist["error"] = "goal_id非法(需整数)"
    if persist["persisted"]:
        thought += f" | 经write_tasks落库{persist['created']}条"
    elif persist["error"]:
        thought += " | 落库失败降级state透传"
    # P1 可选双写：仅 preferences.require_calendar==true 时在write_tasks成功后调用calendar_create，默认关闭防误写
    if persist.get("persisted"):
        try:
            _prefs = state.get("preferences") or {}
            _need_cal = isinstance(_prefs, dict) and _prefs.get("require_calendar") is True
            if _need_cal:
                from app.agents.tools import registry as _reg2

                _rows = persist.get("rows") or []
                _cal_results: list = []
                for _r in _rows if isinstance(_rows, list) else []:
                    try:
                        if not isinstance(_r, dict):
                            continue
                        _t = str(_r.get("title") or "任务")
                        _s = _r.get("planned_start")
                        _e = _r.get("planned_end")
                        if hasattr(_s, "isoformat"):
                            _s = _s.isoformat()
                        if hasattr(_e, "isoformat"):
                            _e = _e.isoformat()
                        if not _s:
                            continue
                        _cargs: dict = {"title": _t, "start": str(_s)}
                        if _e:
                            _cargs["end"] = str(_e)
                        _cres = await _reg2.execute_tool("calendar_create", _cargs, context=_e_ctx)
                        _cal_results.append(_cres)
                    except Exception:
                        logger.warning("executor calendar_create per-task failed", exc_info=True)
                        continue
                _ok = 0
                for _c in _cal_results:
                    if not isinstance(_c, dict):
                        continue
                    if _c.get("is_error"):
                        continue
                    _inner = _c.get("result")
                    if isinstance(_inner, dict) and _inner.get("is_error"):
                        continue
                    _ok += 1
                persist["calendar_sync"] = {"enabled": True, "tried": len(_cal_results), "ok": _ok}
                thought += f" | 日历双写{_ok}/{len(_cal_results)}条"
                if _ok < len(_cal_results):
                    thought += "(部分失败已降级)"
            else:
                persist["calendar_sync"] = {"enabled": False}
                thought += " | 日历双写关闭(默认)"
        except Exception:
            logger.warning("executor calendar dual-write failed", exc_info=True)
            try:
                persist["calendar_sync"] = {"enabled": True, "error": "calendar dual-write failed"}
            except Exception:
                pass
            thought += " | 日历双写失败已降级"
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

    tasks_sorted = sorted(tasks, key=lambda x: x.get("planned_start", "") if isinstance(x, dict) else "")
    for i in range(len(tasks_sorted) - 1):
        try:
            s1 = datetime.fromisoformat(tasks_sorted[i].get("planned_start", ""))
            e1 = datetime.fromisoformat(tasks_sorted[i].get("planned_end", ""))
            s2 = datetime.fromisoformat(tasks_sorted[i + 1].get("planned_start", ""))
            if s2 < e1:
                overlap = (e1 - s2).total_seconds() / 3600
                dur1 = (e1 - s1).total_seconds() / 3600
                if dur1 > 0 and overlap / dur1 > 0.3:
                    feedback.append(f"重叠>30%: {tasks_sorted[i].get('title', '?')}与{tasks_sorted[i+1].get('title', '?')} {overlap:.1f}h")
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    day_hours = defaultdict(float)
    for t in tasks:
        try:
            if not isinstance(t, dict):
                continue
            s = datetime.fromisoformat(t.get("planned_start", ""))
            e = datetime.fromisoformat(t.get("planned_end", ""))
            day_hours[s.date().isoformat()] += (e - s).total_seconds() / 3600
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    for day, h in day_hours.items():
        if h > 4:
            feedback.append(f"单日超4h: {day} {h:.1f}h")
    title_order = [t.get("title", "") if isinstance(t, dict) else "" for t in tasks]
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
    # 真实LLM二次校验（原生await，astream事件循环内生效；失败走规则降级，不拼伪造复核）
    llm_real, llm_degraded = await _try_llm_critic(tasks, graph_deps)
    if llm_real:
        if llm_real not in feedback:
            feedback.append(llm_real)
    # llm_degraded=True 时仅打标，不追加伪造“LLM复核:不通过”，规则校验结果为准
    llm_marker: dict = {"llm": "degraded"} if llm_degraded else {}
    if feedback:
        try:
            _rw = int(state.get("rewrites", 0) or 0)
        except (TypeError, ValueError):
            _rw = 0
        if _rw < 3:
            replan_reasons = replan_reasons + ["; ".join(feedback)]
        thought = thought_prefix + f" | 发现问题: {'; '.join(feedback)[:80]}"
        if llm_degraded:
            thought += " | llm:degraded走规则校验降级"
        if prev:
            thought = prev + " | " + thought
        return {"critic_feedback": "; ".join(feedback), "_thought": thought, "replan_reasons": replan_reasons, **llm_marker}
    thought = thought_prefix + " | 校验通过"
    if llm_degraded:
        thought += " | llm:degraded走规则校验降级"
    if prev:
        thought = prev + " | " + thought
    return {"critic_feedback": "", "_thought": thought, "replan_reasons": replan_reasons, **llm_marker}


# P3 Reviewer复核打分（纯函数，无LLM调用）：输入tasks+critic_feedback，输出_review+_thought
def reviewer_node(state: PlanState) -> dict:
    tasks = state.get("tasks", []) or []
    fb = state.get("critic_feedback", "") or ""
    prev = state.get("_thought", "") or ""
    issues: list[str] = []
    if fb:
        try:
            parts = re.split(r"[;；,，\n]+", fb)
            for p in parts:
                s = (p or "").strip()
                if s and s not in issues:
                    issues.append(s[:200])
        except Exception:
            logger.warning("reviewer feedback split failed", exc_info=True)
            if fb.strip():
                issues = [fb.strip()[:200]]
    if not tasks:
        if "空任务" not in issues:
            issues.append("空任务")
        score = 0
    else:
        try:
            score = max(0, 100 - 20 * len(issues))
        except Exception:
            logger.warning("reviewer score calc failed", exc_info=True)
            score = 0 if issues else 100
    review = {"score": int(score), "issues": issues}
    thought = f"思考：reviewer 复核 {len(tasks)} 任务，critic反馈{'无' if not fb else '有'}，评分{int(score)}，问题{len(issues)}个"
    if prev:
        thought = prev + " | " + thought
    return {"_review": review, "_thought": thought}


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
        # 可执行顺序：优先从 graphDeps 推导标题全序，供 planner reorder 按指定顺序重排；
        # 无图谱时回退 True（planner 按优先级兜底），保持旧行为兼容。
        try:
            _gdeps = state.get("graphDeps") or []
            _order: list[str] = []
            if isinstance(_gdeps, list) and _gdeps:
                for _d in _gdeps[:8]:
                    if isinstance(_d, dict):
                        _f = str(_d.get("from", "")).strip()
                        _t = str(_d.get("to", "")).strip()
                        if _f and _f not in _order:
                            _order.append(_f)
                        if _t and _t not in _order:
                            _order.append(_t)
            patch["reorder"] = {"order": _order} if _order else True
        except Exception:
            logger.warning("reflector reorder order build failed", exc_info=True)
            patch["reorder"] = True
    if "熔断" in fb:
        patch["truncate"] = True
    # add_buffer 默认缓冲分钟（planner 纯函数缺省 15min，此处显式声明便于追溯）
    if patch.get("add_buffer") is True:
        patch["buffer_minutes"] = 15
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
    # P2 第3轮仅轻patch：rewrites>=2 时剥离重键，杜绝跨周搬移（保留只读视图以便追溯）
    try:
        _rw_ref = int(state.get("rewrites", 0) or 0)
    except (TypeError, ValueError):
        _rw_ref = 0
    if _rw_ref >= 2:
        for _hk in ("reallocate", "reduce_load", "truncate", "reduce_daily_hours", "reduce_weekly", "next_week_hours", "instructions", "suggested_hours_per_day"):
            try:
                patch.pop(_hk, None)
            except Exception:
                pass
        # 轻轮无轻动作时给 keep，避免 views-only 触发截断兜底移周
        if "reorder" not in patch and "add_buffer" not in patch and "keep" not in patch:
            # 若已有只读视图则保留视图+keep（keep 短路，视图仅追溯）
            patch["keep"] = True
    # 若无patch，给默认轻量
    if not patch:
        patch["keep"] = True
    # P2 元信息：patch_id（幂等键）+ auto_execute + retry_policy（未知键由 planner 纯函数忽略）
    try:
        import uuid as _uuid_mod

        _pid0 = patch.get("patch_id")
        if not (isinstance(_pid0, str) and _pid0):
            patch["patch_id"] = _uuid_mod.uuid4().hex[:16]
    except Exception:
        try:
            patch.setdefault("patch_id", "p2-fallback")
        except Exception:
            pass
    try:
        _heavy_keys = {"reallocate", "reduce_load", "truncate", "reduce_daily_hours", "reduce_weekly"}
        patch["auto_execute"] = not any(k in patch for k in _heavy_keys)
    except Exception:
        pass
    try:
        patch["retry_policy"] = {"max_retries": 0 if _rw_ref >= 2 else 1, "backoff_ms": 200}
    except Exception:
        pass
    thought = f"思考：reflector 基于反馈 '{fb[:30]}' 生成可执行补丁 {patch}"
    if prev:
        thought = prev + " | " + thought
    return {"_patch": patch, "_thought": thought}


def should_replan(state: PlanState) -> str:
    # 落库移到 critic 通过之后：仅校验通过才走 executor 落库；
    # 熔断/重写耗尽仍有反馈时直达 reviewer→mentor（不落库，plans.py 回退直插兜底）。
    # P3：返回仍为 mentor/replan/executor（兼容旧测试），build_graph 将 mentor 路由到 reviewer。
    # S10：followUp 由 reflector->planner 条件边独立承载（见 should_followup），此处不动防循环。
    if state.get("terminate"):
        return "mentor"
    fb = state.get("critic_feedback", "")
    try:
        rewrites = int(state.get("rewrites", 0) or 0)
    except (TypeError, ValueError):
        rewrites = 0
    # 越界钳制：rewrites 异常偏大时直接 mentor，避免死循环
    if rewrites < 0:
        rewrites = 0
    # P2：放宽到 <3，第3轮仅轻patch（见 planner/reflector），重任务不再移周
    if fb and rewrites < 3:
        return "replan"
    if fb:
        return "mentor"
    return "executor"


def should_followup(state: PlanStateEx) -> str:
    """S10 followUp 条件边：reflector->planner 复用 thread_id（Pi agent-loop 外层 followUp 启示）。

    - state 含 _followup/followup_msg 非空且 rewrites<3 时回 planner 续跑一轮；
    - 默认回 end（旧行为零变化，兼容现有 completed 断言）。
    """
    try:
        msg = state.get("_followup") or state.get("followup_msg") or ""
        if isinstance(msg, str) and msg.strip():
            try:
                rw = int(state.get("rewrites", 0) or 0)
            except (TypeError, ValueError):
                rw = 0
            if rw < 3:
                return "planner"
    except Exception:
        pass
    return "end"


def build_graph(checkpointer=None):
    """构建 7 节点图（planner_with_count计入则7，逻辑6+reviewer=7），支持 Pi 风格 checkpoint（executor 落库在 critic 通过之后，reviewer 常驻 mentor 前）"""
    g = StateGraph(PlanStateEx)
    g.add_node("planner", planner_with_count)
    g.add_node("researcher", researcher_node)
    g.add_node("executor", executor_node)
    g.add_node("critic", critic_node)
    g.add_node("reviewer", reviewer_node)
    g.add_node("mentor", mentor_node)
    g.add_node("reflector", reflector_node)
    g.set_entry_point("planner")
    g.add_edge("planner", "researcher")
    g.add_edge("researcher", "critic")
    # P3：mentor 路由经 reviewer（critic→reviewer→mentor），executor 仍仅 critic 通过后走（critic→executor→reviewer→mentor），保持落库语义
    g.add_conditional_edges("critic", should_replan, {"replan": "planner", "mentor": "reviewer", "executor": "executor"})
    g.add_edge("executor", "reviewer")
    g.add_edge("reviewer", "mentor")
    g.add_edge("mentor", "reflector")
    # S10 followUp 边：reflector 经 should_followup 复用 thread_id 回 planner（默认 end，旧流零变化）
    g.add_conditional_edges("reflector", should_followup, {"planner": "planner", "end": END})
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
