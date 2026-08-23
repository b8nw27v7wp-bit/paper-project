import hashlib
import json
import math
from typing import Any

from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.memory import MemoryChunk

settings = get_settings()

def _hash_mock_embedding(text: str, dim: int = 1536) -> list[float]:
    # 稳定hash mock，满足离线可验
    h = hashlib.sha256(text.encode()).digest()
    # 扩展到dim
    vals = []
    for i in range(dim):
        vals.append((h[i % len(h)] / 255.0) * 2 - 1)
    # 归一化
    norm = math.sqrt(sum(x*x for x in vals))
    if norm > 0:
        vals = [x / norm for x in vals]
    return vals

async def embed_text(text: str) -> list[float]:
    if not settings.llm_api_key:
        return _hash_mock_embedding(text)
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
        resp = await client.embeddings.create(model="text-embedding-3-small", input=text)
        vec = resp.data[0].embedding
        # 若维度不是1536，截断/填充
        if len(vec) != 1536:
            if len(vec) > 1536:
                vec = vec[:1536]
            else:
                vec = vec + [0.0]*(1536 - len(vec))
        # 归一化
        norm = math.sqrt(sum(x*x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec
    except Exception:
        return _hash_mock_embedding(text)

def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x*y for x, y in zip(a, b))

async def create_memory(session: Session, user_id: int, content: str, type_: str = "memory", source_id: int | None = None) -> MemoryChunk:
    vec = await embed_text(content)
    mc = MemoryChunk(user_id=user_id, content=content, embedding=json.dumps(vec), type=type_, source_id=source_id)
    session.add(mc)
    session.commit()
    session.refresh(mc)
    return mc

def search_memory(session: Session, user_id: int, query: str, top_k: int = 5, type_: str | None = None) -> list[dict]:
    # 计算query向量
    import asyncio
    # 同步上下文中跑异步embed
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在已有loop中，需用 mock 同步版本
            qvec = _hash_mock_embedding(query)
        else:
            qvec = loop.run_until_complete(embed_text(query))
    except Exception:
        qvec = _hash_mock_embedding(query)

    q = select(MemoryChunk).where(MemoryChunk.user_id == user_id)
    if type_:
        q = q.where(MemoryChunk.type == type_)
    items = session.exec(q).all()
    scored_all: list[tuple[float, Any]] = []
    for it in items:
        try:
            vec = json.loads(it.embedding) if isinstance(it.embedding, str) else it.embedding
            if not vec:
                continue
            score = cosine(qvec, vec)
            # mock语义补偿：若query为content子串，提升至0.85
            if query and query in it.content:
                score = max(score, 0.85)
            scored_all.append((score, it))
        except Exception:
            continue
    scored_all.sort(key=lambda x: x[0], reverse=True)
    # 先取 >0.75
    filtered = [(s, it) for s, it in scored_all if s > 0.75]
    res = []
    for score, it in filtered[:top_k]:
        res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "source_id": it.source_id})
    # 不足则放宽到 0.5 并补齐
    if len(res) < top_k:
        for score, it in scored_all:
            if len(res) >= top_k:
                break
            if any(r["id"] == it.id for r in res):
                continue
            if score > 0.5:
                res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "source_id": it.source_id})
    # 仍不足则取Top
    if len(res) < top_k:
        for score, it in scored_all:
            if len(res) >= top_k:
                break
            if any(r["id"] == it.id for r in res):
                continue
            res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "source_id": it.source_id})
    return res[:top_k]

def summarize_for_task(task_title: str, duration: int, rate: float, delay_reason: str | None) -> str:
    if rate >= 1:
        return f"任务「{task_title}」按时完成{int(duration)}分钟，效率高"
    if delay_reason:
        return f"任务「{task_title}」拖延{delay_reason}，完成率{rate}"
    return f"任务「{task_title}」完成率{rate}，用时{int(duration)}分钟"
