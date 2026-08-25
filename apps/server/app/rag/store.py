import asyncio
import json
import math

from sqlmodel import Session, select

from app.models.memory import MemoryChunk
from app.services.memory import cosine, embed_text
from app.services.memory import _hash_mock_embedding  # noqa: F401 - reuse mock vector


async def store_chunks(session: Session, user_id: int, chunks: list[str], type_: str = "knowledge", subject: str | None = None) -> list[MemoryChunk]:
    created = []
    for c in chunks:
        if not c.strip():
            continue
        vec = await embed_text(c)
        # subject 拼到 content 前缀以支持按学科检索
        content = f"[{subject}] {c}" if subject else c
        mc = MemoryChunk(user_id=user_id, content=content, embedding=json.dumps(vec), type=type_)
        session.add(mc)
        created.append(mc)
    session.commit()
    for m in created:
        session.refresh(m)
    return created


def _embedding_sync(text: str) -> list[float]:
    """同步获取 embedding，兼容已有 event loop"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return _hash_mock_embedding(text)
        else:
            return loop.run_until_complete(embed_text(text))
    except Exception:
        return _hash_mock_embedding(text)


def search_chunks(session: Session, user_id: int, query: str, top_k: int = 5, subject: str | None = None) -> list[dict]:
    """向量相似度检索，返回 top_k 结果（知识库专用）"""
    if not query or not query.strip():
        return []
    qvec = _embedding_sync(query)
    # 仅检索 knowledge 类型
    stmt = select(MemoryChunk).where(MemoryChunk.user_id == user_id).where(MemoryChunk.type == "knowledge")
    items = session.exec(stmt).all()
    # subject 过滤（若提供）
    if subject:
        items = [it for it in items if subject in (it.content or "")]
    scored: list[tuple[float, MemoryChunk]] = []
    for it in items:
        try:
            vec = json.loads(it.embedding) if isinstance(it.embedding, str) else it.embedding
            if not vec:
                continue
            score = cosine(qvec, vec)
            scored.append((score, it))
        except Exception:
            continue
    scored.sort(key=lambda x: x[0], reverse=True)
    # 阈值与回退逻辑：>0.7 高置信，回退到 0.4，最后取 Top
    filtered = [(s, it) for s, it in scored if s > 0.7]
    res: list[dict] = []
    for score, it in filtered[:top_k]:
        res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "subject": subject, "created_at": it.created_at.isoformat() if it.created_at else None})
    if len(res) < top_k:
        for score, it in scored:
            if len(res) >= top_k:
                break
            if any(r["id"] == it.id for r in res):
                continue
            if score > 0.4:
                res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "subject": subject, "created_at": it.created_at.isoformat() if it.created_at else None})
    if len(res) < top_k:
        for score, it in scored:
            if len(res) >= top_k:
                break
            if any(r["id"] == it.id for r in res):
                continue
            res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "subject": subject, "created_at": it.created_at.isoformat() if it.created_at else None})
    return res[:top_k]


async def asearch_chunks(session: Session, user_id: int, query: str, top_k: int = 5, subject: str | None = None) -> list[dict]:
    """异步版本"""
    if not query or not query.strip():
        return []
    try:
        qvec = await embed_text(query)
    except Exception:
        qvec = _hash_mock_embedding(query)
    stmt = select(MemoryChunk).where(MemoryChunk.user_id == user_id).where(MemoryChunk.type == "knowledge")
    items = session.exec(stmt).all()
    if subject:
        items = [it for it in items if subject in (it.content or "")]
    scored: list[tuple[float, MemoryChunk]] = []
    for it in items:
        try:
            vec = json.loads(it.embedding) if isinstance(it.embedding, str) else it.embedding
            if not vec:
                continue
            score = cosine(qvec, vec)
            scored.append((score, it))
        except Exception:
            continue
    scored.sort(key=lambda x: x[0], reverse=True)
    res: list[dict] = []
    for score, it in scored[:top_k]:
        # 阈值逻辑与同步版一致，简化为直接 TopK
        res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "subject": subject, "created_at": it.created_at.isoformat() if it.created_at else None})
    return res
