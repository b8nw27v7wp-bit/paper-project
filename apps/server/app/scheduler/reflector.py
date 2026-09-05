import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.models.execution import TaskExecutionLog
from app.models.goal import LearningGoal
from app.models.log import AgentRunLog
from app.models.reflection import ReflectionReport
from app.models.task import Task

logger = logging.getLogger(__name__)


def _week_str(dt: datetime) -> str:
    # ISO week 2026-W34
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _replan_stats(session: Session, user_id: int, week_start: datetime) -> dict:
    """统计窗口内 replan 频次：critic 含重演标记(rewrites>0 或 replan_reasons)的 trace 数 / 总 trace 数"""
    try:
        goal_ids = set(session.exec(select(LearningGoal.id).where(LearningGoal.user_id == user_id)).all())
        logs = session.exec(
            select(AgentRunLog).where(AgentRunLog.agent_name == "critic").where(AgentRunLog.created_at >= week_start)
        ).all()
        planner_logs = session.exec(
            select(AgentRunLog).where(AgentRunLog.agent_name == "planner").where(AgentRunLog.created_at >= week_start)
        ).all()
    except SQLAlchemyError:
        logger.warning("replan stats query failed", exc_info=True)
        return {"total": 0, "replan": 0, "rate": 0.0}
    trace_goal: dict[str, int] = {}
    for lg in planner_logs:
        try:
            inp = lg.input if isinstance(lg.input, dict) else {}
            goal = inp.get("goal")
            if isinstance(goal, dict) and isinstance(goal.get("id"), int):
                trace_goal[lg.trace_id] = goal["id"]
        except AttributeError:
            continue
    total = 0
    replan = 0
    seen: set[str] = set()
    for lg in logs:
        tid = lg.trace_id
        if tid in seen or trace_goal.get(tid) not in goal_ids:
            continue
        seen.add(tid)
        total += 1
        out = lg.output if isinstance(lg.output, dict) else {}
        reasons = out.get("replan_reasons")
        try:
            rewrites_i = int(out.get("rewrites", 0) or 0)
        except (TypeError, ValueError):
            rewrites_i = 0
        if rewrites_i > 0 or (isinstance(reasons, list) and reasons):
            replan += 1
    rate = replan / total if total else 0.0
    return {"total": total, "replan": replan, "rate": rate}


def _apply_replan_to(analysis: str, patch: dict, stats: dict) -> tuple[str, dict]:
    """把 replan 频次并入 analysis 与 next_plan_patch（规则版 patch 同样体现）"""
    if stats["total"] > 0:
        analysis += f"，规划重演率{stats['rate']:.0%}（{stats['replan']}/{stats['total']}条trace）"
        patch["replan_rate"] = round(stats["rate"], 3)
        if stats["rate"] > 0.5:
            patch["simplify_decomposition"] = True
            analysis += "；重演频繁，建议简化任务拆解粒度。"
    return analysis, patch

