import asyncio
import json
import math

from sqlmodel import Session, select

from app.models.memory import MemoryChunk
from app.services.memory import cosine, embed_flagged, pg_vector_search


async def store_chunks(session: Session, user_id: int, chunks: list[str], type_: str = "knowledge", subject: str | None = None) -> list[MemoryChunk]:
    items = [c for c in chunks if c and c.strip()]
    if not items:
        return []
    # 分批并发 embed（限 20 并发，与查询侧 embed_flagged 同源）
    sem = asyncio.Semaphore(20)

    async def _one(c: str):
        async with sem:
            return await embed_flagged(c)

    vecs = await asyncio.gather(*[_one(c) for c in items])
    created: list[MemoryChunk] = []
    for c, (vec, _mock) in zip(items, vecs):
        content = f"[{subject}] {c}" if subject else c
        try:
            from app.models.memory import _USE_PG_VECTOR
            embedding_val = vec if _USE_PG_VECTOR else json.dumps(vec)
        except Exception:
            embedding_val = json.dumps(vec)
        mc = MemoryChunk(user_id=user_id, content=content, embedding=embedding_val, type=type_)  # type: ignore
        created.append(mc)
    # bulk 保存
    if created:
        session.add_all(created)
        session.commit()
        for m in created:
            session.refresh(m)
    return created


def _norm_vec(raw):  # type: ignore[no-untyped-def]
    """PG Vector 归一：Vector 用 list(vec)，str 走 json.loads，防丢弃"""
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else None
        except Exception:
            return None
    try:
        return list(raw)
    except Exception:
        return None


