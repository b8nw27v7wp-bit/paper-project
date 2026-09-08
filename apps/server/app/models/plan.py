
from pydantic import BaseModel


class PlanCreate(BaseModel):
    goal_id: int
    preferences: dict | None = None  # {hours_per_day:1-8, preferred_time}
    require_approval: bool = False  # 写库审批网关：仅 multi 模式生效，默认 False 保持旧流程


class ApproveRequest(BaseModel):
    approved: bool
    token: str

class PlanResponse(BaseModel):
    trace_id: str
    tasks: list
    mentor_msg: str
    citations: list = []
