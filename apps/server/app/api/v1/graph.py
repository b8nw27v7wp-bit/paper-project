
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.graph.neo import get_graph, get_subgraph, search_prereqs

router = APIRouter()


@router.get("/graph/subgraph")
def get_subgraph_api(subject: str = Query(...), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    """GET /api/v1/graph/subgraph?subject=xxx 返回子图（按学科）"""
    g = get_subgraph(subject)
    return {"code": 200, "msg": "ok", "data": g}


@router.get("/graph")
def get_graph_api(subject: str | None = Query(default=None), keyword: str | None = Query(default=None), session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    g = get_graph(subject)
    # keyword 过滤：若提供 keyword 则用 BFS 多跳关联（2层）增强
    if keyword:
        # 优先 BFS 返回相关边
        try:
            prereqs = search_prereqs(keyword)
            if prereqs:
                # 以 BFS 结果为准，节点取相关
                related_nodes = set()
                for e in prereqs:
                    related_nodes.add(e["from"])
                    related_nodes.add(e["to"])
                g["nodes"] = [n for n in g["nodes"] if n["name"] in related_nodes or keyword in n["name"]]
                g["edges"] = prereqs
            else:
                g["nodes"] = [n for n in g["nodes"] if keyword in n["name"]]
                g["edges"] = [e for e in g["edges"] if keyword in e["from"] or keyword in e["to"]]
        except Exception:
            g["nodes"] = [n for n in g["nodes"] if keyword in n["name"]]
            g["edges"] = [e for e in g["edges"] if keyword in e["from"] or keyword in e["to"]]
    return {"code":200,"msg":"ok","data": g}
