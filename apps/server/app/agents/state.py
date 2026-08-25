from typing import Any, TypedDict

try:
    from typing import NotRequired  # py311+
except ImportError:
    from typing_extensions import NotRequired  # type: ignore


class PlanState(TypedDict, total=False):
    goal: dict[str, Any]
    memory: list[dict[str, Any]]
    graphDeps: list[dict[str, Any]]
    vectorDeps: list[dict[str, Any]]
    milestones: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    critic_feedback: str
    mentor_msg: str
    rewrites: int
    trace_id: str
    preferences: dict[str, Any]
    _thought: str
    _research: dict[str, Any]
    _patch: dict[str, Any]
    terminate: bool
    # 供 researcher 工具调用的上下文（可选）
    _session: Any
    session: Any
    user_id: int
