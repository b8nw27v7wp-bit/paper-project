import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.memory import MemoryChunk

settings = get_settings()

def _hash_mock_embedding(text: str, dim: int = 1536) -> list[float]:
    # 语义化 hash mock：基于字符/二元组哈希的词袋向量，保证子串查询有较高余弦相似度
    # 取代全文本 SHA 随机向量，避免检索失效
    vals = [0.0] * dim
    if not text:
        return vals
    for i, ch in enumerate(text):
        h = hashlib.sha256(ch.encode()).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        vals[idx] += 1.0
        if i < len(text) - 1:
            big = text[i : i + 2]
            h2 = hashlib.sha256(big.encode()).digest()
            idx2 = int.from_bytes(h2[:4], "little") % dim
            vals[idx2] += 0.5
    # 归一化
    norm = math.sqrt(sum(x * x for x in vals))
    if norm > 0:
        vals = [x / norm for x in vals]
    return vals

async def embed_text(text: str) -> list[float]:
    # Pi-ai启示：优先走统一LLM
    try:
        from app.core.llm import UnifiedClient
        client = UnifiedClient()
        vec = await client.embed(text)
        if vec and len(vec) == 1536:
            return vec
    except Exception:
        pass
    if not settings.llm_api_key:
        return _hash_mock_embedding(text)
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
        resp = await client.embeddings.create(model="text-embedding-3-small", input=text)
        vec = resp.data[0].embedding
        if len(vec) != 1536:
            vec = (vec[:1536] + [0.0]*1536)[:1536]
        n = math.sqrt(sum(x*x for x in vec))
        return [x/n for x in vec] if n else vec
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
    now = datetime.now(UTC)
    for it in items:
        try:
            vec = json.loads(it.embedding) if isinstance(it.embedding, str) else it.embedding
            if not vec:
                continue
            score = cosine(qvec, vec)
            # 记忆衰减：超过 30 天的记忆 score *= 0.7
            try:
                created = it.created_at
                if created is not None:
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=UTC)
                    age_days = (now - created).days
                    if age_days > 30:
                        score *= 0.7
            except Exception:
                pass
            scored_all.append((score, it))
        except Exception:
            continue
    scored_all.sort(key=lambda x: x[0], reverse=True)
    # 阈值调整：>0.7 高置信，>0.4 低置信可用
    filtered = [(s, it) for s, it in scored_all if s > 0.7]
    res = []
    for score, it in filtered[:top_k]:
        res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "source_id": it.source_id, "created_at": it.created_at.isoformat() if it.created_at else None})
    # 不足则放宽到 0.4 并补齐
    if len(res) < top_k:
        for score, it in scored_all:
            if len(res) >= top_k:
                break
            if any(r["id"] == it.id for r in res):
                continue
            if score > 0.4:
                res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "source_id": it.source_id, "created_at": it.created_at.isoformat() if it.created_at else None})
    # 仍不足则取Top
    if len(res) < top_k:
        for score, it in scored_all:
            if len(res) >= top_k:
                break
            if any(r["id"] == it.id for r in res):
                continue
            res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "source_id": it.source_id, "created_at": it.created_at.isoformat() if it.created_at else None})
    return res[:top_k]

def summarize_for_task(task_title: str, duration: int, rate: float, delay_reason: str | None) -> str:
    if rate >= 1:
        return f"任务「{task_title}」按时完成{int(duration)}分钟，效率高"
    if delay_reason:
        return f"任务「{task_title}」拖延{delay_reason}，完成率{rate}"
    return f"任务「{task_title}」完成率{rate}，用时{int(duration)}分钟"
