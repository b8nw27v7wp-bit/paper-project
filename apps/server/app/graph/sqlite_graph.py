"""SQLite 图谱持久化：knowledge_nodes + knowledge_edges"""
import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "graph.db"
# P1懒加载：import时不建库，首次调用经_ensure_db建库（原import期_init_db改延迟）
_DB_INIT_DONE = False


def _get_conn():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # M9：WAL 正常，连接 timeout 加大到 30s（原 5s 高并发易 locked 直抛）；busy_timeout 同步加大。
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # H-03: 启用 WAL 与 busy_timeout 降低并发锁（sqlite 默认 DELETE 模式易 database is locked）
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except sqlite3.Error:
        logger.warning("sqlite pragma setup failed", exc_info=True)
    return conn


def _with_retry(fn, *, attempts: int = 5, base_ms: float = 50.0):
    """M9：写操作指数退避恢复（database is locked 直抛改重试；确认原 _with_retry 已删除，此处恢复）。

    - 仅对 sqlite3.OperationalError 且 message 含 locked/busy 重试；
    - 退避 base_ms*2^n（50/100/200/400/800ms），耗尽后原错上抛；
    - 读路径不走重试（直连+WAL 足够），仅写路径（upsert/add_edge/clear）使用。
    """
    last: Exception | None = None
    for i in range(max(1, int(attempts))):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            last = e
            try:
                _msg = str(e).lower()
            except Exception:
                _msg = ""
            if "locked" not in _msg and "busy" not in _msg:
                raise
            if i >= max(1, int(attempts)) - 1:
                raise
            try:
                time.sleep((float(base_ms) * (2**i)) / 1000.0)
            except Exception:
                pass
        except Exception:
            raise
    if last is not None:
        raise last


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


def _ensure_db():
    """首次调用懒加载建库（import期不触DB，兼容只读导入与测试隔离）"""
    global _DB_INIT_DONE
    if _DB_INIT_DONE:
        return
    try:
        _init_db()
    except Exception:
        logger.warning("sqlite graph lazy init failed", exc_info=True)
    finally:
        _DB_INIT_DONE = True


def sqlite_upsert_node(name: str, subject: str | None = None):
    _ensure_db()
    if not name or not name.strip():
        return
    name = name.strip()
    subject = (subject or "通用").strip()

    def _op():
        conn = _get_conn()
        try:
            cur = conn.cursor()
            # 存在则更新 subject（若原为通用且新非通用）
            cur.execute("SELECT subject FROM knowledge_nodes WHERE name=?", (name,))
            row = cur.fetchone()
            if row is None:
                cur.execute("INSERT INTO knowledge_nodes (name, subject) VALUES (?, ?)", (name, subject))
            else:
                # 与内存图对齐：仅当原 subject 为通用/空且新 subject 更具体时更新，避免跨学科覆盖
                old = (row["subject"] or "").strip() if row["subject"] else ""
                if old != subject and subject != "通用" and old in ("", "通用"):
                    cur.execute("UPDATE knowledge_nodes SET subject=? WHERE name=?", (subject, name))
            conn.commit()
        finally:
            conn.close()

    return _with_retry(_op)


def sqlite_add_edge(frm: str, to: str, type_: str = "PREREQUISITE"):
    _ensure_db()
    if not frm or not to or frm == to:
        return
    frm = frm.strip()
    to = to.strip()

    def _op():
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

    return _with_retry(_op)


def sqlite_get_graph(subject: str | None = None) -> dict:
    _ensure_db()
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
    _ensure_db()

    def _op():
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM knowledge_edges")
            cur.execute("DELETE FROM knowledge_nodes")
            conn.commit()
        finally:
            conn.close()

    return _with_retry(_op)
