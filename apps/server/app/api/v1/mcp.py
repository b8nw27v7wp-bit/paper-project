from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.deps import get_current_user_id
from app.mcp.client import call_tool, list_servers, list_tools

router = APIRouter()

class CallRequest(BaseModel):
    server: str
    tool: str
    args: dict[str, Any]

@router.get("/mcp/servers")
def get_servers():
    return {"code": 200, "msg": "ok", "data": list_servers()}


@router.get("/mcp/tools")
def get_tools():
    return {"code": 200, "msg": "ok", "data": list_tools()}


@router.post("/mcp/call")
async def mcp_call(payload: CallRequest, user_id: int = Depends(get_current_user_id)):
    try:
        res = await call_tool(payload.server, payload.tool, payload.args)
        return {"code": 200, "msg": "ok", "data": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": 50002, "msg": f"MCP失败: {e}"})
