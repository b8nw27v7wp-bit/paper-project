from typing import List, Dict, Tuple
from collections import defaultdict

# 内存图（Neo4j不可用时回退）
_mem_nodes: Dict[str, Dict] = {}
_mem_edges: List[Dict] = []

def _mem_upsert_knowledge(name: str, subject: str | None = None):
    if name not in _mem_nodes:
        _mem_nodes[name] = {"id": name, "name": name, "subject": subject or "通用"}

def _mem_add_edge(frm: str, to: str, type_: str = "PREREQUISITE"):
    if not any(e["from"]==frm and e["to"]==to for e in _mem_edges):
        _mem_edges.append({"from": frm, "to": to, "type": type_})

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

async def add_triples(triples: List[Tuple[str,str,str]], subject: str | None = None):
    # 先写内存
    for frm, _, to in triples:
        _mem_upsert_knowledge(frm, subject)
        _mem_upsert_knowledge(to, subject)
        _mem_add_edge(frm, to)
    # 再试Neo4j
    driver = _get_driver()
    if not driver:
        return
    try:
        with driver.session() as sess:
            for frm, _, to in triples:
                sess.run("MERGE (a:Knowledge {name:$frm}) ON CREATE SET a.subject=$subj", frm=frm, subj=subject or "通用")
                sess.run("MERGE (a:Knowledge {name:$to}) ON CREATE SET a.subject=$subj", to=to, subj=subject or "通用")
                sess.run("MATCH (a:Knowledge {name:$frm}), (b:Knowledge {name:$to}) MERGE (a)-[:PREREQUISITE]->(b)", frm=frm, to=to)
    except Exception:
        pass

def get_graph(subject: str | None = None) -> Dict:
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
                    nodes[frm] = {"id": frm, "name": frm}
                    nodes[to] = {"id": to, "name": to}
                    edges.append({"from": frm, "to": to, "type": rec["type"]})
                if nodes:
                    return {"nodes": list(nodes.values()), "edges": edges}
        except Exception:
            pass
    # 回退内存
    nodes = list(_mem_nodes.values())
    edges = _mem_edges
    if subject:
        # 过滤
        nodes = [n for n in nodes if n.get("subject")==subject]
        # edges 过滤保留两端均在nodes中的
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in edges if e["from"] in node_ids or e["to"] in node_ids]
    return {"nodes": nodes, "edges": edges}

def search_prereqs(keyword: str) -> List[Dict]:
    # 查找keyword的前置
    g = get_graph()
    # 简单BFS：找指向keyword的
    res = []
    for e in g["edges"]:
        if e["to"] == keyword or e["from"] == keyword:
            res.append(e)
    return res
