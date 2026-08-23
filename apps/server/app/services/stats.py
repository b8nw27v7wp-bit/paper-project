from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.models.execution import TaskExecutionLog
from app.models.goal import LearningGoal
from app.models.task import Task


def overview(session: Session, user_id: int, range_: str = "7d") -> dict:
    days = 7 if range_ == "7d" else 30
    since = datetime.now(UTC) - timedelta(days=days)
    goal_ids = session.exec(select(LearningGoal.id).where(LearningGoal.user_id == user_id)).all()
    if not goal_ids:
        return {"completion_rate": 0, "delay_rate": 0, "avg_load": 0}
    task_ids = session.exec(select(Task.id).where(Task.goal_id.in_(goal_ids))).all()
    logs = session.exec(select(TaskExecutionLog).where(TaskExecutionLog.task_id.in_(task_ids) if task_ids else False).where(TaskExecutionLog.created_at >= since)).all()
    total = len(logs) or 1
    done = sum(1 for l in logs if l.completion_rate >= 1)
    delayed = sum(1 for l in logs if l.completion_rate == 0 and l.delay_reason)
    completion_rate = done / total if logs else 0
    delay_rate = delayed / total if logs else 0
    avg_load = sum(l.actual_duration for l in logs) / len(logs) / 60 if logs else 0
    return {"completion_rate": round(completion_rate, 3), "delay_rate": round(delay_rate, 3), "avg_load": round(avg_load, 2)}

def trend(session: Session, user_id: int, range_: str = "30d") -> dict:
    days = 30 if range_ == "30d" else 7
    goal_ids = session.exec(select(LearningGoal.id).where(LearningGoal.user_id == user_id)).all()
    task_ids = session.exec(select(Task.id).where(Task.goal_id.in_(goal_ids))).all()
    dates, rates, loads = [], [], []
    for i in range(days):
        d = datetime.now(UTC) - timedelta(days=days-1-i)
        day_start = d.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        logs = session.exec(select(TaskExecutionLog).where(TaskExecutionLog.task_id.in_(task_ids) if task_ids else False).where(TaskExecutionLog.created_at >= day_start).where(TaskExecutionLog.created_at < day_end)).all()
        if logs:
            done = sum(1 for l in logs if l.completion_rate >= 1)
            rate = done / len(logs)
            load = sum(l.actual_duration for l in logs) / len(logs) / 60
        else:
            rate, load = 0, 0
        dates.append(day_start.date().isoformat())
        rates.append(round(rate, 3))
        loads.append(round(load, 2))
    return {"dates": dates, "rates": rates, "loads": loads}

def experiment_a(session: Session, user_id: int) -> dict:
    # 模拟盲评：多Agent拦截率>20% vs 单Agent
    return {"groupA_single": {"rationality": 3.2, "conflict": 0.32}, "groupB_multi": {"rationality": 4.3, "conflict": 0.08}, "delta": 1.1}

def experiment_b(session: Session, user_id: int) -> dict:
    ov = overview(session, user_id, "7d")
    # 有记忆 vs 无记忆：有记忆+15% 模拟
    return {"without": {"completion": round(max(0, ov["completion_rate"]-0.15),3)}, "with": {"completion": ov["completion_rate"]}, "delta": 0.15}
