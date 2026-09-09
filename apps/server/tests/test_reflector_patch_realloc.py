"""P1 reflector patch 真重分配用例（仅追加，不动旧断言）。

覆盖纯函数 app.services.planner.apply_patch_reallocation：
- reduce_load 顺延生效
- add_buffer 间隙存在
- 超载截断有标记（移入下一周 + note，status 不变，绝不删除）
- 空 patch 等于旧行为（纯函数恒等，planner 侧保留 +30min 平移）
- reallocate 跨日搬移
"""
from datetime import datetime, timezone, timedelta

from app.services.planner import apply_patch_reallocation


def _mk(day: datetime, sh: float, dur: float, title="T", pri=3, **kw):
    s = day.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(hours=sh)
    e = s + timedelta(hours=dur)
    d = {"title": title, "planned_start": s.isoformat(), "planned_end": e.isoformat(), "priority": pri}
    d.update(kw)
    return d


def _day_load(tasks, day_str: str) -> float:
    tot = 0.0
    for t in tasks:
        s = datetime.fromisoformat(t["planned_start"])
        e = datetime.fromisoformat(t["planned_end"])
        if s.date().isoformat() == day_str:
            tot += (e - s).total_seconds() / 3600
    return tot


def test_reduce_load_defers_overload():
    base = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    day = base.date().isoformat()
    # 同日 3 任务共 4.5h，可用 2h，必超载
    tasks = [_mk(base, 0, 1.5, "High", pri=5), _mk(base, 1.5, 1.5, "Mid", pri=3), _mk(base, 3.0, 1.5, "Low", pri=1)]
    out = apply_patch_reallocation(tasks, {"reduce_load": True}, {"hours_per_day": 2})
    assert len(out) == len(tasks)
    assert _day_load(out, day) <= 2.0 + 1e-9
    # 低优先级应被顺延出超载日，高优先级保留
    low = next(t for t in out if t["title"] == "Low")
    assert datetime.fromisoformat(low["planned_start"]).date().isoformat() != day


def test_add_buffer_gap_exists():
    base = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    tasks = [_mk(base, 0, 1.0, "A"), _mk(base, 1.0, 1.0, "B")]
    out = apply_patch_reallocation(tasks, {"add_buffer": True}, {"hours_per_day": 4})
    assert len(out) == 2
    o = sorted(out, key=lambda t: t["planned_start"])
    gap = (datetime.fromisoformat(o[1]["planned_start"]) - datetime.fromisoformat(o[0]["planned_end"])).total_seconds() / 60
    assert gap >= 15 - 1e-6
    # 时长保持
    for a, b in zip(sorted(tasks, key=lambda t: t["title"]), o):
        da = (datetime.fromisoformat(a["planned_end"]) - datetime.fromisoformat(a["planned_start"])).total_seconds()
        db = (datetime.fromisoformat(b["planned_end"]) - datetime.fromisoformat(b["planned_start"])).total_seconds()
        assert abs(da - db) < 1e-6


def test_overload_truncation_marked_not_dropped():
    base = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    # 单任务 3h，可用 1h：无法靠搬移消解，应标记保留
    t = _mk(base, 0, 3.0, "Huge", pri=1, status="todo")
    out = apply_patch_reallocation([t], {"reduce_load": True}, {"hours_per_day": 1})
    assert len(out) == 1
    assert out[0].get("status") == "todo"
    assert "超载截断" in str(out[0].get("note", ""))
    # 多任务仍超载时：搬至下周 + note，数量不变（用非 reduce patch 使减负不介入，直达截断兜底）
    tasks = [_mk(base, 0, 1.0, "K1", pri=1), _mk(base, 1.0, 1.0, "K2", pri=5)]
    out2 = apply_patch_reallocation(tasks, {"add_buffer": True}, {"hours_per_day": 1})
    assert len(out2) == 2
    assert any("超载截断" in str(x.get("note", "")) for x in out2)


def test_empty_patch_is_identity_old_behavior():
    base = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    tasks = [_mk(base, 0, 1.0, "A"), _mk(base, 1.0, 1.0, "B")]
    for p in ({}, {"keep": True}, None):
        out = apply_patch_reallocation(tasks, p, {"hours_per_day": 2})  # type: ignore[arg-type]
        assert [(t["planned_start"], t["planned_end"]) for t in out] == [(t["planned_start"], t["planned_end"]) for t in tasks]
    # 输入不被突变
    assert tasks[0]["planned_start"] == out[0]["planned_start"]


def test_reallocate_moves_across_days():
    base = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    fday = base.date().isoformat()
    tday = (base + timedelta(days=1)).date().isoformat()
    tasks = [_mk(base, 0, 1.0, "MoveMe", pri=1), _mk(base, 1.0, 1.0, "Stay", pri=5)]
    out = apply_patch_reallocation(tasks, {"reallocate": {"from": fday, "to": tday, "hours": 1.0}}, {"hours_per_day": 4})
    assert len(out) == 2
    moved = next(t for t in out if t["title"] == "MoveMe")
    assert datetime.fromisoformat(moved["planned_start"]).date().isoformat() == tday


# ---- v1.2: normalize_patch_for_planner（reflector→planner 回注可执行性） ----

def test_normalize_add_buffer_fills_15min():
    from app.scheduler.reflector import normalize_patch_for_planner

    out = normalize_patch_for_planner({"add_buffer": True})
    assert out["buffer_minutes"] == 15
    # 已显式指定不覆盖
    out2 = normalize_patch_for_planner({"add_buffer": True, "buffer_minutes": 30})
    assert out2["buffer_minutes"] == 30


def test_normalize_reduce_alias_maps_to_reduce_load():
    from app.scheduler.reflector import normalize_patch_for_planner

    assert normalize_patch_for_planner({"reduce_daily_hours": 2})["reduce_load"] is True
    assert normalize_patch_for_planner({"reduce_weekly": True})["reduce_load"] is True
    # 已含 reduce_load 不覆盖；空/非法输入恒等安全
    assert normalize_patch_for_planner({"reduce_load": False})["reduce_load"] is False
    assert normalize_patch_for_planner(None) == {}
    assert normalize_patch_for_planner("bad") == {}


def test_normalize_reallocate_hours_float_and_unknown_kept():
    from app.scheduler.reflector import normalize_patch_for_planner

    out = normalize_patch_for_planner({"reallocate": {"from": "2026-09-08", "to": "2026-09-09", "hours": "2"}, "prefer_weekday": "Mon"})
    assert out["reallocate"]["hours"] == 2.0
    assert out["prefer_weekday"] == "Mon"  # 未知键原样保留
