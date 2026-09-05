"""Pi 启示的类型安全工具注册表 - schema 校验 + before/after 钩子 + 结构化事件"""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


# ── 结构化事件类型（Pi 启示） ──────────────────────────────────

class AgentEventType(str, Enum):
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    THOUGHT = "thought"
    ERROR = "error"


@dataclass
class AgentEvent:
    type: AgentEventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_sse(self) -> dict[str, Any]:
        return {"event": self.type.value, "data": self.data, "id": self.event_id}


# ── Before/After 工具钩子（Pi 启示） ──────────────────────────

class BeforeToolCallResult(TypedDict, total=False):
    block: bool
    reason: str
    terminate: bool


class AfterToolCallResult(TypedDict, total=False):
    content: Any
    details: Any
    is_error: bool
    terminate: bool


BeforeToolHook = Callable[[str, dict, Any], BeforeToolCallResult | None]
AfterToolHook = Callable[[str, dict, Any, Any], AfterToolCallResult | None]


# ── 类型安全的工具定义（Pi 启示） ──────────────────────────────

@dataclass
class ToolSchema:
    """工具参数 schema，用于校验"""
    type: str = "object"
    properties: dict[str, dict[str, Any]] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)

    def validate(self, args: dict[str, Any]) -> list[str]:
        """校验参数，返回错误列表（空=通过）"""
        errors = []
        for r in self.required:
            if r not in args:
                errors.append(f"missing required: {r}")
        for k, v in args.items():
            if k in self.properties:
                expected = self.properties[k].get("type")
                if expected == "string" and not isinstance(v, str):
                    errors.append(f"{k}: expected string, got {type(v).__name__}")
                elif expected == "integer" and not isinstance(v, int):
                    errors.append(f"{k}: expected int, got {type(v).__name__}")
                elif expected == "number" and not isinstance(v, (int, float)):
                    errors.append(f"{k}: expected number, got {type(v).__name__}")
                elif expected == "boolean" and not isinstance(v, bool):
                    errors.append(f"{k}: expected bool, got {type(v).__name__}")
                elif expected == "array" and not isinstance(v, list):
                    errors.append(f"{k}: expected array, got {type(v).__name__}")
                elif expected == "object" and not isinstance(v, dict):
                    errors.append(f"{k}: expected object, got {type(v).__name__}")
        return errors


@dataclass
class RegisteredTool:
    name: str
    fn: Callable
    schema: ToolSchema | None = None
    label: str = ""
    description: str = ""

    def validate_args(self, args: dict[str, Any]) -> list[str]:
        if self.schema:
            return self.schema.validate(args)
        return []


# ── 注册表 ──────────────────────────────────────────────────────

_tools: dict[str, RegisteredTool] = {}
_before_hooks: list[BeforeToolHook] = []
_after_hooks: list[AfterToolHook] = []
_event_log: list[AgentEvent] = []


def register(name: str, schema: ToolSchema | None = None, label: str = "", description: str = ""):
    """装饰器注册工具，支持 schema 校验"""
    def deco(fn: Callable):
        _tools[name] = RegisteredTool(
            name=name, fn=fn, schema=schema,
            label=label or name, description=description,
        )
        return fn
    return deco


def get(name: str) -> Callable | None:
    """向后兼容：返回可直接 await 的 Callable（对标 Pi 直接 getTool 后调用）"""
    rt = _tools.get(name)
    return rt.fn if rt else None


def get_registered(name: str) -> RegisteredTool | None:
    """获取完整注册信息（含 schema/label）"""
    return _tools.get(name)


def get_spec(name: str) -> ToolSchema | None:
    rt = _tools.get(name)
    return rt.schema if rt else None


def list_tools() -> list[str]:
    return list(_tools.keys())


def list_tools_detailed() -> list[dict[str, Any]]:
    return [
        {"name": n, "label": rt.label, "description": rt.description, "schema": rt.schema}
        for n, rt in _tools.items()
    ]


def add_before_hook(hook: BeforeToolHook):
    _before_hooks.append(hook)


def add_after_hook(hook: AfterToolHook):
    _after_hooks.append(hook)


def emit_event(event: AgentEvent):
    """记录事件到日志"""
    _event_log.append(event)
    # 保留最近 200 条
    if len(_event_log) > 200:
        _event_log.pop(0)


def get_events(limit: int = 50) -> list[AgentEvent]:
    return _event_log[-limit:]


# ── 工具执行器（带 before/after 钩子 + schema 校验） ──────────

