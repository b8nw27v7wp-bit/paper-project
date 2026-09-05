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
