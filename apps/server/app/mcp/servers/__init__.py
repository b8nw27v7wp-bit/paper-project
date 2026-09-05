"""本地真 MCP server 集合（stdio 传输，python -m 启动）

- calendar: create_event / list_events，SQLite(WAL) 存储
- todo:     create_todo / complete_todo，SQLite(WAL) 存储
- search:   web_search，本地确定性检索（不接外网）

由 apps/server/mcp.json 以 {"command":"py","args":["-m","app.mcp.servers.<name>"],"cwd":"apps/server"}
经 app/mcp/client.py:_call_once (StdioServerParameters + stdio_client) 拉起。
"""
