import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.database import engine, init_db
from app.main import app

init_db()
client = TestClient(app)

FAKE_VEC = [1.0] + [0.0] * 1535


async def _fake_embed_flag(text: str) -> tuple[list[float], bool]:
    return list(FAKE_VEC), False


def test_sync_memory_api_uses_async_real_embedding(monkeypatch):
    """同步 API 端点走 asearch 异步路径，查询向量与入库同源（注入真向量，非 hash mock）"""
    from app.services import memory as memory_mod

    monkeypatch.setattr(memory_mod, "embed_flagged", _fake_embed_flag)
    with Session(engine) as session:
        asyncio.run(memory_mod.create_memory(session, 1, "真向量同源记忆A", "memory"))
    r = client.get("/api/v1/memory/search?q=真向量同源&top_k=5")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    assert all(d["emb"] == "real" for d in data)
    target = [d for d in data if "真向量同源记忆A" in d["content"]]
    assert target and target[0]["score"] >= 0.9


def test_rag_search_api_uses_async_real_embedding(monkeypatch):
    from app.rag import store as store_mod

    monkeypatch.setattr(store_mod, "embed_flagged", _fake_embed_flag)
    with Session(engine) as session:
        asyncio.run(store_mod.store_chunks(session, 1, ["知识库同源片段K"], type_="knowledge"))
    r = client.get("/api/v1/rag/search?q=知识库同源片段K&top_k=5")
    assert r.status_code == 200
    chunks = r.json()["data"]["chunks"]
    assert len(chunks) >= 1
    assert all(c["emb"] == "real" for c in chunks)
    assert any("知识库同源片段K" in c["content"] for c in chunks)


def test_no_key_falls_back_to_mock_annotation(monkeypatch):
    """无 key：入库与查询都回退 hash mock，且结果显式标注 emb=mock"""
    from app.services import memory as memory_mod

    monkeypatch.setattr(memory_mod.settings, "llm_api_key", "", raising=False)
    monkeypatch.setattr(memory_mod, "pg_vector_search", lambda *a, **kw: None)
    with Session(engine) as session:
        asyncio.run(memory_mod.create_memory(session, 1, "mock标注记忆B", "memory"))
        res = asyncio.run(memory_mod.asearch_memory(session, 1, "mock标注记忆B", top_k=5, type_="memory"))
    assert len(res) >= 1
    assert all(d["emb"] == "mock" for d in res)
    assert any("mock标注记忆B" in d["content"] for d in res)


def test_pg_vector_sql_branch(monkeypatch):
    """USE_PG=1 且列为 Vector 时走 pg_vector_search（SQL <=>）分支"""
    import app.models.memory as mm
    from app.services import memory as memory_mod

    seen: dict = {}

    class _Row:
        id = 777
        content = "pg命中内容"
        type = "memory"
        source_id = None
        created_at = None

    def fake_pg(session, user_id, qvec, top_k, type_=None):
        seen.update(user_id=user_id, top_k=top_k, type_=type_, dim=len(qvec))
        return [(0.93, _Row())]

    monkeypatch.setattr(mm, "_USE_PG_VECTOR", True)
    monkeypatch.setattr(memory_mod, "pg_vector_search", fake_pg)
    with Session(engine) as session:
        res = asyncio.run(memory_mod.asearch_memory(session, 1, "pgq", top_k=3, type_="memory"))
    assert seen["type_"] == "memory" and seen["top_k"] == 3 and seen["dim"] == 1536
    assert len(res) >= 1
    assert res[0]["content"] == "pg命中内容" and res[0]["score"] == 0.93


def test_pg_vector_store_branch(monkeypatch):
    import app.models.memory as mm
    from app.rag import store as store_mod

    class _Row:
        id = 888
        content = "pg知识命中"
        type = "knowledge"
        subject = None
        created_at = None

    def fake_pg(session, user_id, qvec, top_k, type_=None):
        assert type_ == "knowledge"
        return [(0.88, _Row())]

    monkeypatch.setattr(mm, "_USE_PG_VECTOR", True)
    monkeypatch.setattr(store_mod, "pg_vector_search", fake_pg)
    with Session(engine) as session:
        res = asyncio.run(store_mod.asearch_chunks(session, 1, "kbq", top_k=2))
    assert len(res) >= 1
    assert res[0]["content"] == "pg知识命中" and res[0]["score"] == 0.88


