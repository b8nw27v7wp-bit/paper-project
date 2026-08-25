from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlmodel import Session

from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.graph.extract import llm_extract_triples
from app.graph.neo import add_triples, search_prereqs
from app.rag.chunk import chunk_text, extract_pdf_text
from app.rag.store import search_chunks, store_chunks

router = APIRouter()

@router.post("/rag/ingest")
async def ingest(
    file: UploadFile = File(...),
    subject: str | None = Form(default=None),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    if file.size and file.size > 20*1024*1024:
        raise HTTPException(status_code=400, detail={"code":40001,"msg":"文件>20M"})
    ext = Path(file.filename or "").suffix.lower()
    allowed = (".pdf", ".jpg", ".jpeg", ".png", ".txt", ".md", "")
    if ext not in allowed:
        # 允许无后缀，但限制类型
        if ext not in ("", ".txt", ".md") and not (file.content_type and file.content_type.startswith("image/")):
            raise HTTPException(status_code=400, detail={"code":40001,"msg":"仅支持PDF/JPG/PNG/TXT/MD"})
        if ext not in allowed and file.content_type and file.content_type.startswith("image/"):
            pass
        elif ext not in allowed:
            raise HTTPException(status_code=400, detail={"code":40001,"msg":"仅支持PDF/JPG/PNG/TXT/MD"})
    data = await file.read()
    if ext == ".pdf":
        text = extract_pdf_text(data)
    elif ext in (".jpg",".jpeg",".png") or (file.content_type and file.content_type.startswith("image/")):
        # 图片先尝试OCR mock，当前返回空则用文件名
        text = f"图片 {file.filename} 内容"
    else:
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = ""
    if not text.strip():
        text = f"文件 {file.filename} 空"
    # 本地备份
    try:
        up_dir = Path("data/uploads")
        up_dir.mkdir(parents=True, exist_ok=True)
        # 防止 filename 为空
        fname = file.filename or "upload.txt"
        Path(up_dir / fname).write_bytes(data)
    except Exception:
        pass
    # 按段落分割，每块 500 字，overlap 50 字
    chunks = chunk_text(text, 500, 50)
    stored = await store_chunks(session, user_id, chunks, type_="knowledge", subject=subject)
    # 图谱抽取
    triples = await llm_extract_triples(text[:3000])
    from app.graph.neo import add_triples as _add_triples  # 延迟导入避免循环

    await _add_triples(triples, subject)
    return {"code":200,"msg":"ok","data":{"chunks":len(stored),"knowledges":len(triples),"triples":triples}}

@router.get("/rag/search")
def rag_search(q: str = Query(...), top_k: int = Query(default=10, ge=1, le=20), subject: str | None = Query(default=None), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    # 向量相似度检索，优先用 search_chunks（知识库专用），回退 search_memory 兼容
    try:
        vec_res = search_chunks(session, user_id, q, top_k=top_k, subject=subject)
    except Exception:
        from app.services.memory import search_memory

        vec_res = search_memory(session, user_id, q, top_k=top_k, type_="knowledge")
        if subject:
            vec_res = [r for r in vec_res if subject in r.get("content","")]
    # 图谱关联
    from app.graph.neo import search_prereqs

    graph = search_prereqs(q)
    return {"code":200,"msg":"ok","data":{"chunks": vec_res, "graph": graph}}


@router.get("/rag/chunks")
def list_chunks(
    subject: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """查看已有知识库列表，支持按 subject 过滤与分页"""
    from sqlalchemy import func

    from app.models.memory import MemoryChunk
    from sqlmodel import select

    q = select(MemoryChunk).where(MemoryChunk.user_id == user_id).where(MemoryChunk.type == "knowledge")
    if subject:
        # content 前缀 [subject] 或直接包含 subject
        q = q.where(MemoryChunk.content.contains(subject))
    total = session.exec(select(func.count()).select_from(q.subquery())).one()
    items = session.exec(q.order_by(MemoryChunk.created_at.desc()).offset((page - 1) * size).limit(size)).all()
    data = [
        {"id": it.id, "content": it.content, "type": it.type, "created_at": it.created_at.isoformat() if it.created_at else None}
        for it in items
    ]
    return {"code": 200, "msg": "ok", "data": {"items": data, "total": total, "page": page, "size": size}}
