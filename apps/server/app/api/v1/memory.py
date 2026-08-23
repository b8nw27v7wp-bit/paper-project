from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session
from pydantic import BaseModel

from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.services.memory import create_memory, search_memory

router = APIRouter()

class MemoryCreate(BaseModel):
    content: str
    type: str = "memory"  # memory/knowledge
    source_id: Optional[int] = None

@router.post("/memory")
async def post_memory(payload: MemoryCreate, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    if not payload.content or len(payload.content) > 1000:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "content 1-1000"})
    if payload.type not in ("memory", "knowledge"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "type非法"})
    mc = await create_memory(session, user_id, payload.content, payload.type, payload.source_id)
    return {"code": 200, "msg": "ok", "data": mc}

@router.get("/memory/search")
def search(q: str = Query(...), top_k: int = Query(default=5, ge=1, le=20), type: Optional[str] = Query(default=None), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    if not q or len(q) > 200:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "q 1-200"})
    res = search_memory(session, user_id, q, top_k, type)
    return {"code": 200, "msg": "ok", "data": res}
