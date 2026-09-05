"""SQLite 图谱持久化：knowledge_nodes + knowledge_edges"""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "graph.db"


def _get_conn():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # H-03: 启用 WAL 与 busy_timeout 降低并发锁（sqlite 默认 DELETE 模式易 database is locked）
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
    except sqlite3.Error:
        logger.warning("sqlite pragma setup failed", exc_info=True)
    return conn


def _with_retry(func, *args, max_retries: int = 3, **kwargs):
    """SQLite busy 重试（H-03）"""
    import time

    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries:
                time.sleep(0.1 * (2**attempt))
                continue
            raise
    return func(*args, **kwargs)


def _init_db():
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                subject TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_node TEXT NOT NULL,
                to_node TEXT NOT NULL,
                type TEXT DEFAULT 'PREREQUISITE',
                UNIQUE(from_node, to_node)
            )
            """
        )
        # 索引
        cur.execute("CREATE INDEX IF NOT EXISTS idx_nodes_subject ON knowledge_nodes(subject)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_from ON knowledge_edges(from_node)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_to ON knowledge_edges(to_node)")
        conn.commit()
    finally:
        conn.close()


_init_db()


def sqlite_upsert_node(name: str, subject: str | None = None):
    if not name or not name.strip():
        return
    name = name.strip()
    subject = (subject or "通用").strip()
    conn = _get_conn()
    try:
        cur = conn.cursor()
        # 存在则更新 subject（若原为通用且新非通用）
        cur.execute("SELECT subject FROM knowledge_nodes WHERE name=?", (name,))
        row = cur.fetchone()
        if row is None:
            cur.execute("INSERT INTO knowledge_nodes (name, subject) VALUES (?, ?)", (name, subject))
        else:
            # 若已有 subject 且新 subject 不同且非通用，可更新
            if row["subject"] != subject and subject != "通用":
                cur.execute("UPDATE knowledge_nodes SET subject=? WHERE name=?", (subject, name))
        conn.commit()
    finally:
        conn.close()


def sqlite_add_edge(frm: str, to: str, type_: str = "PREREQUISITE"):
    if not frm or not to or frm == to:
        return
    frm = frm.strip()
    to = to.strip()
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO knowledge_edges (from_node, to_node, type) VALUES (?, ?, ?)",
            (frm, to, type_),
        )
        conn.commit()
    finally:
        conn.close()


def sqlite_get_graph(subject: str | None = None) -> dict:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        if subject:
            # 节点过滤
            cur.execute("SELECT id, name, subject FROM knowledge_nodes WHERE subject=?", (subject,))
            nodes_rows = cur.fetchall()
            nodes = [{"id": r["name"], "name": r["name"], "subject": r["subject"]} for r in nodes_rows]
            node_ids = {n["id"] for n in nodes}
            # 边：保留至少一端在 subject 子图中的边
            cur.execute("SELECT from_node, to_node, type FROM knowledge_edges")
            all_edges = cur.fetchall()
            edges = []
            for r in all_edges:
                if r["from_node"] in node_ids or r["to_node"] in node_ids:
                    edges.append({"from": r["from_node"], "to": r["to_node"], "type": r["type"]})
            # 若节点为空但有边关联 subject 关键词，也返回相关节点
            if not nodes and edges:
                # 补充节点
                names = set()
                for e in edges:
                    names.add(e["from"])
                    names.add(e["to"])
                for n in names:
                    cur.execute("SELECT name, subject FROM knowledge_nodes WHERE name=?", (n,))
                    rr = cur.fetchone()
                    if rr:
                        nodes.append({"id": rr["name"], "name": rr["name"], "subject": rr["subject"]})
                    else:
                        nodes.append({"id": n, "name": n, "subject": subject})
            return {"nodes": nodes, "edges": edges}
        else:
            cur.execute("SELECT id, name, subject FROM knowledge_nodes")
            nodes = [{"id": r["name"], "name": r["name"], "subject": r["subject"]} for r in cur.fetchall()]
            cur.execute("SELECT from_node, to_node, type FROM knowledge_edges")
            edges = [{"from": r["from_node"], "to": r["to_node"], "type": r["type"]} for r in cur.fetchall()]
            return {"nodes": nodes, "edges": edges}
    finally:
        conn.close()


def sqlite_search_prereqs(keyword: str, depth: int = 2) -> list[dict]:
    """BFS 多跳检索（2层深度）"""
    if not keyword:
        return []
    g = sqlite_get_graph()
    edges = g["edges"]
    # 构建邻接表：from -> [to] ，以及反向 to -> [from]（前置）
    forward: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {}
    edge_map: dict[tuple[str, str], dict] = {}
    for e in edges:
        frm, to = e["from"], e["to"]
        forward.setdefault(frm, []).append(to)
        reverse.setdefault(to, []).append(frm)
        edge_map[(frm, to)] = e
    # BFS 从 keyword 出发，双向最多 depth 层
    visited_nodes = set([keyword])
    visited_edges_set: set[tuple[str, str]] = set()
    queue: list[tuple[str, int]] = [(keyword, 0)]
    # 为支持反向前置，需同时遍历两个方向
    while queue:
        node, d = queue.pop(0)
        if d >= depth:
            continue
        # 前置（反向）
        for pre in reverse.get(node, []):
            key = (pre, node)
            if key not in visited_edges_set:
                visited_edges_set.add(key)
            if pre not in visited_nodes:
                visited_nodes.add(pre)
                queue.append((pre, d + 1))
        # 后继（正向）
        for nxt in forward.get(node, []):
            key = (node, nxt)
            if key not in visited_edges_set:
                visited_edges_set.add(key)
            if nxt not in visited_nodes:
                visited_nodes.add(nxt)
                queue.append((nxt, d + 1))
    # 额外：若 keyword 未命中任何节点，尝试模糊匹配节点名包含 keyword
    if not visited_edges_set:
        # 模糊匹配
        matched = [n["name"] for n in g["nodes"] if keyword in n["name"]]
        for m in matched[:3]:
            # 将 matched 节点的直接边加入
            for e in edges:
                if e["from"] == m or e["to"] == m:
                    visited_edges_set.add((e["from"], e["to"]))
    # 转为 list[dict]
    res = []
    for frm, to in visited_edges_set:
        e = edge_map.get((frm, to))
        if e:
            res.append(e)
        else:
            res.append({"from": frm, "to": to, "type": "PREREQUISITE"})
    return res


def sqlite_clear():
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM knowledge_edges")
        cur.execute("DELETE FROM knowledge_nodes")
        conn.commit()
    finally:
        conn.close()
