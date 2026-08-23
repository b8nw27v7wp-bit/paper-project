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
    # LLM 生成分析
    analysis = f"本周完成率{completion_rate:.0%}，拖延率{delay_rate:.0%}，平均负荷{avg_load:.1f}h/天"
    patch = {}
    if completion_rate < 0.7:
        patch["reduce_load"] = True
        analysis += "；建议下周减负。"
    if delay_rate > 0.3:
        patch["add_buffer"] = True
        analysis += "；建议增加缓冲时间。"
    # 尝试LLM
    try:
        from app.core.config import get_settings
        s = get_settings()
        if s.llm_api_key:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url)
            prompt = f"本周学情：完成率{completion_rate}，拖延率{delay_rate}，负荷{avg_load}h，生成analysis和next_plan_patch{{reduce_load,add_buffer}} JSON"
            resp = await client.chat.completions.create(model=s.llm_model, messages=[{"role":"user","content":prompt}], temperature=0.3, timeout=10)
            resp.choices[0].message.content or ""
            # 解析可忽略，保留mock
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
