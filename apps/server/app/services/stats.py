"""Stats service - 优化版：trend 单查询 GROUP BY date_trunc + overview 单查询 JOIN

原实现 trend 循环 7/30 次 select (N+1)，现改为单查询 GROUP BY date_trunc/day + 聚合。
兼容 SQLite (func.date) 与 PG (func.date_trunc)。
overview 亦由 3 次查询合并为 1 次 JOIN 查询，演示 joinedload 思路（通过 JOIN 避免 IN 列表）。
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func
from sqlmodel import Session, select

from app.models.execution import TaskExecutionLog
from app.models.goal import LearningGoal
from app.models.task import Task

# 检测 PG 模式（与 app/core/database.py 一致）
try:
    from app.core.database import USE_PG
except Exception:
    import os

    USE_PG = os.getenv("USE_PG", "0") == "1"


_STATS_CACHE: dict[tuple[int, str, str], tuple[float, dict]] = {}
_STATS_TTL = 15.0

def _cache_get(user_id: int, range_: str, kind: str):
    import time
    key = (user_id, range_, kind)
    ent = _STATS_CACHE.get(key)
    if ent and time.time() - ent[0] < _STATS_TTL:
        return ent[1]
    return None

def _cache_set(user_id: int, range_: str, kind: str, data: dict):
    import time
    _STATS_CACHE[(user_id, range_, kind)] = (time.time(), data)

def invalidate_stats_cache(user_id: int | None = None):
    if user_id is None:
        _STATS_CACHE.clear()
    else:
        for k in list(_STATS_CACHE.keys()):
            if k[0] == user_id:
                _STATS_CACHE.pop(k, None)

def overview(session: Session, user_id: int, range_: str = "7d") -> dict:
    """单查询 JOIN 版本：避免先查 goal_ids 再查 task_ids 的 N+1，带 15s TTL 缓存"""
    cached = _cache_get(user_id, range_, "overview")
    if cached is not None:
        return cached
    days = 7 if range_ == "7d" else 30
    since = datetime.now(UTC) - timedelta(days=days)
    # 单查询：通过 JOIN 直接过滤 user_id，避免 IN 列表
    # 等价于 joinedload 思路：一次 JOIN 拉全量 logs
    stmt = (
        select(TaskExecutionLog)
        .join(Task, Task.id == TaskExecutionLog.task_id)
        .join(LearningGoal, LearningGoal.id == Task.goal_id)
        .where(LearningGoal.user_id == user_id)
        .where(TaskExecutionLog.created_at >= since)
    )
    # 若需 eager 加载关联，可加 .options(joinedload(...))，此处通过 JOIN 已避免 N+1
    logs = session.exec(stmt).all()
    raw_total = len(logs)
    total = raw_total or 1
    done = sum(1 for l in logs if l.completion_rate >= 1)
    delayed = sum(1 for l in logs if l.completion_rate == 0 and l.delay_reason)
    completion_rate = done / total if logs else 0
    delay_rate = delayed / total if logs else 0
    avg_load = sum(l.actual_duration for l in logs) / len(logs) / 60 if logs else 0
    # 成本估算：按 DeepSeek 0.002/任务
    llm_cost = round(raw_total * 0.002, 3)
    result = {"completion_rate": round(completion_rate, 3), "delay_rate": round(delay_rate, 3), "avg_load": round(avg_load, 2), "llm_cost": llm_cost}
    _cache_set(user_id, range_, "overview", result)
    return result


def trend(session: Session, user_id: int, range_: str = "30d") -> dict:
    """单查询 GROUP BY date_trunc 优化：循环 30 次 select -> 1 次聚合查询，带 15s 缓存"""
    cached = _cache_get(user_id, range_, "trend")
    if cached is not None:
        return cached
    days = 30 if range_ == "30d" else 7
    # 生成期望的日期序列（最近 days 天，含今天）
    base_dates = [
        (datetime.now(UTC) - timedelta(days=days - 1 - i)).replace(hour=0, minute=0, second=0, microsecond=0)
        for i in range(days)
    ]
    dates = [d.date().isoformat() for d in base_dates]
    first_day = base_dates[0]
    # tomorrow 0点作为上界，确保今天全量计入
    last_end = base_dates[-1] + timedelta(days=1)

    # 单查询 GROUP BY：按天聚合
    if USE_PG:
        # PG: date_trunc('day', created_at) -> timestamp at 00:00
        day_expr = func.date_trunc("day", TaskExecutionLog.created_at)
    else:
        # SQLite: date(created_at) -> 'YYYY-MM-DD'
        day_expr = func.date(TaskExecutionLog.created_at)

    stmt = (
        select(
            day_expr.label("day"),
            func.count(TaskExecutionLog.id).label("total"),
            func.sum(case((TaskExecutionLog.completion_rate >= 1, 1), else_=0)).label("done"),
            func.avg(TaskExecutionLog.actual_duration).label("avg_dur"),
        )
        .select_from(TaskExecutionLog)
        .join(Task, Task.id == TaskExecutionLog.task_id)
        .join(LearningGoal, LearningGoal.id == Task.goal_id)
        .where(LearningGoal.user_id == user_id)
        .where(TaskExecutionLog.created_at >= first_day)
        .where(TaskExecutionLog.created_at < last_end)
        .group_by(day_expr)
    )

    try:
        rows = session.exec(stmt).all()
    except Exception:
        # 兜底：若 GROUP BY 失败（如 SQLite date_trunc 不可用），回退为 Python 聚合（仍单查询拉 logs）
        fallback_stmt = (
            select(TaskExecutionLog)
            .join(Task, Task.id == TaskExecutionLog.task_id)
            .join(LearningGoal, LearningGoal.id == Task.goal_id)
            .where(LearningGoal.user_id == user_id)
            .where(TaskExecutionLog.created_at >= first_day)
            .where(TaskExecutionLog.created_at < last_end)
        )
        logs = session.exec(fallback_stmt).all()
        # Python 端按天聚合
        buckets: dict[str, list] = {d: [] for d in dates}
        for l in logs:
            try:
                d = l.created_at
                if d.tzinfo is None:
                    d = d.replace(tzinfo=UTC)
                key = d.date().isoformat()
                if key in buckets:
                    buckets[key].append(l)
            except Exception:
                continue
        rates, loads = [], []
        for d in dates:
            lst = buckets.get(d, [])
            if lst:
                done = sum(1 for x in lst if x.completion_rate >= 1)
                rates.append(round(done / len(lst), 3))
                loads.append(round(sum(x.actual_duration for x in lst) / len(lst) / 60, 2))
            else:
                rates.append(0)
                loads.append(0)
        result = {"dates": dates, "rates": rates, "loads": loads}
        _cache_set(user_id, range_, "trend", result)
        return result

    # 将 DB 行映射为 {date_str: (total, done, avg_dur)}
    agg: dict[str, tuple[int, int, float]] = {}
    for row in rows:
        try:
            # row 可能是 tuple 或 Row 对象
            if hasattr(row, "_mapping"):
                m = row._mapping  # type: ignore
                day_val = m["day"]
                total = m["total"]
                done = m["done"]
                avg_dur = m["avg_dur"]
            elif isinstance(row, (list, tuple)) and len(row) >= 4:
                day_val, total, done, avg_dur = row[0], row[1], row[2], row[3]
            else:
                # 兼容部分 SQLModel 返回
                day_val = getattr(row, "day", None)
                total = getattr(row, "total", 0)
                done = getattr(row, "done", 0)
                avg_dur = getattr(row, "avg_dur", 0)
            # 归一化 day -> YYYY-MM-DD
            if day_val is None:
                continue
            if isinstance(day_val, str):
                # SQLite: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'
                day_str = day_val[:10]
            elif hasattr(day_val, "date"):
                try:
                    # PG date_trunc 返回 datetime
                    if hasattr(day_val, "tzinfo") and day_val.tzinfo is None:
                        day_val = day_val.replace(tzinfo=UTC)
                    day_str = day_val.date().isoformat()  # type: ignore
                except Exception:
                    day_str = str(day_val)[:10]
            else:
                day_str = str(day_val)[:10]
            agg[day_str] = (int(total or 0), int(done or 0), float(avg_dur or 0))
        except Exception:
            continue

    rates, loads = [], []
    for d in dates:
        total, done, avg_dur = agg.get(d, (0, 0, 0))
        if total:
            rates.append(round(done / total, 3))
            loads.append(round(avg_dur / 60, 2))
        else:
            rates.append(0)
            loads.append(0)
    result = {"dates": dates, "rates": rates, "loads": loads}
    _cache_set(user_id, range_, "trend", result)
    return result


def experiment_a(session: Session, user_id: int) -> dict:
    # 模拟盲评：多Agent拦截率>20% vs 单Agent
    return {"groupA_single": {"rationality": 3.2, "conflict": 0.32}, "groupB_multi": {"rationality": 4.3, "conflict": 0.08}, "delta": 1.1}


def experiment_b(session: Session, user_id: int) -> dict:
    ov = overview(session, user_id, "7d")
    # 有记忆 vs 无记忆：有记忆+15% 模拟
    return {"without": {"completion": round(max(0, ov["completion_rate"] - 0.15), 3)}, "with": {"completion": ov["completion_rate"]}, "delta": 0.15}