def _embedding_sync(text: str) -> tuple[list[float], bool]:
    """同步上下文取 embedding；事件循环运行中显式报错（原静默返回 hash mock 导致查询/入库失配）"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        raise RuntimeError("sync embedding inside running event loop; use asearch_chunks")
    if loop is None:
        return asyncio.run(embed_flagged(text))
    return loop.run_until_complete(embed_flagged(text))


def _adaptive_threshold(scores: list[float]) -> float:
    """阈值自适应：基于Top分与均值方差"""
    if not scores:
        return 0.4
    top = scores[0]
    if len(scores) == 1:
        return max(0.4, min(0.7, top * 0.7))
    mean = sum(scores) / len(scores)
    var = sum((x - mean) ** 2 for x in scores) / len(scores)
    std = math.sqrt(var) if var > 0 else 0
    # 动态：top*0.65 与 mean+0.5*std 取大，夹逼0.35-0.75
    thr = max(top * 0.65, mean + 0.5 * std)
    return max(0.35, min(0.75, round(thr, 3)))


def search_chunks(session: Session, user_id: int, query: str, top_k: int = 5, subject: str | None = None, adaptive: bool = True) -> list[dict]:
    """向量相似度检索，支持subject过滤与阈值自适应"""
    if not query or not query.strip():
        return []
    qvec, mock = _embedding_sync(query)
    emb = "mock" if mock else "real"
    # PG 分支优先走 HNSW（与 asearch_chunks 对齐；SQLite 回退 Python cosine）
    try:
        pg_rows = pg_vector_search(session, user_id, qvec, top_k if not subject else max(top_k * 3, top_k), type_="knowledge")
    except Exception:
        pg_rows = None
    if pg_rows is not None:
        scored: list[tuple[float, MemoryChunk]] = list(pg_rows)
        if subject:
            subject = subject.strip()
            scored = [(s, it) for s, it in scored if subject in (it.content or "")]
    else:
        stmt = select(MemoryChunk).where(MemoryChunk.user_id == user_id).where(MemoryChunk.type == "knowledge")
        items = session.exec(stmt).all()
        # subject 过滤：前缀 [subject] 或内容包含
        if subject:
            subject = subject.strip()
            items = [it for it in items if subject in (it.content or "") or (it.content or "").startswith(f"[{subject}]")]
        scored = []
        for it in items:
            try:
                vec = _norm_vec(it.embedding)
                if not vec:
                    continue
                score = cosine(qvec, vec)
                scored.append((score, it))
            except Exception:
                continue
    scored.sort(key=lambda x: x[0], reverse=True)
    scores_only = [s for s, _ in scored]
    thr = _adaptive_threshold(scores_only) if adaptive else 0.5
    # P1真过滤二选一：命中>=thr则仅返过滤结果（删>0.4/全量垫补装饰分支）；
    # 无命中时回退TopK保可用（如模糊“链表”0.31<0.4仍返1条，见test_rag_graph）
    filtered = [(s, it) for s, it in scored if s >= thr]
    target = filtered if filtered else scored
    res: list[dict] = []
    for score, it in target[:top_k]:
        res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "subject": subject, "threshold": thr, "emb": emb, "created_at": it.created_at.isoformat() if it.created_at else None})
    return res[:top_k]


async def asearch_chunks(session: Session, user_id: int, query: str, top_k: int = 5, subject: str | None = None, adaptive: bool = True) -> list[dict]:
    if not query or not query.strip():
        return []
    qvec, mock = await embed_flagged(query)
    emb = "mock" if mock else "real"
    pg_rows = pg_vector_search(session, user_id, qvec, top_k if not subject else max(top_k * 3, top_k), type_="knowledge")
    if pg_rows is not None:
        scored: list[tuple[float, MemoryChunk]] = list(pg_rows)
    else:
        stmt = select(MemoryChunk).where(MemoryChunk.user_id == user_id).where(MemoryChunk.type == "knowledge")
        items = session.exec(stmt).all()
        if subject:
            subject = subject.strip()
            items = [it for it in items if subject in (it.content or "")]
        scored = []
        for it in items:
            try:
                vec = _norm_vec(it.embedding)
                if not vec:
                    continue
                score = cosine(qvec, vec)
                scored.append((score, it))
            except Exception:
                continue
    if subject:
        subject = subject.strip()
        scored = [(s, it) for s, it in scored if subject in (it.content or "")]
    scored.sort(key=lambda x: x[0], reverse=True)
    scores_only = [s for s, _ in scored]
    thr = _adaptive_threshold(scores_only) if adaptive else 0.5
    # P1真过滤二选一：命中>=thr则仅返过滤结果（原`or len<top_k`装饰分支删去）；
    # 无命中回退TopK保可用，与同步版同口径
    filtered = [(s, it) for s, it in scored if s >= thr]
    target = filtered if filtered else scored
    res: list[dict] = []
    for score, it in target[:top_k]:
        res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "subject": subject, "threshold": thr, "emb": emb, "created_at": it.created_at.isoformat() if it.created_at else None})
    return res[:top_k]


def search_with_evidence(session: Session, user_id: int, query: str, top_k: int = 5, subject: str | None = None, include_graph: bool = True) -> dict:
    """evidence式检索：返回chunk+graph证据链"""
    chunks = search_chunks(session, user_id, query, top_k=top_k, subject=subject, adaptive=True)
    graph: list[dict] = []
    if include_graph:
        try:
            from app.graph.neo import search_prereqs
            graph = search_prereqs(query)
        except Exception:
            graph = []
    # 构建证据链：chunk中出现图谱节点即关联
    evidence_chain: list[dict] = []
    for ch in chunks[:3]:
        content = ch.get("content", "")
        for e in graph[:5]:
            frm = e.get("from", "")
            to = e.get("to", "")
            if frm and frm in content:
                evidence_chain.append({"chunk_id": ch["id"], "evidence": f"{frm}->{to}", "type": e.get("type", "PREREQUISITE"), "score": ch["score"]})
            elif to and to in content:
                evidence_chain.append({"chunk_id": ch["id"], "evidence": f"{frm}->{to}", "type": e.get("type", "PREREQUISITE"), "score": ch["score"]})
    # 若无直接命中，给一条兜底
    if not evidence_chain and chunks and graph:
        evidence_chain.append({"chunk_id": chunks[0]["id"], "evidence": f"{graph[0].get('from')}->{graph[0].get('to')}", "type": "PREREQUISITE", "score": chunks[0]["score"]})
    thr = chunks[0].get("threshold", 0.5) if chunks else 0.5
    return {"chunks": chunks, "graph": graph, "evidence_chain": evidence_chain, "threshold": thr, "subject": subject, "query": query, "coverage": round(len(evidence_chain) / max(1, len(chunks)), 3)}


async def asearch_with_evidence(session: Session, user_id: int, query: str, top_k: int = 5, subject: str | None = None, include_graph: bool = True) -> dict:
    chunks = await asearch_chunks(session, user_id, query, top_k=top_k, subject=subject)
    graph: list[dict] = []
    if include_graph:
        try:
            from app.graph.neo import search_prereqs
            graph = search_prereqs(query)
        except Exception:
            graph = []
    evidence_chain = []
    for ch in chunks[:3]:
        content = ch.get("content", "") or ""
        for e in graph[:5]:
            frm = e.get("from") or ""
            to = e.get("to") or ""
            if (frm and frm in content) or (to and to in content):
                evidence_chain.append({"chunk_id": ch["id"], "evidence": f"{e.get('from')}->{e.get('to')}", "type": e.get("type", "PREREQUISITE"), "score": ch["score"]})
    # P1与同步版同7键：无直接命中时给一条兜底，保持coverage口径一致
    if not evidence_chain and chunks and graph:
        evidence_chain.append({"chunk_id": chunks[0]["id"], "evidence": f"{graph[0].get('from')}->{graph[0].get('to')}", "type": "PREREQUISITE", "score": chunks[0]["score"]})
    thr = chunks[0].get("threshold", 0.5) if chunks else 0.5
    return {"chunks": chunks, "graph": graph, "evidence_chain": evidence_chain, "threshold": thr, "subject": subject, "query": query, "coverage": round(len(evidence_chain) / max(1, len(chunks)), 3)}
