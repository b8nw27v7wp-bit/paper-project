"""calendar 真 MCP server — stdio 传输，SQLite(WAL) 存储

启动: py -m app.mcp.servers.calendar （cwd=apps/server，见仓库根 mcp.json）
工具: create_event / list_events
返回结构与 app/mcp/client.py 的 Mock 版本字段兼容：
  create_event -> event_id/id/result/server/tool/title/start/end
  list_events  -> events/result/count/queried_at
数据库固定落 apps/server/data/mcp_calendar.db（基于本文件路径定位，与启动 cwd 无关）。
"""
from __future__ import annotations

import pathlib
import sqlite3
import time
import uuid

from mcp.server.mcpserver import MCPServer

# 数据库路径：apps/server/data/mcp_calendar.db（parents[3] = apps/server）
_DB = pathlib.Path(__file__).resolve().parents[3] / "data" / "mcp_calendar.db"
_DB.parent.mkdir(parents=True, exist_ok=True)

server = MCPServer(name="calendar", version="0.1.0")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB, timeout=5.0)
    # WAL 模式 + busy_timeout，避免并发读写锁定
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _execute(sql: str, params: tuple = ()) -> list[tuple]:
    conn = _conn()
    try:
        with conn:
            cur = conn.execute(sql, params)
            if cur.description:
                return cur.fetchall()
            return []
    finally:
        conn.close()


def _init() -> None:
    _execute(
        "CREATE TABLE IF NOT EXISTS events ("
        " id TEXT PRIMARY KEY, title TEXT NOT NULL, start TEXT, end TEXT,"
        " created_at TEXT NOT NULL)"
    )


_init()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@server.tool(name="create_event", description="创建日历事件（SQLite 持久化）")
def create_event(title: str = "Event", start: str | None = None, end: str | None = None) -> dict:
    eid = str(uuid.uuid4())
    _execute(
        "INSERT INTO events (id, title, start, end, created_at) VALUES (?, ?, ?, ?, ?)",
        (eid, title, start, end, _now()),
    )
    return {
        "event_id": eid,
        "id": eid,
        "result": {"ok": True, "server": "calendar", "tool": "create_event"},
        "server": "calendar",
        "tool": "create_event",
        "title": title,
        "start": start,
        "end": end,
    }


@server.tool(name="list_events", description="列出日历事件（SQLite，按创建时间倒序）")
def list_events(limit: int = 20) -> dict:
    rows = _execute(
        "SELECT id, title, start, end FROM events ORDER BY created_at DESC LIMIT ?",
        (max(1, int(limit)),),
    )
    events = [{"id": r[0], "title": r[1], "start": r[2], "end": r[3]} for r in rows]
    return {
        "events": events,
        "result": {"ok": True, "server": "calendar", "tool": "list_events"},
        "count": len(events),
        "queried_at": _now(),
    }


if __name__ == "__main__":
    # mcp 2.x: MCPServer.run(transport="stdio") 默认 stdio 传输
    server.run()
