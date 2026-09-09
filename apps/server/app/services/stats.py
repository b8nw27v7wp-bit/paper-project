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

# 模拟数据标记（与 services/experiments.py 口径一致；本地定义避免跨模块导入循环）
SIMULATED_NOTE = "模拟数据不可引用，需真实实验回放"


# S3: overflow 独立计数（旧字段不动，新函数+新字段）
_OVERFLOW_COUNT: int = 0


def record_overflow(n: int = 1) -> int:
    """overflow 独立计数+1（S2 length 截断联动），返回当前累计值。"""
    global _OVERFLOW_COUNT
    try:
        _n = int(n)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        _n = 1
    if _n < 0:
        _n = 0
    _OVERFLOW_COUNT += _n
    return int(_OVERFLOW_COUNT)


def get_overflow_count() -> int:
    """返回当前 overflow 累计值。"""
    try:
        return int(_OVERFLOW_COUNT)
    except (TypeError, ValueError):
        return 0


def reset_overflow_count() -> None:
    """重置 overflow 计数（单测隔离用）。"""
    global _OVERFLOW_COUNT
    _OVERFLOW_COUNT = 0


def _cache_key(user_id: int | str, range_: str, kind: str) -> tuple[int, str, str]:
    try:
        uid = int(user_id)  # type: ignore[arg-type]
    except Exception:
        uid = 0
    return (uid, range_, kind)


def _cache_get(user_id: int, range_: str, kind: str):
    import time
    key = _cache_key(user_id, range_, kind)
    ent = _STATS_CACHE.get(key)
    if ent and time.time() - ent[0] < _STATS_TTL:
        return dict(ent[1])  # 浅拷贝：防调用方 mutation 污染缓存窗口

def _cache_set(user_id: int, range_: str, kind: str, data: dict):
    import time
    _STATS_CACHE[_cache_key(user_id, range_, kind)] = (time.time(), dict(data))

def invalidate_stats_cache(user_id: int | None = None):
    if user_id is None:
        _STATS_CACHE.clear()
    else:
        try:
            uid = int(user_id)  # type: ignore[arg-type]
        except Exception:
            uid = 0
        for k in list(_STATS_CACHE.keys()):
            if k[0] == uid:
                _STATS_CACHE.pop(k, None)

def overview(session: Session, user_id: int, range_: str = "7d") -> dict:
    """单查询 JOIN 版本：避免先查 goal_ids 再查 task_ids 的 N+1，带 15s TTL 缓存"""
    cached = _cache_get(user_id, range_, "overview")
    if cached is not None:
        # S3: 新字段 overflow_count 独立透出，旧字段不动（缓存命中亦刷新为当前累计）
        try:
            cached["overflow_count"] = int(_OVERFLOW_COUNT)
        except (TypeError, ValueError):
            cached["overflow_count"] = 0
        return cached
    days = {"7d": 7, "30d": 30, "365d": 365}.get(range_, 30)
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
    # H4：completion_rate 可能为 None（历史/部分写入），用 (or 0) 防 TypeError；番茄行（delay_reason=='pomodoro'）不计入 delay_rate。
    done = sum(1 for l in logs if (l.completion_rate or 0) >= 1)
    # P1统一口径：delayed为(0+reason)或<0.5（与reflector/tasks_async一致，原仅==0漏<0.5）
    delayed = sum(1 for l in logs if (getattr(l, "delay_reason", None) != "pomodoro") and (((l.completion_rate or 0) == 0 and l.delay_reason) or (l.completion_rate or 0) < 0.5))
    completion_rate = done / total if logs else 0
    delay_rate = delayed / total if logs else 0
    avg_load = sum(l.actual_duration for l in logs) / len(logs) / 60 if logs else 0
    # 成本估算：按 DeepSeek 0.002/任务
    llm_cost = round(raw_total * 0.002, 3)
    # 中文注释：专注时长复用本周 logs，不新增查询；delay_reason=='pomodoro' 的 actual_duration 求和，无则 0
    focus_seconds = sum((l.actual_duration or 0) for l in logs if l.delay_reason == "pomodoro") if logs else 0
    # S3: 新字段 overflow_count 独立计数，旧字段计算不动
    try:
        _ov = int(_OVERFLOW_COUNT)
    except (TypeError, ValueError):
        _ov = 0
    result = {"completion_rate": round(completion_rate, 3), "delay_rate": round(delay_rate, 3), "avg_load": round(avg_load, 2), "llm_cost": llm_cost, "focus_seconds": int(focus_seconds), "overflow_count": _ov}
    _cache_set(user_id, range_, "overview", result)
    return result


def trend(session: Session, user_id: int, range_: str = "30d") -> dict:
    """单查询 GROUP BY date_trunc 优化：循环 30 次 select -> 1 次聚合查询，带 15s 缓存"""
    cached = _cache_get(user_id, range_, "trend")
    if cached is not None:
        return cached
    # 中文注释：支持 7d/30d/365d，循环体按 days 生成日期序列
    days = {"7d": 7, "30d": 30, "365d": 365}.get(range_, 30)
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
                # H4 同 overview：None 防护（or 0）。
                done = sum(1 for x in lst if (x.completion_rate or 0) >= 1)
                rates.append(round(done / len(lst), 3))
                loads.append(round(sum((x.actual_duration or 0) for x in lst) / len(lst) / 60, 2))
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
    return {"groupA_single": {"rationality": 3.2, "conflict": 0.32}, "groupB_multi": {"rationality": 4.3, "conflict": 0.08}, "delta": 1.1, "simulated": True, "note": SIMULATED_NOTE}


def experiment_b(session: Session, user_id: int) -> dict:
    ov = overview(session, user_id, "7d")
    # 有记忆 vs 无记忆：有记忆+15% 模拟
    return {"without": {"completion": round(max(0, ov["completion_rate"] - 0.15), 3)}, "with": {"completion": ov["completion_rate"]}, "delta": 0.15, "simulated": True, "note": SIMULATED_NOTE}


def self_evolution_curve(session: Session, user_id: int, weeks: int = 3) -> dict:
    """自演进曲线（P4）：复用 memory.self_evolution_experiment，无新依赖，不改栈。

    直接委托已有自演进实验函数，保持 estimated/模拟不可引用口径一致；
    stats 层仅做 weeks 钳制与透传，供 /stats/self-evolution 与 /experiments/self-evolution 共用。
    """
    try:
        w = int(weeks)
    except (TypeError, ValueError):
        w = 3
    w = max(1, min(12, w))
    try:
        from app.services.memory import self_evolution_experiment

        return self_evolution_experiment(session, user_id, weeks=w)
    except Exception as e:
        return {
            "experiment": "self_evolution",
            "weeks": [],
            "avg_delta": 0.0,
            "estimated": True,
            "simulated": True,
            "note": SIMULATED_NOTE,
            "error": str(e)[:200],
        }
