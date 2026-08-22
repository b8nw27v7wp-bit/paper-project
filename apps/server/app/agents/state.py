from typing import TypedDict

class PlanState(TypedDict):
    goal: dict
    memory: list
    graphDeps: list
    vectorDeps: list
    milestones: list
    tasks: list
    critic_feedback: str
    mentor_msg: str
