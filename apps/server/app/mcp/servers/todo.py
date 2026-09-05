"""todo 真 MCP server — stdio 传输，SQLite(WAL) 存储

启动: py -m app.mcp.servers.todo （cwd=apps/server，见仓库根 mcp.json）
工具: create_todo / complete_todo（与 mock 版工具集一致）
返回结构与 app/mcp/client.py 的 Mock 版本字段兼容：
  create_todo   -> todo_id/id/event_id/result/server/tool/title
  complete_todo -> todo_id/result/server/tool/completed
数据库固定落 apps/server/data/mcp_todo.db（基于本文件路径定位，与启动 cwd 无关）。
"""
from __future__ import annotations

import pathlib
import sqlite3
import time
import uuid

from mcp.server.mcpserver import MCPServer

# 数据库路径：apps/server/data/mcp_todo.db（parents[3] = apps/server）
_DB = pathlib.Path(__file__).resolve().parents[3] / "data" / "mcp_todo.db"
_DB.parent.mkdir(parents=True, exist_ok=True)

server = MCPServer(name="todo", version="0.1.0")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB, timeout=5.0)
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
        "CREATE TABLE IF NOT EXISTS todos ("
        " id TEXT PRIMARY KEY, title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL, completed_at TEXT)"
    )


_init()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@server.tool(name="create_todo", description="创建待办事项（SQLite 持久化）")
def create_todo(title: str = "Todo") -> dict:
    tid = str(uuid.uuid4())
    _execute(
        "INSERT INTO todos (id, title, done, created_at) VALUES (?, ?, 0, ?)",
        (tid, title, _now()),
    )
    return {
        "todo_id": tid,
        "id": tid,
        "event_id": tid,  # 兼容部分调用者期望 event_id（与 Mock 一致）
        "result": {"ok": True, "server": "todo", "tool": "create_todo"},
        "server": "todo",
        "tool": "create_todo",
        "title": title,
    }


@server.tool(name="complete_todo", description="完成待办事项（SQLite 持久化）")
def complete_todo(todo_id: str = "") -> dict:
    tid = todo_id or ""
    found = False
    if tid:
        rows = _execute("SELECT id FROM todos WHERE id = ?", (tid,))
        if rows:
            _execute(
                "UPDATE todos SET done = 1, completed_at = ? WHERE id = ?",
                (_now(), tid),
            )
            found = True
    return {
        "todo_id": tid or str(uuid.uuid4()),
        "result": {"ok": True, "server": "todo", "tool": "complete_todo"},
        "server": "todo",
        "tool": "complete_todo",
        "completed": found,
        "found": found,
    }


if __name__ == "__main__":
    server.run()
