
from pydantic import BaseModel


class PlanCreate(BaseModel):
    goal_id: int
    preferences: dict | None = None  # {hours_per_day:1-8, preferred_time}

class PlanResponse(BaseModel):
    trace_id: str
    tasks: list
    mentor_msg: str
    citations: list = []