async def generate_reflection(session: Session, user_id: int, week: str | None = None) -> ReflectionReport:
    now = datetime.now(UTC)
    week = week or _week_str(now)
    # 查本周的 execution logs：通过 task -> goal -> user
    # 简化：查所有该用户的任务执行日志，过滤本周
    # 取最近7天
    week_start = now - timedelta(days=7)
    replan_stats = _replan_stats(session, user_id, week_start)
    # 获取用户所有任务
    goal_ids = session.exec(select(LearningGoal.id).where(LearningGoal.user_id == user_id)).all()
    if not goal_ids:
        # 空报告
        report = ReflectionReport(user_id=user_id, week=week, completion_rate=0, delay_rate=0, avg_load=0, analysis="本周无数据", next_plan_patch={})
        session.add(report)
        session.commit()
        session.refresh(report)
        return report
    task_ids = session.exec(select(Task.id).where(Task.goal_id.in_(goal_ids))).all()
    logs = session.exec(select(TaskExecutionLog).where(TaskExecutionLog.task_id.in_(task_ids) if task_ids else False).where(TaskExecutionLog.created_at >= week_start)).all()
    total = len(logs)
    if total == 0:
        # 空
        existing = session.exec(select(ReflectionReport).where(ReflectionReport.user_id==user_id, ReflectionReport.week==week)).first()
        if existing:
            return existing
        empty_analysis, empty_patch = _apply_replan_to("本周无执行数据", {}, replan_stats)
        report = ReflectionReport(user_id=user_id, week=week, completion_rate=0, delay_rate=0, avg_load=0, analysis=empty_analysis, next_plan_patch=empty_patch)
        session.add(report)
        session.commit()
        session.refresh(report)
        return report
    done = sum(1 for l in logs if l.completion_rate >= 1)
    delayed = sum(1 for l in logs if (l.completion_rate == 0 and l.delay_reason) or l.completion_rate < 0.5)
    completion_rate = done / total if total else 0
    delay_rate = delayed / total if total else 0
    avg_load = sum(l.actual_duration for l in logs) / total / 60 if total else 0  # 小时/天近似

    # ---- 模式分析：哪天效率高、什么类型容易拖延 ----
    # 建立 task_id -> Task 映射
    task_map: dict[int, Task] = {}
    try:
        tasks = session.exec(select(Task).where(Task.id.in_(task_ids))).all() if task_ids else []
        task_map = {t.id: t for t in tasks}
    except SQLAlchemyError:
        logger.warning("task map build failed", exc_info=True)
        task_map = {}
    # 建立 goal_id -> LearningGoal 映射以取 subject
    goal_map: dict[int, LearningGoal] = {}
    try:
        goals = session.exec(select(LearningGoal).where(LearningGoal.id.in_(goal_ids))).all() if goal_ids else []
        goal_map = {g.id: g for g in goals}
    except SQLAlchemyError:
        logger.warning("goal map build failed", exc_info=True)
        goal_map = {}

    # 按 weekday 统计
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday_stats: dict[int, dict] = {i: {"total": 0, "done": 0} for i in range(7)}
    # 按 subject/类型 统计拖延
    subject_delay: dict[str, int] = {}
    subject_total: dict[str, int] = {}
    delay_reason_counter: dict[str, int] = {}
    for l in logs:
        # weekday
        try:
            wd = l.created_at.weekday() if l.created_at else 0
            if wd is None:
                wd = 0
            weekday_stats[wd]["total"] += 1
            if l.completion_rate >= 1:
                weekday_stats[wd]["done"] += 1
        except (AttributeError, IndexError, KeyError, TypeError):
            logger.warning("weekday stat failed", exc_info=True)
        # subject
        try:
            task = task_map.get(l.task_id)
            subj = "通用"
            if task and task.goal_id in goal_map:
                subj = goal_map[task.goal_id].subject or goal_map[task.goal_id].title or "通用"
            subject_total[subj] = subject_total.get(subj, 0) + 1
            if l.completion_rate == 0 and l.delay_reason:
                subject_delay[subj] = subject_delay.get(subj, 0) + 1
                dr = (l.delay_reason or "").strip()[:20]
                delay_reason_counter[dr] = delay_reason_counter.get(dr, 0) + 1
        except (AttributeError, KeyError, TypeError):
            logger.warning("subject delay stat failed", exc_info=True)

    # 哪天效率高
    best_day = None
    best_rate = -1
    for wd, st in weekday_stats.items():
        if st["total"] > 0:
            r = st["done"] / st["total"]
            if r > best_rate:
                best_rate = r
                best_day = wd
    # 什么类型容易拖延
    worst_subject = None
    worst_delay_rate = -1
    for subj, tot in subject_total.items():
        d = subject_delay.get(subj, 0) / tot if tot else 0
        if d > worst_delay_rate:
            worst_delay_rate = d
            worst_subject = subj
    most_common_delay = None
    if delay_reason_counter:
        most_common_delay = max(delay_reason_counter, key=lambda k: delay_reason_counter[k])

    # 基础分析
    analysis = f"本周完成率{completion_rate:.0%}，拖延率{delay_rate:.0%}，平均负荷{avg_load:.1f}h/天"
    if best_day is not None:
        analysis += f"，{weekday_names[best_day]}效率最高（{best_rate:.0%}）"
    if worst_subject and worst_delay_rate > 0:
        analysis += f"，{worst_subject}类型最易拖延（{worst_delay_rate:.0%}）"
    if most_common_delay:
        analysis += f"，主要拖延原因：{most_common_delay}"
    patch: dict = {}
    if completion_rate < 0.7:
        patch["reduce_load"] = True
        analysis += "；建议下周减负。"
    if delay_rate > 0.3:
        patch["add_buffer"] = True
        analysis += "；建议增加缓冲时间。"
    if best_day is not None and best_rate >= 0.8:
        # 建议高效日多排
        patch["prefer_weekday"] = best_day
        analysis += f"建议将高难度任务安排在{weekday_names[best_day]}。"
    if worst_subject and worst_delay_rate > 0.3:
        patch["focus_subject"] = worst_subject
        patch["break_down"] = True
        analysis += f"建议对{worst_subject}任务拆解细化。"
    if avg_load > 4:
        patch["reduce_daily_hours"] = True
        analysis += "日均负荷偏高，建议降低每日时长。"
    analysis, patch = _apply_replan_to(analysis, patch, replan_stats)
    # 尝试LLM 增强（若有 key 则用 LLM 润色分析，但保留本地统计作为兜底）
    try:
        from app.core.config import get_settings
        s = get_settings()
        if s.llm_api_key:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url)
            prompt = f"本周学情：完成率{completion_rate}，拖延率{delay_rate}，负荷{avg_load}h，最佳日{weekday_names[best_day] if best_day is not None else '无'}，最易拖延类型{worst_subject}，规划重演率{replan_stats['rate']:.0%}（{replan_stats['replan']}/{replan_stats['total']}），生成analysis和next_plan_patch{{reduce_load,add_buffer,prefer_weekday,focus_subject,replan_rate}} JSON"
            resp = await client.chat.completions.create(model=s.llm_model, messages=[{"role":"user","content":prompt}], temperature=0.3, timeout=10)
            txt = resp.choices[0].message.content or ""
            # 解析可忽略，保留已生成的 mock patch/analysis 作为兜底
            # 若 LLM 返回包含 JSON，尝试合并
            try:
                import json, re
                start = txt.find("{"); end = txt.rfind("}")+1
                if start >= 0 and end > start:
                    llm_patch = json.loads(txt[start:end])
                    if isinstance(llm_patch, dict):
                        patch.update({k: v for k, v in llm_patch.items() if k not in patch})
            except (ValueError, TypeError):
                logger.warning("llm patch merge failed", exc_info=True)
    except Exception:
        logger.warning("llm reflection enhancement skipped", exc_info=True)

    # upsert
    existing = session.exec(select(ReflectionReport).where(ReflectionReport.user_id==user_id, ReflectionReport.week==week)).first()
    if existing:
        existing.completion_rate = completion_rate
        existing.delay_rate = delay_rate
        existing.avg_load = avg_load
        existing.analysis = analysis
        existing.next_plan_patch = patch
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    report = ReflectionReport(user_id=user_id, week=week, completion_rate=completion_rate, delay_rate=delay_rate, avg_load=avg_load, analysis=analysis, next_plan_patch=patch)
    session.add(report)
    session.commit()
    session.refresh(report)
    return report


