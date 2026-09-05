import asyncio
import json
import math

from sqlmodel import Session, select

from app.models.memory import MemoryChunk
from app.services.memory import cosine, embed_flagged, pg_vector_search


async def store_chunks(session: Session, user_id: int, chunks: list[str], type_: str = "knowledge", subject: str | None = None) -> list[MemoryChunk]:
    created = []
    for c in chunks:
        if not c.strip():
            continue
        vec, _mock = await embed_flagged(c)
        content = f"[{subject}] {c}" if subject else c
        try:
            from app.models.memory import _USE_PG_VECTOR
            embedding_val = vec if _USE_PG_VECTOR else json.dumps(vec)
        except Exception:
            embedding_val = json.dumps(vec)
        mc = MemoryChunk(user_id=user_id, content=content, embedding=embedding_val, type=type_)  # type: ignore
        session.add(mc)
        created.append(mc)
    session.commit()
    for m in created:
        session.refresh(m)
    return created


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
    stmt = select(MemoryChunk).where(MemoryChunk.user_id == user_id).where(MemoryChunk.type == "knowledge")
    items = session.exec(stmt).all()
    # subject 过滤：前缀 [subject] 或内容包含
    if subject:
        subject = subject.strip()
        items = [it for it in items if subject in (it.content or "") or (it.content or "").startswith(f"[{subject}]")]
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
    scores_only = [s for s, _ in scored]
    thr = _adaptive_threshold(scores_only) if adaptive else 0.7
    filtered = [(s, it) for s, it in scored if s >= thr]
    res: list[dict] = []
    for score, it in filtered[:top_k]:
        res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "subject": subject, "threshold": thr, "emb": emb, "created_at": it.created_at.isoformat() if it.created_at else None})
    if len(res) < top_k:
        for score, it in scored:
            if len(res) >= top_k:
                break
            if any(r["id"] == it.id for r in res):
                continue
            if score > 0.4:
                res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "subject": subject, "threshold": thr, "emb": emb, "created_at": it.created_at.isoformat() if it.created_at else None})
    if len(res) < top_k:
        for score, it in scored:
            if len(res) >= top_k:
                break
            if any(r["id"] == it.id for r in res):
                continue
            res.append({"id": it.id, "content": it.content, "score": round(score, 4), "type": it.type, "subject": subject, "threshold": thr, "emb": emb, "created_at": it.created_at.isoformat() if it.created_at else None})
    return res[:top_k]


async def asearch_chunks(session: Session, user_id: int, query: str, top_k: int = 5, subject: str | None = None, adaptive: bool = True) -> list[dict]:
    if not query or not query.strip():
        return []
    qvec, mock = await embed_flagged(query)
    emb = "mock" if mock else "real"
    pg_rows = pg_vector_search(session, user_id, qvec, top_k, type_="knowledge")
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
                vec = json.loads(it.embedding) if isinstance(it.embedding, str) else it.embedding
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
    res: list[dict] = []
    for score, it in scored:
        if len(res) >= top_k:
            break
        if score >= thr or len(res) < top_k:
            # 简化：取TopK但标记阈值
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


async def asearch_with_evidence(session: Session, user_id: int, query: str, top_k: int = 5, subject: str | None = None) -> dict:
    chunks = await asearch_chunks(session, user_id, query, top_k=top_k, subject=subject)
    graph: list[dict] = []
    try:
        from app.graph.neo import search_prereqs
        graph = search_prereqs(query)
    except Exception:
        graph = []
    evidence_chain = []
    for ch in chunks[:3]:
        content = ch.get("content", "")
        for e in graph[:5]:
            if e.get("from") in content or e.get("to") in content:
                evidence_chain.append({"chunk_id": ch["id"], "evidence": f"{e.get('from')}->{e.get('to')}", "score": ch["score"]})
    return {"chunks": chunks, "graph": graph, "evidence_chain": evidence_chain, "subject": subject}