async def execute_tool(
    name: str,
    args: dict[str, Any],
    context: Any = None,
) -> dict[str, Any]:
    """执行工具，带完整生命周期：校验 → before → 执行 → after"""
    tool = _tools.get(name)
    if not tool:
        return {"error": f"tool not found: {name}", "is_error": True}

    event_id = str(uuid.uuid4())[:8]

    # 1. Schema 校验
    errors = tool.validate_args(args)
    if errors:
        emit_event(AgentEvent(
            type=AgentEventType.ERROR,
            data={"tool": name, "errors": errors, "event_id": event_id},
        ))
        return {"error": f"validation failed: {errors}", "is_error": True}

    # 2. Before hooks
    for hook in _before_hooks:
        try:
            result = hook(name, args, context)
            if result and result.get("block"):
                reason = result.get("reason", "blocked by policy")
                emit_event(AgentEvent(
                    type=AgentEventType.TOOL_CALL_END,
                    data={"tool": name, "blocked": True, "reason": reason, "event_id": event_id},
                ))
                return {"error": reason, "is_error": True, "blocked": True}
        except Exception:
            logger.warning("before hook failed for tool %s", name, exc_info=True)

    # 3. Emit tool_call_start
    emit_event(AgentEvent(
        type=AgentEventType.TOOL_CALL_START,
        data={"tool": name, "args": args, "event_id": event_id},
    ))

    # 4. Execute
    t0 = time.time()
    try:
        if callable(tool.fn) and _is_coroutine(tool.fn):
            result = await tool.fn(**args)
        else:
            result = tool.fn(**args)
        elapsed = time.time() - t0
    except Exception as e:
        elapsed = time.time() - t0
        logger.warning("tool %s execution failed", name, exc_info=True)
        emit_event(AgentEvent(
            type=AgentEventType.TOOL_CALL_END,
            data={"tool": name, "error": str(e), "elapsed": elapsed, "event_id": event_id},
        ))
        return {"error": str(e), "is_error": True}

    # 5. After hooks
    final_result = result
    for hook in _after_hooks:
        try:
            override = hook(name, args, context, result)
            if override:
                if "content" in override:
                    final_result = override["content"]
                if "is_error" in override:
                    final_result = {"result": final_result, "is_error": override["is_error"]}
        except Exception:
            logger.warning("after hook failed for tool %s", name, exc_info=True)

    # 6. Emit tool_call_end
    emit_event(AgentEvent(
        type=AgentEventType.TOOL_CALL_END,
        data={"tool": name, "result": str(final_result)[:200], "elapsed": elapsed, "event_id": event_id},
    ))

    return {"result": final_result, "is_error": False}


def _is_coroutine(fn) -> bool:
    import asyncio
    return asyncio.iscoroutinefunction(fn)


# ── 启动时加载 mcp.json + skills ──────────────────────────────

try:
    import json
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[5]
    _mcp_path = root / "mcp.json"
    if not _mcp_path.exists():
        _mcp_path = pathlib.Path("mcp.json")
    _mcp = json.loads(_mcp_path.read_text(encoding="utf-8"))
    for srv, cfg in _mcp.get("servers", {}).items():
        for tool in cfg.get("tools", []):
            _tools[f"mcp:{srv}:{tool}"] = RegisteredTool(
                name=f"mcp:{srv}:{tool}",
                fn=lambda *a, **kw: [],
                label=f"MCP: {srv}.{tool}",
            )
    _skills_dir = root / "skills"
    if not _skills_dir.exists():
        _skills_dir = pathlib.Path("skills")
    for skill_file in _skills_dir.glob("*/SKILL.md"):
        name = skill_file.parent.name
        if name not in _tools:
            _tools[name] = RegisteredTool(
                name=name,
                fn=lambda *a, **kw: [],
                label=f"Skill: {name}",
            )
except Exception:
    logger.warning("mcp.json / skills bootstrap failed", exc_info=True)


# ── 4 核心工具 ─────────────────────────────────────────────────

_ValidStatus = ("todo", "doing", "done", "delayed")


