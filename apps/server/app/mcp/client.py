import asyncio
import json

# Mock MCP client - P2演示，真实MCP用 stdio 调 calendar-mcp
SERVERS = {
    "calendar": {"status": "running", "tools": ["create_calendar_event"]},
    "todo": {"status": "running", "tools": ["create_todo"]},
}

async def call_tool(server: str, tool: str, args: dict, timeout: float = 5.0) -> dict:
    # 模拟 100ms 延迟，成功率>95% 的 mock
    await asyncio.sleep(0.05)
    if server not in SERVERS:
        raise RuntimeError(f"server {server} not found")
    if tool not in SERVERS[server]["tools"]:
        raise RuntimeError(f"tool {tool} not found")
    # 超时重试已在上游，这里直接成功
    # 模拟 event_id
    import uuid
    return {"event_id": str(uuid.uuid4()), "result": {"ok": True, "server": server, "tool": tool, "args": args}}

def list_servers():
    return [{"name": k, "status": v["status"]} for k, v in SERVERS.items()]
