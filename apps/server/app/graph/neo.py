
# 内存图（Neo4j不可用时回退 - 第三级）
_mem_nodes: dict[str, dict] = {}
_mem_edges: list[dict] = []

def _mem_upsert_knowledge(name: str, subject: str | None = None):
    if name not in _mem_nodes:
        _mem_nodes[name] = {"id": name, "name": name, "subject": subject or "通用"}
    else:
        # 若已有但 subject 为通用且新 subject 更具体则更新
        if _mem_nodes[name].get("subject") == "通用" and subject and subject != "通用":
            _mem_nodes[name]["subject"] = subject

def _mem_add_edge(frm: str, to: str, type_: str = "PREREQUISITE"):
    if not any(e["from"]==frm and e["to"]==to for e in _mem_edges):
        _mem_edges.append({"from": frm, "to": to, "type": type_})

# SQLite 图谱（第二级 fallback）
try:
    from app.graph.sqlite_graph import (
        sqlite_add_edge,
        sqlite_get_graph,
        sqlite_search_prereqs,
        sqlite_upsert_node,
    )

    _sqlite_available = True
except Exception:
    _sqlite_available = False
    sqlite_upsert_node = None  # type: ignore
    sqlite_add_edge = None  # type: ignore
    sqlite_get_graph = None  # type: ignore
    sqlite_search_prereqs = None  # type: ignore

# Neo4j 尝试
_neo_available = None
_driver = None

def _get_driver():
    global _neo_available, _driver
    if _neo_available is not None:
        return _driver if _neo_available else None
    try:
        from neo4j import GraphDatabase

        from app.core.config import get_settings
        s = get_settings()
        driver = GraphDatabase.driver(s.neo4j_url, auth=(s.neo4j_user, s.neo4j_password))
        driver.verify_connectivity()
        _driver = driver
        _neo_available = True
        return driver
    except Exception:
        _neo_available = False
        return None

def _extract_from_text_simple(text: str) -> list[tuple[str, str, str]]:
    """简单关键词匹配从文本自动提取实体关系"""
    # 优先用 extract.py 的 mock 抽取
    try:
        from app.graph.extract import mock_extract_triples

        return mock_extract_triples(text)
    except Exception:
        # 极简兜底：按句切取词
        import re

        sents = re.split(r"[。；;,.，\n]", text)
        triples = []
        for s in sents[:5]:
            words = [w for w in re.split(r"\s+", s.strip()) if len(w) >= 2]
            if len(words) >= 2:
                triples.append((words[0], "PREREQUISITE", words[1]))
        return triples[:10]


async def add_triples(triples: list[tuple[str, str, str]] | str | None, subject: str | None = None):
    # 支持从文本自动提取：若传入字符串则视为文本
    if isinstance(triples, str):
        triples = _extract_from_text_simple(triples)
    elif triples is None:
        triples = []
    # 兼容部分调用者传入单条文本的列表
    normalized: list[tuple[str, str, str]] = []
    for item in triples or []:
        if isinstance(item, str):
            # 字符串元素视为需抽取的文本片段
            normalized.extend(_extract_from_text_simple(item))
        elif isinstance(item, (list, tuple)) and len(item) == 3:
            frm, rel, to = item
            if isinstance(frm, str) and isinstance(to, str) and frm.strip() and to.strip():
                normalized.append((frm.strip(), str(rel).strip() or "PREREQUISITE", to.strip()))
        elif isinstance(item, dict) and "from" in item and "to" in item:
            normalized.append((str(item["from"]).strip(), "PREREQUISITE", str(item["to"]).strip()))
    triples = normalized

    # 三级写入：先内存
    for frm, rel, to in triples:
        _mem_upsert_knowledge(frm, subject)
        _mem_upsert_knowledge(to, subject)
        _mem_add_edge(frm, to, rel)

    # 再 SQLite（第二级）
    if _sqlite_available:
        try:
            for frm, rel, to in triples:
                sqlite_upsert_node(frm, subject)
                sqlite_upsert_node(to, subject)
                sqlite_add_edge(frm, to, rel)
        except Exception:
            pass

    # 最后尝试 Neo4j（第一级）
    driver = _get_driver()
    if not driver:
        return
    try:
        with driver.session() as sess:
            for frm, rel, to in triples:
                sess.run("MERGE (a:Knowledge {name:$frm}) ON CREATE SET a.subject=$subj", frm=frm, subj=subject or "通用")
                sess.run("MERGE (a:Knowledge {name:$to}) ON CREATE SET a.subject=$subj", to=to, subj=subject or "通用")
                sess.run("MATCH (a:Knowledge {name:$frm}), (b:Knowledge {name:$to}) MERGE (a)-[:PREREQUISITE]->(b)", frm=frm, to=to)
    except Exception:
        pass

