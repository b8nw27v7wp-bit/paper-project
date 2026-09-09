"""Wave2 P1后端一致性单测：mode/abort门/review门槛/RAG阈值/extract跳过/delayed口径。"""
import asyncio

import pytest
from sqlmodel import Session

from app.core.database import engine, init_db

init_db()


def test_execution_mode_consumed():
    """mode真消费：calendar_create/write_tasks为sequential，三检索为parallel；executor双写断言sequential。"""
    from app.agents.tools import registry

    assert registry.get_registered("calendar_create").execution_mode == "sequential"
    assert registry.get_registered("write_tasks").execution_mode == "sequential"
    assert registry.get_registered("memory_search").execution_mode == "parallel"
    assert registry.get_registered("rag_search").execution_mode == "parallel"
    assert registry.get_registered("graph_search").execution_mode == "parallel"
    # executor双写循环显式消费execution_mode（源码断言存在）
    import inspect

    from app.agents import graph as graph_mod

    src = inspect.getsource(graph_mod.executor_node)
    assert 'get_registered("calendar_create").execution_mode' in src
    assert "sequential" in src


@pytest.mark.asyncio
async def test_abort_gate():
    """abort可取消在途：execute_tool遇abort_flag直接返aborted；researcher gather前检查。"""
    import inspect

    from app.agents import graph as graph_mod
    from app.agents.tools import registry

    res = await registry.execute_tool("web_search", {"query": "x", "top_k": 1}, context={"abort_flag": True})
    assert res.get("is_error") is True and res.get("aborted") is True and res.get("error") == "aborted"
    # researcher源码含gather前单次abort检查（Pi简化版注释）
    src = inspect.getsource(graph_mod.researcher_node)
    assert "abort_flag" in src and "gather" in src


def test_review_threshold_gates_mentor():
    """review进决策：critic通过但_review.score<40转mentor并附issues首项；缺失视为100走executor。"""
    from app.agents import graph as graph_mod

    assert graph_mod._REVIEW_MIN_SCORE == 40
    # 低分转mentor
    state = {"critic_feedback": "", "rewrites": 0, "_review": {"score": 20, "issues": ["前置缺失: A应在B前"]}, "_thought": "t0"}
    assert graph_mod.should_replan(state) == "mentor"
    assert "前置缺失" in state.get("critic_feedback", "")
    assert "前置缺失" in state.get("_thought", "")
    # 缺失视为100 → executor
    state2 = {"critic_feedback": "", "rewrites": 0, "_thought": ""}
    assert graph_mod.should_replan(state2) == "executor"
    # 高分仍executor
    state3 = {"critic_feedback": "", "rewrites": 0, "_review": {"score": 100, "issues": []}}
    assert graph_mod.should_replan(state3) == "executor"


def test_rag_threshold_unified_and_true_filter(monkeypatch):
    """RAG统一：sync/async非自适应阈值同0.5；命中时真过滤不垫补；evidence同7键。"""
    import app.rag.store as store_mod

    # 非自适应统一0.5：构造0.6/0.4两档，adaptive=False应仅返>=0.5
    class _It:
        def __init__(self, i, content):
            self.id = i
            self.content = content
            self.type = "knowledge"
            self.created_at = None

    rows = [(0.6, _It(1, "高分命中")), (0.4, _It(2, "低分噪声"))]

    async def _fake_embed(text):
        return ([1.0] + [0.0] * 1535), False

    def _fake_sync(text):
        return ([1.0] + [0.0] * 1535), False

    monkeypatch.setattr(store_mod, "embed_flagged", _fake_embed)
    monkeypatch.setattr(store_mod, "_embedding_sync", _fake_sync)
    monkeypatch.setattr(store_mod, "pg_vector_search", lambda *a, **kw: list(rows))

    with Session(engine) as s:
        sync_res = store_mod.search_chunks(s, 1, "q", top_k=5, adaptive=False)
        assert len(sync_res) == 1 and sync_res[0]["score"] == 0.6
        assert sync_res[0]["threshold"] == 0.5
        async_res = asyncio.run(store_mod.asearch_chunks(s, 1, "q", top_k=5, adaptive=False))
        assert len(async_res) == 1 and async_res[0]["score"] == 0.6
        assert async_res[0]["threshold"] == 0.5
        # evidence同7键
        monkeypatch.setattr("app.graph.neo.search_prereqs", lambda q, depth=2: [{"from": "高分", "to": "目标", "type": "PREREQUISITE"}])
        sync_ev = store_mod.search_with_evidence(s, 1, "q", top_k=5)
        async_ev = asyncio.run(store_mod.asearch_with_evidence(s, 1, "q", top_k=5))
        assert set(sync_ev.keys()) == {"chunks", "graph", "evidence_chain", "threshold", "subject", "query", "coverage"}
        assert set(async_ev.keys()) == set(sync_ev.keys())


def test_extract_dependent_direction_skipped():
    """extract方向断言：A依赖B模式跳过不存（宁缺勿错），其他箭头模式仍存。"""
    from app.graph.extract import mock_extract_triples

    assert mock_extract_triples("链表依赖数组") == []
    kept = mock_extract_triples("链表->数组")
    assert any(a == "链表" and b == "数组" for a, _, b in kept)


def test_delayed_unified_lt_half():
    """delayed统一<0.5：完成率0.3无reason仍计delayed（原==0漏计）。"""
    from datetime import UTC, datetime, timedelta

    from sqlmodel import select

    from app.models.execution import TaskExecutionLog
    from app.models.goal import LearningGoal
    from app.models.task import Task
    from app.services import stats as stats_mod

    uid = 999993
    stats_mod.invalidate_stats_cache(uid)
    with Session(engine) as s:
        for m in (TaskExecutionLog, Task, LearningGoal):
            try:
                for r in s.exec(select(m).where(m.user_id == uid) if hasattr(m, "user_id") else select(m)).all():
                    pass
            except Exception:
                pass
        # 清理该用户旧数据
        try:
            goals = s.exec(select(LearningGoal).where(LearningGoal.user_id == uid)).all()
            for g in goals:
                tasks = s.exec(select(Task).where(Task.goal_id == g.id)).all()
                for t in tasks:
                    for lg in s.exec(select(TaskExecutionLog).where(TaskExecutionLog.task_id == t.id)).all():
                        s.delete(lg)
                    s.delete(t)
                s.delete(g)
            s.commit()
        except Exception:
            s.rollback()
        g = LearningGoal(user_id=uid, title="delayed-g", deadline=datetime.now(UTC) + timedelta(days=5), subject="general")
        s.add(g)
        s.commit()
        s.refresh(g)
        now = datetime.now(UTC).replace(tzinfo=None)
        t = Task(goal_id=g.id, title="T1", planned_start=now, planned_end=now + timedelta(hours=1), priority=3, status="todo")
        s.add(t)
        s.commit()
        s.refresh(t)
        s.add(TaskExecutionLog(task_id=t.id, completion_rate=0.3, actual_duration=60, delay_reason=None))
        s.commit()
        ov = stats_mod.overview(s, uid, "7d")
        assert ov["delay_rate"] == 1.0
        # 清理
        for lg in s.exec(select(TaskExecutionLog).where(TaskExecutionLog.task_id == t.id)).all():
            s.delete(lg)
        s.delete(t)
        s.delete(g)
        s.commit()
    stats_mod.invalidate_stats_cache(uid)