def _parse_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, str) and v.strip():
        dt = datetime.fromisoformat(v.strip())
    else:
        raise ValueError("invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _tool_error(msg: str, code: int) -> dict[str, Any]:
    return {"error": msg, "code": code, "is_error": True}


@register(
    "memory_search",
    schema=ToolSchema(
        properties={"query": {"type": "string"}, "top_k": {"type": "integer"}},
        required=["query"],
    ),
    label="记忆搜索",
    description="搜索用户长期记忆",
)
async def memory_search(query: str, top_k: int = 5, **kw) -> list[dict[str, Any]]:
    # H-07 修复：异步路径走 asearch_memory 以获真实 embedding（原 loop.is_running 时误走 hash mock）
    session = kw.get("session")
    user_id = kw.get("user_id", 1)
    if not session:
        return []
    try:
        from app.services.memory import asearch_memory as _asearch

        return await _asearch(session, user_id, query, top_k, type_="memory")
    except Exception:
        logger.warning("async memory search failed, fallback to sync", exc_info=True)
        from app.services.memory import search_memory as _search

        return _search(session, user_id, query, top_k, type_="memory")


@register(
    "rag_search",
    schema=ToolSchema(
        properties={"query": {"type": "string"}, "top_k": {"type": "integer"}},
        required=["query"],
    ),
    label="知识检索",
    description="检索 RAG 知识库",
)
async def rag_search(query: str, top_k: int = 10, **kw) -> list[dict[str, Any]]:
    session = kw.get("session")
    user_id = kw.get("user_id", 1)
    if not session:
        return []
    try:
        from app.services.memory import asearch_memory as _asearch

        return await _asearch(session, user_id, query, top_k, type_="knowledge")
    except Exception:
        logger.warning("async knowledge search failed, fallback to sync", exc_info=True)
        from app.services.memory import search_memory as _search

        return _search(session, user_id, query, top_k, type_="knowledge")


@register(
    "graph_search",
    schema=ToolSchema(
        properties={"query": {"type": "string"}},
        required=["query"],
    ),
    label="图谱查询",
    description="查询知识图谱前置关系",
)
async def graph_search(query: str, **kw) -> list[dict[str, Any]]:
    from app.graph.neo import search_prereqs
    return search_prereqs(query)


@register(
    "write_tasks",
    schema=ToolSchema(
        properties={"tasks": {"type": "array"}},
        required=["tasks"],
    ),
    label="写入任务",
    description="将规划任务写入数据库",
)
async def write_tasks(tasks: list[dict[str, Any]], **kw) -> list[dict[str, Any]] | dict[str, Any]:
    from sqlmodel import Session, select

    from app.core.database import engine
    from app.models.goal import LearningGoal
    from app.models.task import Task

    session: Session | None = kw.get("session")
    user_id = kw.get("user_id", 1)
    if not isinstance(tasks, list) or not tasks:
        return _tool_error("tasks不能为空", 40001)
    if len(tasks) > 50:
        return _tool_error("批量最多50条", 40001)

    parsed: list[dict[str, Any]] = []
    seen: set[tuple[int, str, datetime]] = set()
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            return _tool_error(f"tasks[{i}]必须为对象", 40001)
        goal_id = t.get("goal_id")
        title = t.get("title")
        if not isinstance(goal_id, int) or isinstance(goal_id, bool):
            return _tool_error(f"tasks[{i}].goal_id必须为整数", 40001)
        if not isinstance(title, str) or not title.strip():
            return _tool_error(f"tasks[{i}].title必填", 40001)
        try:
            start = _parse_dt(t.get("planned_start"))
            end = _parse_dt(t.get("planned_end"))
        except (TypeError, ValueError):
            return _tool_error(f"tasks[{i}].planned_start/planned_end时间格式非法", 40001)
        if end <= start:
            return _tool_error(f"tasks[{i}]: planned_end必须大于planned_start", 40001)
        title = title.strip()
        priority = t.get("priority", 3)
        if not isinstance(priority, int) or isinstance(priority, bool) or not (1 <= priority <= 5):
            return _tool_error(f"tasks[{i}].priority须为1-5", 40001)
        status = t.get("status") or "todo"
        if status not in _ValidStatus:
            return _tool_error(f"tasks[{i}].status非法", 40001)
        key = (goal_id, title, start)
        if key in seen:
            continue
        seen.add(key)
        parsed.append({
            "goal_id": goal_id,
            "title": title,
            "start": start,
            "end": end,
            "priority": priority,
            "status": status,
            "source_agent": t.get("source_agent"),
            "citations": t.get("citations"),
        })

    own_session = session is None
    if session is None:
        session = Session(engine)
    try:
        goals: dict[int, LearningGoal] = {}
        for p in parsed:
            gid = p["goal_id"]
            if gid not in goals:
                goals[gid] = session.get(LearningGoal, gid)
            goal = goals[gid]
            if not goal or goal.user_id != user_id:
                return _tool_error("目标不存在或无权限", 40401)
        created: list[Task] = []
        for p in parsed:
            exists = session.exec(
                select(Task).where(
                    Task.goal_id == p["goal_id"],
                    Task.title == p["title"],
                    Task.planned_start == p["start"],
                )
            ).first()
            if exists:
                continue
            row = Task(
                goal_id=p["goal_id"],
                title=p["title"],
                planned_start=p["start"],
                planned_end=p["end"],
                priority=p["priority"],
                status=p["status"],
                source_agent=p["source_agent"],
                citations=p["citations"],
            )
            session.add(row)
            created.append(row)
        session.commit()
        for row in created:
            session.refresh(row)
        return [r.model_dump() for r in created]
    finally:
        if own_session and session is not None:
            session.close()