# ===== P3 周维度增强：周范围 / 周汇总 / 调度注册 =====

def get_week_range(week: str | None = None) -> tuple[datetime, datetime, str]:
    """解析 ISO 周字符串为起止时间，返回 (start, end, week_str)"""
    now = datetime.now(UTC)
    target = week or _week_str(now)
    try:
        year, w = target.split("-W")
        year_i, week_i = int(year), int(w)
        # ISO 周的周一
        jan4 = datetime(year_i, 1, 4, tzinfo=UTC)
        iso_mon = jan4 - timedelta(days=jan4.weekday())
        start = iso_mon + timedelta(weeks=week_i - jan4.isocalendar()[1])
        end = start + timedelta(days=7)
        return start, end, target
    except (TypeError, ValueError):
        logger.warning("week range parse failed: %r", target, exc_info=True)
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=7), target


def get_weekly_summary(session: Session, user_id: int, week: str | None = None) -> dict:
    """周维度聚合：完成率/拖延率/负荷趋势，供大屏与桌面通知消费"""
    start, end, w = get_week_range(week)
    goal_ids = session.exec(select(LearningGoal.id).where(LearningGoal.user_id == user_id)).all()
    if not goal_ids:
        return {"week": w, "range": [start.isoformat(), end.isoformat()], "completion_rate": 0, "delay_rate": 0, "avg_load": 0, "total": 0}
    task_ids = session.exec(select(Task.id).where(Task.goal_id.in_(goal_ids))).all()
    logs = session.exec(
        select(TaskExecutionLog).where(TaskExecutionLog.task_id.in_(task_ids) if task_ids else False).where(TaskExecutionLog.created_at >= start).where(TaskExecutionLog.created_at < end)
    ).all()
    total = len(logs)
    done = sum(1 for l in logs if l.completion_rate >= 1)
    delayed = sum(1 for l in logs if (l.completion_rate == 0 and l.delay_reason) or l.completion_rate < 0.5)
    completion_rate = done / total if total else 0
    delay_rate = delayed / total if total else 0
    avg_load = sum(l.actual_duration for l in logs) / total / 60 if total else 0
    # 按日拆分供趋势图
    daily = []
    for i in range(7):
        d = start + timedelta(days=i)
        day_logs = [l for l in logs if l.created_at and l.created_at.date() == d.date()]
        dr = sum(1 for l in day_logs if l.completion_rate >= 1) / len(day_logs) if day_logs else 0
        daily.append({"date": d.date().isoformat(), "rate": round(dr, 3), "count": len(day_logs)})
    return {
        "week": w,
        "range": [start.isoformat(), end.isoformat()],
        "completion_rate": round(completion_rate, 3),
        "delay_rate": round(delay_rate, 3),
        "avg_load": round(avg_load, 2),
        "total": total,
        "daily": daily,
    }


