from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlmodel import Session

from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.graph.extract import llm_extract_triples
from app.graph.neo import add_triples, search_prereqs
from app.rag.chunk import chunk_text, extract_pdf_text
from app.rag.store import store_chunks
from app.services.memory import search_memory

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
    if ext not in (".pdf", ".jpg", ".jpeg", ".png", ".txt", ""):
        # 允许无后缀，但限制类型
        if ext not in ("", ".txt") and not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail={"code":40001,"msg":"仅支持PDF/JPG/PNG/TXT"})
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
        Path(up_dir / file.filename).write_bytes(data)
    except Exception:
        pass
    chunks = chunk_text(text, 512, 50)
    stored = await store_chunks(session, user_id, chunks, type_="knowledge", subject=subject)
    # 图谱抽取
    triples = await llm_extract_triples(text[:3000])
    await add_triples(triples, subject)
    return {"code":200,"msg":"ok","data":{"chunks":len(stored),"knowledges":len(triples),"triples":triples}}

@router.get("/rag/search")
def rag_search(q: str = Query(...), top_k: int = Query(default=10, ge=1, le=20), subject: str | None = Query(default=None), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    # 向量检索
    vec_res = search_memory(session, user_id, q, top_k=top_k, type_="knowledge")
    # 过滤 subject
    if subject:
        vec_res = [r for r in vec_res if subject in r.get("content","")]
    # 图谱关联
    graph = search_prereqs(q)
    return {"code":200,"msg":"ok","data":{"chunks": vec_res, "graph": graph}}
