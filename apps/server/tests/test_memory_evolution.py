"""P4 记忆与自进化 3用例：偏好抽取 / patch归一 / 自进化estimated标记（只增不改旧断言）。"""
import asyncio

from sqlmodel import Session, select

from app.core.database import engine, init_db

init_db()


def test_extract_preference_hints():
    """偏好抽取纯函数：weekday/subject/hours_bias 结构化，不改排序语义（无 IO）"""
    from app.services.memory import asearch_memory, extract_preference_hints

    # 空/None 兜底
    assert extract_preference_hints([]) == {"prefer_weekday": None, "focus_subject": None, "hours_bias": 0.0}
    assert extract_preference_hints(None) == {"prefer_weekday": None, "focus_subject": None, "hours_bias": 0.0}

    # 显式键优先
    explicit = extract_preference_hints([{"content": "无关", "prefer_weekday": 3, "focus_subject": "英语", "hours_bias": 0.5}])
    assert explicit == {"prefer_weekday": 3, "focus_subject": "英语", "hours_bias": 0.5}

    # 文本模式抽取：周三/薄弱点数学/减负
    memories = [
        {"content": "周三效率最高，偏好周三学习", "score": 0.9},
        {"content": "薄弱点：数学，需拆解", "score": 0.8},
        {"content": "轻量节奏，减负", "score": 0.7},
    ]
    hints = extract_preference_hints(memories)
    assert hints["prefer_weekday"] == 2
    assert hints["focus_subject"] == "数学"
    assert hints["hours_bias"] == -0.5

    # asearch 附带 hints 不改排序：同 query 两次检索顺序一致
    async def _check_order() -> None:
        from app.services import memory as memory_mod

        uid = 999991
        # 清理残留后写入两条可区分记忆
        with Session(engine) as s:
            from app.models.memory import MemoryChunk

            for r in s.exec(select(MemoryChunk).where(MemoryChunk.user_id == uid)).all():
                s.delete(r)
            s.commit()
            await memory_mod.create_memory(s, uid, "周五效率最高偏好", "memory")
            await memory_mod.create_memory(s, uid, "无关填充内容xyz", "memory")
        with Session(engine) as s:
            plain = await asearch_memory(s, uid, "偏好", top_k=5, type_="memory", force=True)
            bundled = await asearch_memory(s, uid, "偏好", top_k=5, type_="memory", force=True, with_hints=True)
        assert isinstance(plain, list)
        assert isinstance(bundled, dict) and "results" in bundled and "hints" in bundled
        assert [r["id"] for r in bundled["results"]] == [r["id"] for r in plain]
        assert set(bundled["hints"].keys()) == {"prefer_weekday", "focus_subject", "hours_bias"}
        with Session(engine) as s:
            from app.models.memory import MemoryChunk

            for r in s.exec(select(MemoryChunk).where(MemoryChunk.user_id == uid)).all():
                s.delete(r)
            s.commit()

    asyncio.run(_check_order())


def test_normalize_patch_aligns_with_graph():
    """patch归一与 graph reflector 口径对齐：buffer 15 / reduce_*→reduce_load补齐，未知键保留"""
    from app.scheduler.reflector import normalize_patch_for_planner

    # add_buffer=True 补 buffer_minutes=15（graph 侧同口径）
    assert normalize_patch_for_planner({"add_buffer": True}) == {"add_buffer": True, "buffer_minutes": 15}
    # 已有 buffer 不覆盖
    assert normalize_patch_for_planner({"add_buffer": True, "buffer_minutes": 30})["buffer_minutes"] == 30
    # reduce_* 均补齐 reduce_load（旧 planner 兼容）
    assert normalize_patch_for_planner({"reduce_daily_hours": True})["reduce_load"] is True
    assert normalize_patch_for_planner({"reduce_weekly": True})["reduce_load"] is True
    assert normalize_patch_for_planner({"reduce_future_x": 1})["reduce_load"] is True
    # 已含 reduce_load 不覆盖，未知键原样保留
    out = normalize_patch_for_planner({"reduce_load": True, "prefer_weekday": 2, "focus_subject": "数学"})
    assert out["reduce_load"] is True and out["prefer_weekday"] == 2 and out["focus_subject"] == "数学"
    # 非法输入与 reallocate 规范
    assert normalize_patch_for_planner(None) == {}
    assert normalize_patch_for_planner("x") == {}
    ra = normalize_patch_for_planner({"reallocate": {"from": "2026-09-01", "to": "2026-09-02", "hours": "1"}})
    assert ra["reallocate"] == {"from": "2026-09-01", "to": "2026-09-02", "hours": 1.0}


def test_self_evolution_estimated_flag():
    """自进化 estimated 标记保留：无真实数据时 estimated=True 且明示不可引用，不伪增益"""
    from app.models.reflection import ReflectionReport
    from app.services.memory import self_evolution_experiment
    from app.services.stats import self_evolution_curve

    uid = 999992
    with Session(engine) as s:
        for r in s.exec(select(ReflectionReport).where(ReflectionReport.user_id == uid)).all():
            s.delete(r)
        s.commit()
        # 无反思数据 → 回退模拟分支，estimated=True
        res = self_evolution_experiment(s, uid, weeks=3)
        assert res["experiment"] == "self_evolution"
        assert res.get("estimated") is True
        assert len(res["weeks"]) == 3
        assert all(w.get("estimated") is True for w in res["weeks"])
        # 非真实数据不可引用口径：结论/样本明示模拟不可引用
        assert "不可引用" in res.get("conclusion", "") or "模拟" in res.get("conclusion", "")
        # stats 曲线复用同一函数，口径一致
        curve = self_evolution_curve(s, uid, weeks=3)
        assert curve["experiment"] == "self_evolution"
        assert curve.get("estimated") is True
        assert len(curve["weeks"]) == 3