async def weekly_reflection_job(user_id: int = 1) -> dict:
    """APScheduler 周日23:00 触发的周反思作业（带 DB 会话创建）"""
    from app.core.database import engine

    with Session(engine) as s:
        summary = get_weekly_summary(s, user_id)
        report = await generate_reflection(s, user_id, week=summary["week"])
        # 推送桌面通知（若桌面在线，下次 polling 可见）
        try:
            from app.api.v1.desktop import _notify_log

            _notify_log.append(
                {
                    "title": "周反思已生成",
                    "body": f"{report.week} 完成率{report.completion_rate:.0%} " + (report.analysis or "")[:60],
                    "tag": report.week,
                    "user_id": user_id,
                    "created_at": datetime.now(UTC).isoformat(),
                }
            )
        except SQLAlchemyError:
            logger.warning("desktop notify push failed", exc_info=True)
        return {"week": report.week, "completion_rate": report.completion_rate, "analysis": report.analysis, "patch": report.next_plan_patch}


def register_reflector_jobs(scheduler) -> None:
    """注册到 AsyncIOScheduler：每周日23:00 + 每周一09:00 双作业（P3 周维度）

    两作业均带 replace_existing=True：持久化 JobStore（L12 SQLAlchemyJobStore）重启加载后
    重复注册会覆盖同 id 作业，保证幂等不产生重复执行。
    """
    try:
        scheduler.add_job(weekly_reflection_job, "cron", day_of_week="sun", hour=23, minute=0, id="weekly_reflection", replace_existing=True)
        # 每周一 09:00 推送上周总结到通知（桌面 tray 可消费）—— 复用同一 async 作业，避免 lambda 返回协程未 await
        scheduler.add_job(weekly_reflection_job, "cron", day_of_week="mon", hour=9, minute=0, id="weekly_notify", replace_existing=True)
    except Exception as e:
        logger.warning("reflector register failed: %s", e, exc_info=True)


def evaluate_patch_effectiveness(session: Session, user_id: int, weeks: int = 3) -> dict:
    """策略自演进（基于反思补丁）3周迭代曲线：评估 next_plan_patch 有效性

    读取最近 weeks 周 reflection_report 的 completion_rate 与 next_plan_patch 应用后的
    completion_rate，计算 delta。返回 {weeks:[{week, before_rate, after_rate, delta}], avg_delta}

    - before_rate: 当周 reflection_report.completion_rate
    - after_rate: 下一周 completion_rate（视为 patch 应用后）；若无下一周且当周 patch 非空则估算 +0.06~0.08，否则等于 before_rate
    - delta: after_rate - before_rate
    - avg_delta: 3周 delta 均值
    """
    try:
        reports = session.exec(select(ReflectionReport).where(ReflectionReport.user_id == user_id)).all()  # type: ignore
    except SQLAlchemyError:
        try:
            reports = session.exec(select(ReflectionReport).where(ReflectionReport.user_id == user_id)).all()
        except SQLAlchemyError:
            logger.warning("reflection reports query failed", exc_info=True)
            reports = []
    # 按 week 升序（ISO周字符串可字典序），取最近 weeks 条
    try:
        reports_sorted = sorted(reports, key=lambda r: getattr(r, "week", ""), reverse=True)[:weeks]
        reports_sorted = sorted(reports_sorted, key=lambda r: getattr(r, "week", ""))
    except (TypeError, ValueError):
        logger.warning("reflection reports sort failed", exc_info=True)
        reports_sorted = reports[:weeks] if reports else []
    weeks_data: list[dict] = []
    deltas: list[float] = []
    for idx, r in enumerate(reports_sorted):
        try:
            before = float(getattr(r, "completion_rate", 0) or 0)
        except (TypeError, ValueError):
            before = 0.0
        # 计算 after_rate：下一周的 completion_rate 视为 patch 后
        after: float
        if idx + 1 < len(reports_sorted):
            try:
                after = float(getattr(reports_sorted[idx + 1], "completion_rate", before) or before)
            except (TypeError, ValueError):
                after = before
        else:
            patch = getattr(r, "next_plan_patch", None) or {}
            if isinstance(patch, dict) and patch and not patch.get("keep"):
                # 估算增益：含减负/缓冲时 +0.08，否则 +0.06
                if patch.get("reduce_load") or patch.get("add_buffer") or patch.get("reduce_daily_hours") or patch.get("reduce_weekly"):
                    after = min(1.0, before + 0.08)
                else:
                    after = min(1.0, before + 0.06)
            else:
                after = before
        delta = round(after - before, 3)
        weeks_data.append({"week": getattr(r, "week", f"W{idx+1}"), "before_rate": round(before, 3), "after_rate": round(after, 3), "delta": delta})
        deltas.append(delta)
    avg_delta = round(sum(deltas) / len(deltas), 3) if deltas else 0.0
    return {"weeks": weeks_data, "avg_delta": avg_delta}
