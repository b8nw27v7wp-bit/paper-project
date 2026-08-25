from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.models.execution import TaskExecutionLog
from app.models.goal import LearningGoal
from app.models.reflection import ReflectionReport
from app.models.task import Task


def _week_str(dt: datetime) -> str:
    # ISO week 2026-W34
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"

async def generate_reflection(session: Session, user_id: int, week: str | None = None) -> ReflectionReport:
    now = datetime.now(UTC)
    week = week or _week_str(now)
    # 查本周的 execution logs：通过 task -> goal -> user
    # 简化：查所有该用户的任务执行日志，过滤本周
    # 取最近7天
    week_start = now - timedelta(days=7)
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
        report = ReflectionReport(user_id=user_id, week=week, completion_rate=0, delay_rate=0, avg_load=0, analysis="本周无执行数据", next_plan_patch={})
        session.add(report)
        session.commit()
        session.refresh(report)
        return report
    done = sum(1 for l in logs if l.completion_rate >= 1)
    delayed = sum(1 for l in logs if l.completion_rate == 0 and l.delay_reason)
    completion_rate = done / total if total else 0
    delay_rate = delayed / total if total else 0
    avg_load = sum(l.actual_duration for l in logs) / total / 60 if total else 0  # 小时/天近似

    # ---- 模式分析：哪天效率高、什么类型容易拖延 ----
    # 建立 task_id -> Task 映射
    task_map: dict[int, Task] = {}
    try:
        tasks = session.exec(select(Task).where(Task.id.in_(task_ids))).all() if task_ids else []
        task_map = {t.id: t for t in tasks}
    except Exception:
        task_map = {}
    # 建立 goal_id -> LearningGoal 映射以取 subject
    goal_map: dict[int, LearningGoal] = {}
    try:
        goals = session.exec(select(LearningGoal).where(LearningGoal.id.in_(goal_ids))).all() if goal_ids else []
        goal_map = {g.id: g for g in goals}
    except Exception:
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
        except Exception:
            pass
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
        except Exception:
            pass

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
    # 尝试LLM 增强（若有 key 则用 LLM 润色分析，但保留本地统计作为兜底）
    try:
        from app.core.config import get_settings
        s = get_settings()
        if s.llm_api_key:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url)
            prompt = f"本周学情：完成率{completion_rate}，拖延率{delay_rate}，负荷{avg_load}h，最佳日{weekday_names[best_day] if best_day is not None else '无'}，最易拖延类型{worst_subject}，生成analysis和next_plan_patch{{reduce_load,add_buffer,prefer_weekday,focus_subject}} JSON"
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
            except Exception:
                pass
    except Exception:
        pass

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
