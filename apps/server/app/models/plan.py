from pydantic import BaseModel
from typing import Optional, Any

class PlanCreate(BaseModel):
    goal_id: int
    preferences: Optional[dict] = None  # {hours_per_day:1-8, preferred_time}

class PlanResponse(BaseModel):
    trace_id: str
    tasks: list
    mentor_msg: str
    citations: list = []