def test_pg_unavailable_falls_back_to_python_cosine(monkeypatch):
    """PG 标志打开但列不是 Vector（SQLite）时，优雅回退 Python cosine"""
    import app.models.memory as mm
    from app.services import memory as memory_mod

    with Session(engine) as session:
        asyncio.run(memory_mod.create_memory(session, 1, "回退目标记忆X", "memory"))
        monkeypatch.setattr(mm, "_USE_PG_VECTOR", True)
        res = asyncio.run(memory_mod.asearch_memory(session, 1, "回退目标记忆X", top_k=3, type_="memory"))
    assert isinstance(res, list)
    assert any("回退目标记忆X" in r["content"] for r in res)


def test_embedding_sync_raises_in_running_loop():
    """运行中的事件循环内调用同步 embedding：显式报错，不再静默返回假向量"""
    from app.rag.store import _embedding_sync

    async def _inner():
        with pytest.raises(RuntimeError):
            _embedding_sync("x")

    asyncio.run(_inner())


def test_batch_embed_same_source(monkeypatch):
    """批量 embed 同源：store_chunks 分批并发（限20）且查询/入库同源"""
    from app.rag import store as store_mod

    calls: list[str] = []

    async def _fake_batch_embed(text: str) -> tuple[list[float], bool]:
        calls.append(text)
        vec = [0.0] * 1536
        vec[sum(ord(c) for c in text) % 1536] = 1.0
        return list(vec), False

    monkeypatch.setattr(store_mod, "embed_flagged", _fake_batch_embed)
    chunks = [f"批量同源片段{i:02d}-xyz-{i * 7}" for i in range(5)]
    with Session(engine) as session:
        created = asyncio.run(store_mod.store_chunks(session, 1, chunks, type_="knowledge"))
        assert len(created) == 5
        assert len(calls) == 5
        res = asyncio.run(store_mod.asearch_chunks(session, 1, chunks[2], top_k=5))
    assert any(chunks[2] in r["content"] for r in res)
    assert all(r["emb"] == "real" for r in res)


def test_pg_vec_normalization():
    """PG vec 归一：Vector/tuple 非 str 经 list(vec) 归一，不被 json.loads 丢弃"""
    import json as _json

    from app.rag.store import _norm_vec
    from app.services.memory import _normalize_vec

    tup = (1.0, 0.0, 0.5)
    assert _norm_vec(tup) == [1.0, 0.0, 0.5]
    assert _normalize_vec(tup) == [1.0, 0.0, 0.5]
    assert _norm_vec(_json.dumps([1, 2])) == [1, 2]
    assert _normalize_vec(_json.dumps([1, 2])) == [1, 2]
    assert _norm_vec(None) is None
    # 含 tuple embedding 的条目仍可评分（不丢弃）
    from app.services.memory import _score_and_filter

    class _It:
        id = 1
        content = "vec归一条目"
        type = "memory"
        source_id = None
        created_at = None
        embedding = (1.0, 0.0)

    out = _score_and_filter([_It()], [1.0, 0.0], top_k=1, emb="real")
    assert len(out) == 1 and out[0]["content"] == "vec归一条目"


def test_reflector_no_data_no_fake_gain():
    """reflector 无数据不伪增益：无报告/单报告无下一周时 after_rate=None、delta=0、无+0.06/0.08"""
    from app.models.reflection import ReflectionReport
    from app.scheduler.reflector import evaluate_patch_effectiveness

    uid = 999999
    with Session(engine) as session:
        # 清理残留
        from sqlmodel import select as _select

        for r in session.exec(_select(ReflectionReport).where(ReflectionReport.user_id == uid)).all():
            session.delete(r)
        session.commit()
        res = evaluate_patch_effectiveness(session, uid, weeks=3)
        assert res["weeks"] == []
        assert res["avg_delta"] == 0.0
        assert res.get("estimated") is False
        rep = ReflectionReport(
            user_id=uid,
            week="2026-W99",
            completion_rate=0.5,
            delay_rate=0.1,
            avg_load=1.0,
            analysis="t",
            next_plan_patch={"reduce_load": True},
        )
        session.add(rep)
        session.commit()
        res2 = evaluate_patch_effectiveness(session, uid, weeks=3)
        assert len(res2["weeks"]) == 1
        assert res2["weeks"][0]["after_rate"] is None
        assert res2["weeks"][0]["delta"] == 0.0
        assert res2["avg_delta"] == 0.0
        for r in session.exec(_select(ReflectionReport).where(ReflectionReport.user_id == uid)).all():
            session.delete(r)
        session.commit()
