from typing import Any, TypedDict


class PlanState(TypedDict, total=False):
    goal: dict[str, Any]
    memory: list[dict[str, Any]]
    graphDeps: list[dict[str, Any]]
    vectorDeps: list[dict[str, Any]]
    milestones: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    critic_feedback: str
    mentor_msg: str
    _review: dict[str, Any]
    rewrites: int
    trace_id: str
    preferences: dict[str, Any]
    _thought: str
    _research: dict[str, Any]
    _patch: dict[str, Any]
    terminate: bool
    # critic LLM 降级标记（llm:degraded），需透传避免图合并丢失
    llm: str
    # 供 researcher 工具调用的上下文（可选）
    _session: Any
    session: Any
    user_id: int