def get_graph(subject: str | None = None) -> dict:
    # 三级 fallback: Neo4j → SQLite → 内存
    driver = _get_driver()
    if driver:
        try:
            with driver.session() as sess:
                if subject:
                    res = sess.run("MATCH (a:Knowledge)-[r:PREREQUISITE]->(b:Knowledge) WHERE a.subject=$s OR b.subject=$s RETURN a.name as frm, b.name as to, type(r) as type LIMIT 200", s=subject)
                else:
                    res = sess.run("MATCH (a:Knowledge)-[r:PREREQUISITE]->(b:Knowledge) RETURN a.name as frm, b.name as to, type(r) as type LIMIT 200")
                nodes = {}
                edges = []
                for rec in res:
                    frm = rec["frm"]; to = rec["to"]
                    nodes[frm] = {"id": frm, "name": frm, "subject": subject or "通用"}
                    nodes[to] = {"id": to, "name": to, "subject": subject or "通用"}
                    edges.append({"from": frm, "to": to, "type": rec["type"]})
                if nodes:
                    return {"nodes": list(nodes.values()), "edges": edges}
        except Exception:
            pass
    # 第二级：SQLite
    if _sqlite_available:
        try:
            g = sqlite_get_graph(subject)
            if g and (g.get("nodes") or g.get("edges")):
                return g
            # 若 SQLite 有数据但为空，仍回退检查内存合并（避免空图）
            if g and not subject:
                # 无过滤时若 SQLite 有任意节点则返回
                if g["nodes"] or g["edges"]:
                    return g
        except Exception:
            pass
    # 第三级回退：内存
    nodes = list(_mem_nodes.values())
    edges = list(_mem_edges)
    if subject:
        # 过滤
        nodes = [n for n in nodes if n.get("subject") == subject]
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in edges if e["from"] in node_ids or e["to"] in node_ids]
    # 若 SQLite 与内存均有，合并去重（以 SQLite 为准补充内存）
    if _sqlite_available and not subject:
        try:
            sg = sqlite_get_graph(None)
            if sg:
                # 合并
                existing_ids = {n["id"] for n in nodes}
                for n in sg.get("nodes", []):
                    if n["id"] not in existing_ids:
                        nodes.append(n)
                existing_edges = {(e["from"], e["to"]) for e in edges}
                for e in sg.get("edges", []):
                    if (e["from"], e["to"]) not in existing_edges:
                        edges.append(e)
        except Exception:
            pass
    return {"nodes": nodes, "edges": edges}


def search_prereqs(keyword: str, depth: int = 2) -> list[dict]:
    """多跳 BFS（2层深度），支持模糊匹配"""
    if not keyword:
        return []
    # 优先尝试 SQLite 的 BFS（已实现 2 层）
    if _sqlite_available:
        try:
            res = sqlite_search_prereqs(keyword, depth=depth)
            if res:
                return res
        except Exception:
            pass
    # 通用 BFS：基于 get_graph 的全图
    g = get_graph()
    edges = g.get("edges", [])
    nodes = g.get("nodes", [])
    if not edges:
        return []
    # 建图
    forward: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {}
    edge_map: dict[tuple[str, str], dict] = {}
    for e in edges:
        frm, to = e["from"], e["to"]
        forward.setdefault(frm, []).append(to)
        reverse.setdefault(to, []).append(frm)
        edge_map[(frm, to)] = e
    # 若 keyword 恰为节点名，BFS；否则模糊匹配包含 keyword 的节点
    start_nodes: list[str] = []
    if keyword in forward or keyword in reverse or any(n.get("name") == keyword for n in nodes):
        start_nodes = [keyword]
    else:
        # 模糊匹配
        matched = [n["name"] for n in nodes if keyword in n.get("name", "")]
        if matched:
            start_nodes = matched[:3]
        else:
            # 尝试边中包含关键字的
            for e in edges:
                if keyword in e["from"] or keyword in e["to"]:
                    return [e for e in edges if keyword in e["from"] or keyword in e["to"]][:10]
            return []
    visited_nodes: set[str] = set(start_nodes)
    visited_edges: set[tuple[str, str]] = set()
    queue: list[tuple[str, int]] = [(n, 0) for n in start_nodes]
    while queue:
        node, d = queue.pop(0)
        if d >= depth:
            continue
        for pre in reverse.get(node, []):
            key = (pre, node)
            visited_edges.add(key)
            if pre not in visited_nodes:
                visited_nodes.add(pre)
                queue.append((pre, d + 1))
        for nxt in forward.get(node, []):
            key = (node, nxt)
            visited_edges.add(key)
            if nxt not in visited_nodes:
                visited_nodes.add(nxt)
                queue.append((nxt, d + 1))
    res = []
    for frm, to in visited_edges:
        e = edge_map.get((frm, to))
        if e:
            res.append(e)
        else:
            res.append({"from": frm, "to": to, "type": "PREREQUISITE"})
    # 若 BFS 仍为空，退化为直接匹配
    if not res:
        res = [e for e in edges if e["from"] == keyword or e["to"] == keyword]
    return res


def get_subgraph(subject: str) -> dict:
    """API 子图：按 subject 过滤"""
    return get_graph(subject=subject)
