"""System Agent 单点对外智能体 - 封装7子Agent协作，对外单点 studying-planner.

对标 hermes/pi 的单Agent抽象：外部只需调 SystemAgent.ainvoke(goal,prefs) 或 CLI studying / POST /plans
内部即 LangGraph 7节点 graph.py:build_graph
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.tools.registry import list_tools_detailed

logger = logging.getLogger(__name__)


class SystemAgent:
    """对外单一智能体，内部多智能体协作."""

    name = "studying-planner"
    description = "多智能体协作的学习规划智能体 - 内部7子Agent(Planner/Researcher/Executor/Critic/Reviewer/Mentor/Reflector)"
    version = "0.4.0"

    @staticmethod
    def get_manifest() -> dict[str, Any]:
        """供 GET /agent/manifest 返回，供外部 hermes/pi 发现."""
        return {
            "name": SystemAgent.name,
            "description": SystemAgent.description,
            "version": SystemAgent.version,
            "tools": list_tools_detailed(),
            "entry": "POST /api/v1/plans",
            "stream": "GET /api/v1/plans/stream?trace_id={trace_id}",
            "graph": "GET /api/v1/plans/{trace_id}/graph",
            "inspector": "GET /api/v1/plans/{trace_id}/inspector",
            "cli": "studying (--help | plan | trace | stream)",
            "sub_agents": ["planner", "researcher", "executor", "critic", "reviewer", "mentor", "reflector"],
        }

    @staticmethod
    def get_tools_manifest() -> list[dict[str, Any]]:
        """返回详细工具清单 label/description/schema 供文档."""
        return list_tools_detailed()

    @staticmethod
    async def plan_project(
        goal_id: int | dict[str, Any],
        hours_per_day: int | dict[str, Any] | None = None,
        user_id: int = 1,
        session=None,
        trace_id: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """W12-14 项目规划（策略自演进（基于反思补丁））：接收 goal_id, hours_per_day，内部 ainvoke 后将 patch 写入 reflection_report.next_plan_patch 按周 Wxx.

        策略自演进（基于反思补丁）而非权重自进化：通过 Reflector 生成的 next_plan_patch 按周 Wxx 持久化到 reflection_report，供下周 Planner 合并，实现策略层自演进闭环。
        兼容旧签名 plan_project(goal: dict, prefs: dict)；新签名 plan_project(goal_id: int, hours_per_day: int)。
        对应 00-管理/00-项目总计划书.md:35 W12-14 项目规划 + 02-系统架构设计.md:4.0 System Agent 单点，
        将 Reflector 生成的 _patch 持久化到 reflection_report.next_plan_patch 按周 Wxx 供下周 Planner 合并消费。
        """
        # --- 兼容层：区分旧签名(goal:dict)与新签名(goal_id:int, hours_per_day:int) ---
        _goal: dict[str, Any] | None = None
        _prefs: dict[str, Any] | None = None
        if isinstance(goal_id, dict):
            # 旧签名：plan_project(goal: dict, prefs: dict) 或 plan_project(goal, prefs)
            _goal = goal_id
            if isinstance(hours_per_day, dict):
                _prefs = hours_per_day
            elif isinstance(hours_per_day, int):
                _prefs = {"hours_per_day": hours_per_day}
            elif hours_per_day is None:
                _prefs = kwargs.get("prefs") or kwargs.get("preferences") or kwargs.get("pref") or {"hours_per_day": 2}
            else:
                _prefs = {"hours_per_day": 2}
            if kwargs.get("goal") and isinstance(kwargs["goal"], dict):
                _goal = kwargs["goal"]  # type: ignore
            if kwargs.get("prefs") and isinstance(kwargs["prefs"], dict):
                _prefs = kwargs["prefs"]  # type: ignore
            if kwargs.get("preferences") and isinstance(kwargs["preferences"], dict):
                _prefs = kwargs["preferences"]  # type: ignore
        else:
            # 新签名：plan_project(goal_id: int, hours_per_day: int|dict)
            gid = goal_id
            if isinstance(hours_per_day, dict):
                _prefs = hours_per_day
            elif isinstance(hours_per_day, int):
                _prefs = {"hours_per_day": hours_per_day}
            elif hours_per_day is None:
                _prefs = kwargs.get("prefs") or kwargs.get("preferences") or kwargs.get("pref") or {"hours_per_day": 2}
                if isinstance(_prefs, int):
                    _prefs = {"hours_per_day": _prefs}
                if not isinstance(_prefs, dict):
                    _prefs = {"hours_per_day": 2}
            else:
                _prefs = {"hours_per_day": 2}
            # kwargs 显式 goal 优先
            if kwargs.get("goal") and isinstance(kwargs["goal"], dict):
                _goal = kwargs["goal"]  # type: ignore
            elif session is not None and isinstance(gid, int):
                try:
                    from app.models.goal import LearningGoal

                    _g = session.get(LearningGoal, int(gid))
                    if _g:
                        _goal = {
                            "id": _g.id,
                            "title": _g.title,
                            "deadline": _g.deadline.isoformat() if hasattr(_g.deadline, "isoformat") else str(_g.deadline),
                            "description": _g.description,
                            "subject": _g.subject,
                        }
                except Exception:
                    logger.warning("goal load from db failed", exc_info=True)
                    _goal = None
            if _goal is None:
                try:
                    gid_int = int(gid) if isinstance(gid, int) else 1
                except (TypeError, ValueError):
                    gid_int = 1
                _goal = {
                    "id": gid_int,
                    "title": kwargs.get("title") or f"Goal {gid_int}",
                    "deadline": kwargs.get("deadline") or __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    "description": kwargs.get("description") or "",
                    "subject": kwargs.get("subject"),
                }
        prefs = _prefs or {"hours_per_day": 2}
        goal = _goal  # type: ignore
        # --- 下周 Planner 合并：读取上一周 reflection_report.next_plan_patch 并合并到 prefs（02-架构4.0） ---
        try:
            if session is not None:
                from sqlmodel import select

                from app.models.reflection import ReflectionReport

                latest = None
                try:
                    latest = session.exec(
                        select(ReflectionReport).where(ReflectionReport.user_id == user_id).order_by(ReflectionReport.week.desc())  # type: ignore
                    ).first()
                except Exception:
                    logger.warning("reflection query (ordered) failed, fallback unordered", exc_info=True)
                    try:
                        candidates = session.exec(select(ReflectionReport).where(ReflectionReport.user_id == user_id)).all()  # type: ignore
                        if candidates:
                            latest = sorted(candidates, key=lambda r: getattr(r, "week", ""), reverse=True)[0]
                    except Exception:
                        logger.warning("reflection fallback select failed", exc_info=True)
                        latest = None
                if latest is not None and isinstance(getattr(latest, "next_plan_patch", None), dict) and latest.next_plan_patch:
                    patch_prev: dict[str, Any] = latest.next_plan_patch  # type: ignore
                    try:
                        if "suggested_hours_per_day" in patch_prev:
                            try:
                                sug = int(patch_prev["suggested_hours_per_day"])
                                if 1 <= sug <= 8:
                                    prefs = dict(prefs)
                                    prefs["hours_per_day"] = sug
                                    prefs["_merged_from_patch"] = True
                                    prefs["_patch_week"] = getattr(latest, "week", "")
                            except (TypeError, ValueError):
                                logger.debug("suggested_hours_per_day merge skipped", exc_info=True)
                        if patch_prev.get("reduce_load") or patch_prev.get("reduce_daily_hours") or patch_prev.get("reduce_weekly"):
                            try:
                                cur = int(prefs.get("hours_per_day", 2))
                                if cur > 1 and "suggested_hours_per_day" not in patch_prev:
                                    prefs = dict(prefs)
                                    prefs["hours_per_day"] = max(1, cur - 1)
                                    prefs["_merged_from_patch"] = True
                                    prefs["_patch_reason"] = "reduce_load"
                            except (TypeError, ValueError):
                                logger.debug("reduce_load merge skipped", exc_info=True)
                        for k in ("prefer_weekday", "focus_subject", "break_down", "add_buffer", "reallocate", "week_load", "next_week_hours"):
                            if k in patch_prev and k not in prefs:
                                prefs = dict(prefs)
                                prefs[k] = patch_prev[k]
                    except Exception:
                        logger.warning("last week patch merge failed (plan_project)", exc_info=True)
        except Exception:
            logger.warning("last week patch read failed (plan_project)", exc_info=True)
        final = await SystemAgent.ainvoke(goal, prefs, trace_id=trace_id, session=session, user_id=user_id)
        # 提取 patch
        patch: dict[str, Any] = {}
        try:
            if isinstance(final, dict):
                patch = final.get("_patch") or final.get("patch") or {}
                if not isinstance(patch, dict):
                    patch = {"value": patch}
        except Exception:
            logger.warning("patch extraction failed", exc_info=True)
            patch = {}
        # 写入 reflection_report.next_plan_patch（若提供 session）
        if session is not None and isinstance(patch, dict):
            try:
                from datetime import datetime, timezone

                from sqlmodel import select

                from app.models.reflection import ReflectionReport

                # 计算当前 ISO 周
                now = datetime.now(timezone.utc)
                try:
                    from app.scheduler.reflector import _week_str

                    week = _week_str(now)
                except Exception:
                    logger.warning("_week_str failed, fallback iso calc", exc_info=True)
                    iso = now.isocalendar()
                    week = f"{iso[0]}-W{iso[1]:02d}"
                # 优先更新本周记录，若不存在则新建空报告占位
                existing = None
                try:
                    existing = session.exec(
                        select(ReflectionReport).where(ReflectionReport.user_id == user_id, ReflectionReport.week == week)
                    ).first()
                except Exception:
                    logger.warning("existing reflection query failed", exc_info=True)
                    existing = None
                if existing is not None:
                    # 直接覆盖为最新 patch（W12-14 项目规划语义：下周约束以最新 Reflector 为准）
                    existing.next_plan_patch = patch
                    session.add(existing)
                    session.commit()
                    try:
                        session.refresh(existing)
                    except Exception:
                        logger.warning("session refresh(existing) failed", exc_info=True)
                else:
                    # 若本周无报告，创建最小可用记录，analysis 占位
                    try:
                        report = ReflectionReport(
                            user_id=user_id,
                            week=week,
                            completion_rate=0,
                            delay_rate=0,
                            avg_load=0,
                            analysis=f"plan_project auto patch trace={final.get('trace_id', trace_id) if isinstance(final, dict) else trace_id}",
                            next_plan_patch=patch,
                        )
                        session.add(report)
                        session.commit()
                        try:
                            session.refresh(report)
                        except Exception:
                            logger.warning("session refresh(report) failed", exc_info=True)
                    except Exception:
                        logger.warning("reflection report create failed, rollback", exc_info=True)
                        try:
                            session.rollback()
                        except Exception:
                            logger.warning("rollback failed", exc_info=True)
            except Exception:
                # 静默失败，不影响主流程
                logger.warning("reflection report write failed, rollback", exc_info=True)
                try:
                    session.rollback()
                except Exception:
                    logger.warning("rollback failed (outer)", exc_info=True)
        return final

    @staticmethod
    async def ainvoke(
        goal: dict[str, Any],
        preferences: dict[str, Any] | None = None,
        trace_id: str | None = None,
        session=None,
        user_id: int = 1,
    ) -> dict[str, Any]:
        """单点 ainvoke，内部走 LangGraph 7节点."""
        preferences = preferences or {"hours_per_day": 2}
        # Planner 合并：若 session 存在且 prefs 未标记已合并，则尝试合并上周 next_plan_patch（02-架构4.0）
        if session is not None and not preferences.get("_merged_from_patch"):
            try:
                from sqlmodel import select

                from app.models.reflection import ReflectionReport

                latest = None
                try:
                    latest = session.exec(
                        select(ReflectionReport).where(ReflectionReport.user_id == user_id).order_by(ReflectionReport.week.desc())  # type: ignore
                    ).first()
                except Exception:
                    logger.warning("reflection query (ordered) failed, fallback unordered", exc_info=True)
                    try:
                        candidates = session.exec(select(ReflectionReport).where(ReflectionReport.user_id == user_id)).all()  # type: ignore
                        if candidates:
                            latest = sorted(candidates, key=lambda r: getattr(r, "week", ""), reverse=True)[0]
                    except Exception:
                        logger.warning("reflection fallback select failed", exc_info=True)
                        latest = None
                if latest is not None and isinstance(getattr(latest, "next_plan_patch", None), dict) and latest.next_plan_patch:
                    patch_prev = latest.next_plan_patch  # type: ignore
                    try:
                        if "suggested_hours_per_day" in patch_prev:
                            try:
                                sug = int(patch_prev["suggested_hours_per_day"])
                                if 1 <= sug <= 8:
                                    preferences = dict(preferences)
                                    preferences["hours_per_day"] = sug
                                    preferences["_merged_from_patch"] = True
                                    preferences["_patch_week"] = getattr(latest, "week", "")
                            except (TypeError, ValueError):
                                logger.debug("suggested_hours_per_day merge skipped (ainvoke)", exc_info=True)
                        if patch_prev.get("reduce_load") or patch_prev.get("reduce_daily_hours") or patch_prev.get("reduce_weekly"):
                            try:
                                cur = int(preferences.get("hours_per_day", 2))
                                if cur > 1 and "suggested_hours_per_day" not in patch_prev:
                                    preferences = dict(preferences)
                                    preferences["hours_per_day"] = max(1, cur - 1)
                                    preferences["_merged_from_patch"] = True
                                    preferences["_patch_reason"] = "reduce_load"
                            except (TypeError, ValueError):
                                logger.debug("reduce_load merge skipped (ainvoke)", exc_info=True)
                        for k in ("prefer_weekday", "focus_subject", "break_down", "add_buffer", "reallocate", "week_load", "next_week_hours"):
                            if k in patch_prev and k not in preferences:
                                preferences = dict(preferences)
                                preferences[k] = patch_prev[k]
                    except Exception:
                        logger.warning("last week patch merge failed (ainvoke)", exc_info=True)
            except Exception:
                logger.warning("last week patch read failed (ainvoke)", exc_info=True)
        trace_id = trace_id or __import__("uuid").uuid4().hex
        # 复用 plans.py 的多Agent逻辑需要 session/user_id，此处提供轻量直调 graph
        from app.agents.graph import graph as multi_graph

        # 并行检索（与 plans.py:191 保持一致，异步走真实 embedding）
        try:
            from app.services.memory import asearch_memory

            mems = await asearch_memory(session, user_id, query=goal.get("title", ""), top_k=5, type_="memory") if session is not None else []
        except Exception:
            logger.warning("memory prefetch failed", exc_info=True)
            mems = []
        try:
            from app.services.memory import asearch_memory as _as2

            vecs = await _as2(session, user_id, query=goal.get("title", ""), top_k=10, type_="knowledge") if session is not None else []
        except Exception:
            logger.warning("knowledge prefetch failed", exc_info=True)
            vecs = []
        try:
            from app.graph.neo import search_prereqs

            graph_deps = search_prereqs(goal.get("title", "")) or []
        except Exception:
            logger.warning("graph prefetch failed", exc_info=True)
            graph_deps = []

        # 注意：不将 SQLModel Session 放入 checkpoint 状态（msgpack 不可序列化），仅在调用前预取 memory/vector
        init_state = {
            "goal": goal,
            "preferences": preferences,
            "trace_id": trace_id,
            "memory": mems,
            "graphDeps": graph_deps,
            "vectorDeps": vecs,
            "milestones": [],
            "tasks": [],
            "critic_feedback": "",
            "mentor_msg": "",
            "rewrites": 0,
            "user_id": user_id,
        }
        try:
            final = await multi_graph.ainvoke(init_state, config={"configurable": {"thread_id": trace_id}})
        except TypeError:
            final = await multi_graph.ainvoke(init_state)
        # 补回 trace_id/session 上下文供外部使用（不入 checkpoint）
        try:
            if isinstance(final, dict) and "trace_id" not in final:
                final["trace_id"] = trace_id
        except Exception:
            logger.warning("trace_id attach failed", exc_info=True)
        return final

    @staticmethod
    def invoke(*args, **kwargs) -> dict[str, Any]:
        """同步 wrapper，供非 async 调用."""
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(SystemAgent.ainvoke(*args, **kwargs))
        # 已在事件循环中则用线程
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(lambda: asyncio.run(SystemAgent.ainvoke(*args, **kwargs)))
            return fut.result(timeout=30)


# 单例
system_agent = SystemAgent()
