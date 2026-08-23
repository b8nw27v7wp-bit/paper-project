"""Pi 4工具启示的注册表 - 单一职责，可热插"""
from typing import Callable, Dict, Any, List

Registry = Dict[str, Callable]

_tools: Registry = {}

def register(name: str):
    def deco(fn: Callable):
        _tools[name] = fn
        return fn
    return deco

def get(name: str) -> Callable | None:
    return _tools.get(name)

def list_tools() -> List[str]:
    return list(_tools.keys())

# 4核心工具占位，真实实现由 services 注入
@register("memory_search")
async def memory_search(query: str, top_k: int = 5, **kw) -> List[Dict[str, Any]]:
    from app.services.memory import search_memory as _search
    # 需 session，从 kw 传入
    session = kw.get("session")
    user_id = kw.get("user_id", 1)
    if not session:
        return []
    return _search(session, user_id, query, top_k, type_="memory")

@register("rag_search")
async def rag_search(query: str, top_k: int = 10, **kw) -> List[Dict[str, Any]]:
    from app.services.memory import search_memory as _search
    session = kw.get("session")
    user_id = kw.get("user_id", 1)
    if not session:
        return []
    return _search(session, user_id, query, top_k, type_="knowledge")

@register("graph_search")
async def graph_search(query: str, **kw) -> List[Dict[str, Any]]:
    from app.graph.neo import search_prereqs
    return search_prereqs(query)

@register("write_tasks")
async def write_tasks(tasks: List[Dict[str, Any]], **kw) -> List[Dict[str, Any]]:
    # 透传，由上层落库
    return tasks
