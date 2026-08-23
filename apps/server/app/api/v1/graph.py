from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlmodel import Session
from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.graph.neo import get_graph

router = APIRouter()

@router.get("/graph")
def get_graph_api(subject: Optional[str] = Query(default=None), keyword: Optional[str] = Query(default=None), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    g = get_graph(subject)
    # keyword 过滤
    if keyword:
        g["nodes"] = [n for n in g["nodes"] if keyword in n["name"]]
        g["edges"] = [e for e in g["edges"] if keyword in e["from"] or keyword in e["to"]]
    return {"code":200,"msg":"ok","data": g}
