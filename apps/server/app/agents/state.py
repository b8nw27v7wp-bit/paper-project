from typing import TypedDict, Optional

class PlanState(TypedDict):
    goal: dict
    memory: list
    graphDeps: list
    vectorDeps: list
    milestones: list
    tasks: list
    critic_feedback: str
    mentor_msg: str
    rewrites: int
    trace_id: str
    preferences: dict
