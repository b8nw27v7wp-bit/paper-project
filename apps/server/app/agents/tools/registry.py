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
                elif expected == "integer" and (not isinstance(v, int) or isinstance(v, bool)):
                    errors.append(f"{k}: expected int, got {type(v).__name__}")
                elif expected == "number" and (not isinstance(v, (int, float)) or isinstance(v, bool)):
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
    prepare_arguments: Callable | None = None
    execution_mode: str = "parallel"

    def validate_args(self, args: dict[str, Any]) -> list[str]:
        if self.schema:
            return self.schema.validate(args)
        return []


# ── 注册表 ──────────────────────────────────────────────────────

_tools: dict[str, RegisteredTool] = {}
_before_hooks: list[BeforeToolHook] = []
_after_hooks: list[AfterToolHook] = []
_event_log: list[AgentEvent] = []
# S5 前置占位工具 frontmatter 诊断：tool名 -> 缺失项列表（空表=正常）
_tool_diagnostics: dict[str, list[str]] = {}


def register(name: str, schema: ToolSchema | None = None, label: str = "", description: str = "", prepare_arguments: Callable | None = None, execution_mode: str = "parallel"):
    """装饰器注册工具，支持 schema 校验"""
    def deco(fn: Callable):
        _tools[name] = RegisteredTool(
            name=name, fn=fn, schema=schema,
            label=label or name, description=description,
            prepare_arguments=prepare_arguments, execution_mode=execution_mode,
        )
        return fn
    return deco


def get(name: str) -> Callable | None:
    """Deprecated: 请改用 execute_tool(name, args) 以走 schema/hook/事件生命周期。

    保留兼容：仍返回可直接 await 的 Callable（对标 Pi 直接 getTool 后调用），
    但不再推荐，新代码必须走 execute_tool。
    """
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
        {"name": n, "label": rt.label, "description": rt.description, "schema": rt.schema,
         "execution_mode": getattr(rt, "execution_mode", "parallel"),
         "diagnostics": list(_tool_diagnostics.get(n, []))}
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

    # 0. S4 别名归一（prepare_arguments，失败回退原args；恒等默认=None）
    try:
        _prep = getattr(tool, "prepare_arguments", None)
        if _prep is not None and isinstance(args, dict):
            _maybe = _prep(dict(args))
            if isinstance(_maybe, dict):
                args = _maybe
    except Exception:
        logger.warning("prepare_arguments failed for tool %s, fallback original", name, exc_info=True)

    # 1. Schema 校验
    errors = tool.validate_args(args)
    if errors:
        emit_event(AgentEvent(
            type=AgentEventType.ERROR,
            data={"tool": name, "errors": errors, "event_id": event_id},
            event_id=event_id,
        ))
        return {"error": f"validation failed: {errors}", "is_error": True}

    # 2. Before hooks（S1 多hook语义：单个block仅该工具失败返回；Pi every()对标：
    #  全员terminate==true才标注terminated。返回None按False计（与Pi finalized缺省false一致），
    #  常驻hook（如审批guard对非write_tasks返回None）天然参与共识——terminate是强停批信号，
    #  需全链共识，单测须隔离hook表（见test_registry_lifecycle）。）
    _before_terminates: list[bool] = []
    _block_reason: str | None = None
    for hook in _before_hooks:
        try:
            result = hook(name, args, context)
            if result and result.get("block") and _block_reason is None:
                _block_reason = result.get("reason", "blocked by policy")
            if result is not None:
                _before_terminates.append(bool(result.get("terminate")))
            else:
                _before_terminates.append(False)
        except Exception:
            logger.warning("before hook failed for tool %s", name, exc_info=True)
            _before_terminates.append(False)
    _before_all_terminate = bool(_before_hooks) and len(_before_terminates) == len(_before_hooks) and all(_before_terminates)
    if _block_reason is not None:
        _bdata: dict[str, Any] = {"tool": name, "blocked": True, "reason": _block_reason, "event_id": event_id}
        if _before_all_terminate:
            _bdata["terminated"] = True
        emit_event(AgentEvent(
            type=AgentEventType.TOOL_CALL_END,
            data=_bdata,
            event_id=event_id,
        ))
        _bret: dict[str, Any] = {"error": _block_reason, "is_error": True, "blocked": True}
        if _before_all_terminate:
            _bret["terminated"] = True
        return _bret

    # 3. Emit tool_call_start
    emit_event(AgentEvent(
        type=AgentEventType.TOOL_CALL_START,
        data={"tool": name, "args": args, "event_id": event_id},
        event_id=event_id,
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
            event_id=event_id,
        ))
        return {"error": str(e), "is_error": True}

    # 5. After hooks（S1 透传 details/usage/terminate；AfterToolCallResult四字段已含content/details/is_error/terminate，usage按duck-typing透传）
    final_result = result
    _after_details: dict[str, Any] = {}
    _after_usage: dict[str, Any] = {}
    _after_terminate = False
    _after_is_error: bool | None = None
    for hook in _after_hooks:
        try:
            override = hook(name, args, context, result)
            if override:
                if "content" in override:
                    # Pi对标(agent-loop finalize)：字段级合并而非整体替换，保留原result其他键
                    _nc = override["content"]
                    if isinstance(final_result, dict) and isinstance(_nc, dict):
                        final_result = {**final_result, **_nc}
                    else:
                        final_result = _nc
                if "is_error" in override:
                    final_result = {"result": final_result, "is_error": override["is_error"]}
                    _after_is_error = bool(override["is_error"])
                _d = override.get("details")
                if isinstance(_d, dict):
                    _after_details.update(_d)
                elif _d is not None:
                    _after_details["value"] = _d
                _u = override.get("usage")
                if isinstance(_u, dict):
                    _after_usage.update(_u)
                elif _u is not None:
                    _after_usage["value"] = _u
                if override.get("terminate"):
                    _after_terminate = True
        except Exception:
            logger.warning("after hook failed for tool %s", name, exc_info=True)
    # S1 usage并入result字典：dict则update usage键，否则包一层
    if _after_usage:
        if isinstance(final_result, dict):
            if isinstance(final_result.get("usage"), dict):
                _merged = dict(final_result["usage"])
                _merged.update(_after_usage)
                final_result = {**final_result, "usage": _merged}
            else:
                final_result = {**final_result, "usage": dict(_after_usage)}
        else:
            final_result = {"result": final_result, "usage": dict(_after_usage)}

    # 6. Emit tool_call_end（S1 details并入data，terminate收集）
    _terminated = bool(_before_all_terminate or _after_terminate)
    _end_data: dict[str, Any] = {"tool": name, "result": str(final_result)[:200], "elapsed": elapsed, "event_id": event_id}
    if _after_details:
        _end_data.update(_after_details)
        _end_data["details"] = dict(_after_details)
    if _after_usage:
        _end_data["usage"] = dict(_after_usage)
    if _terminated:
        _end_data["terminated"] = True
    emit_event(AgentEvent(
        type=AgentEventType.TOOL_CALL_END,
        data=_end_data,
        event_id=event_id,
    ))

    _out: dict[str, Any] = {"result": final_result, "is_error": bool(_after_is_error) if _after_is_error is not None else False}
    if _after_details:
        _out["details"] = dict(_after_details)
    if _after_usage:
        _out["usage"] = dict(_after_usage)
    if _terminated:
        _out["terminated"] = True
    return _out


def _is_coroutine(fn) -> bool:
    import inspect
    return inspect.iscoroutinefunction(fn)


def _parse_skill_frontmatter(text: str) -> tuple[dict[str, str], list[str]]:
    """S5 frontmatter校验：读SKILL.md首段---块解析name/description，返回(fields, missing)。"""
    try:
        stripped = text.lstrip("\ufeff \t\r\n")
        if not stripped.startswith("---"):
            return {}, ["missing frontmatter --- block"]
        rest = stripped[3:]
        end_idx = rest.find("---")
        if end_idx == -1:
            return {}, ["missing closing --- for frontmatter"]
        block = rest[:end_idx]
        fields: dict[str, str] = {}
        for line in block.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if ":" in s:
                k, v = s.split(":", 1)
                fields[k.strip()] = v.strip().strip("'\"")
        missing: list[str] = []
        if not fields.get("name"):
            missing.append("missing frontmatter field: name")
        if not fields.get("description"):
            missing.append("missing frontmatter field: description")
        return fields, missing
    except Exception as e:
        return {}, [f"frontmatter parse failed: {e}"]


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
        try:
            _txt = skill_file.read_text(encoding="utf-8")
            _, _miss = _parse_skill_frontmatter(_txt)
            if _miss:
                _tool_diagnostics.setdefault(name, []).extend(_miss)
            else:
                _tool_diagnostics.setdefault(name, [])
        except Exception:
            logger.warning("skill frontmatter read failed: %s", skill_file, exc_info=True)
            _tool_diagnostics.setdefault(name, []).append("SKILL.md read failed")
        if name in _tools:
            # Pi对标(skills.ts)：同名碰撞记diagnostics而非静默丢弃
            _tool_diagnostics.setdefault(name, []).append(f"skill name collision: kept existing tool '{name}'")
        else:
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


# ── S4 别名归一 prepare 函数（q→query、limit/top_k互通、end:None删键） ──

def _prepare_calendar_args(args: dict[str, Any]) -> dict[str, Any]:
    """calendar_create归一：end:None删键 + 通用别名兼容。"""
    d = dict(args)
    if "query" not in d and "q" in d:
        d["query"] = d.pop("q")
    if "top_k" not in d and "limit" in d:
        d["top_k"] = d["limit"]
    if "limit" not in d and "top_k" in d:
        d["limit"] = d["top_k"]
    if "end" in d and d.get("end") is None:
        d.pop("end", None)
    return d


def _prepare_todo_args(args: dict[str, Any]) -> dict[str, Any]:
    """todo_create归一：title别名兼容 + 通用别名兼容。"""
    d = dict(args)
    if "title" not in d:
        for _k in ("content", "text", "name"):
            if _k in d and isinstance(d[_k], str):
                d["title"] = d.pop(_k)
                break
    if "query" not in d and "q" in d:
        d["query"] = d.pop("q")
    if "top_k" not in d and "limit" in d:
        d["top_k"] = d["limit"]
    if "limit" not in d and "top_k" in d:
        d["limit"] = d["top_k"]
    if "end" in d and d.get("end") is None:
        d.pop("end", None)
    return d


def _prepare_search_args(args: dict[str, Any]) -> dict[str, Any]:
    """web_search归一：q→query、limit/top_k互通、end:None删键。"""
    d = dict(args)
    if "query" not in d and "q" in d:
        d["query"] = d.pop("q")
    if "top_k" not in d and "limit" in d:
        d["top_k"] = d["limit"]
    if "limit" not in d and "top_k" in d:
        d["limit"] = d["top_k"]
    if "end" in d and d.get("end") is None:
        d.pop("end", None)
    return d


@register(
    "memory_search",
    schema=ToolSchema(
        properties={"query": {"type": "string"}, "top_k": {"type": "integer"}},
        required=["query"],
    ),
    label="记忆搜索",
    description="搜索用户长期记忆",
    execution_mode="parallel",
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
    execution_mode="parallel",
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
    execution_mode="parallel",
)
async def graph_search(query: str, **kw) -> list[dict[str, Any]]:
    from app.graph.neo import search_prereqs
    return search_prereqs(query)


@register(
    "write_tasks",
    schema=ToolSchema(
        properties={"tasks": {"type": "array"}, "user_id": {"type": "integer"}},
        required=["tasks", "user_id"],
    ),
    label="写入任务",
    description="将规划任务写入数据库",
    execution_mode="sequential",
)
# S4: write_tasks暂不配prepare_arguments，下轮处理批量tasks别名归一
async def write_tasks(tasks: list[dict[str, Any]], **kw) -> list[dict[str, Any]] | dict[str, Any]:
    from sqlmodel import Session, select

    from app.core.database import engine
    from app.models.goal import LearningGoal
    from app.models.task import Task

    session: Session | None = kw.get("session")
    user_id = kw.get("user_id")
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        return _tool_error("user_id必填(调用方透传)", 40001)
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


# ── P1 工具干活能力：calendar/todo/search（真stdio + mock回退） ──

async def _call_mcp_or_mock(server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """默认走 app/mcp/client.py 真 stdio，失败回退本地 mock，保证演示链路不断。"""
    try:
        from app.mcp.client import call_tool as _mcp_call

        try:
            res = await _mcp_call(server, tool, args or {}, timeout=3.0)
            if isinstance(res, dict) and res:
                return res
        except Exception:
            logger.warning("mcp real call failed %s.%s, fallback mock", server, tool, exc_info=True)
    except Exception:
        logger.warning("mcp client import failed, fallback mock", exc_info=True)
    # 本地 mock 回退（字段与 app/mcp/client.py Mock 兼容）
    if server == "calendar":
        eid = str(uuid.uuid4())
        return {
            "event_id": eid,
            "id": eid,
            "result": {"ok": True, "server": server, "tool": tool, "args": args, "fallback": "local"},
            "server": server,
            "tool": tool,
            "title": (args or {}).get("title", "Mock Event"),
            "start": (args or {}).get("start"),
            "end": (args or {}).get("end"),
        }
    if server == "todo":
        tid = str(uuid.uuid4())
        return {
            "todo_id": tid,
            "id": tid,
            "event_id": tid,
            "result": {"ok": True, "server": server, "tool": tool, "args": args, "fallback": "local"},
            "server": server,
            "tool": tool,
            "title": (args or {}).get("title", "Mock Todo"),
        }
    q = (args or {}).get("query") or (args or {}).get("q") or "test"
    return {
        "results": [
            {"title": f"Mock result for '{q}' #1", "url": "https://example.com/1", "snippet": f"Simulated snippet for {q} - result 1", "score": 0.95},
            {"title": f"Mock result for '{q}' #2", "url": "https://example.com/2", "snippet": f"Simulated snippet for {q} - result 2", "score": 0.88},
        ],
        "result": {"ok": True, "server": server, "tool": tool, "args": args, "fallback": "local"},
        "server": server,
        "tool": tool,
        "query": q,
        "count": 2,
    }


@register(
    "calendar_create",
    schema=ToolSchema(
        properties={"title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}},
        required=["title", "start"],
    ),
    label="创建日历事件",
    description="创建日历事件（真stdio优先，失败回退mock）",
    prepare_arguments=_prepare_calendar_args,
    execution_mode="sequential",
)
async def calendar_create(title: str, start: str, end: str | None = None, **kw) -> dict[str, Any]:
    if not isinstance(title, str) or not title.strip():
        return _tool_error("title必填", 40001)
    title = title.strip()
    if len(title) > 200:
        return _tool_error("title过长(≤200)", 40001)
    try:
        s = _parse_dt(start)
    except (TypeError, ValueError):
        return _tool_error("start时间格式非法", 40001)
    e = None
    if end is not None:
        try:
            e = _parse_dt(end)
        except (TypeError, ValueError):
            return _tool_error("end时间格式非法", 40001)
        if e <= s:
            return _tool_error("end必须大于start", 40001)
    args: dict[str, Any] = {"title": title, "start": s.isoformat(), "end": e.isoformat() if e else None}
    return await _call_mcp_or_mock("calendar", "create_event", args)


@register(
    "todo_create",
    schema=ToolSchema(
        properties={"title": {"type": "string"}, "priority": {"type": "integer"}},
        required=["title"],
    ),
    label="创建待办",
    description="创建待办事项（真stdio优先，失败回退mock）",
    prepare_arguments=_prepare_todo_args,
)
async def todo_create(title: str, priority: int = 3, **kw) -> dict[str, Any]:
    if not isinstance(title, str) or not title.strip():
        return _tool_error("title必填", 40001)
    title = title.strip()
    if len(title) > 200:
        return _tool_error("title过长(≤200)", 40001)
    if not isinstance(priority, int) or isinstance(priority, bool) or not (1 <= priority <= 5):
        return _tool_error("priority须为1-5", 40001)
    return await _call_mcp_or_mock("todo", "create_todo", {"title": title})


@register(
    "web_search",
    schema=ToolSchema(
        properties={"query": {"type": "string"}, "top_k": {"type": "integer"}, "limit": {"type": "integer"}},
        required=["query"],
    ),
    label="网页搜索",
    description="网页搜索（真stdio优先，失败回退mock）",
    prepare_arguments=_prepare_search_args,
)
async def web_search(query: str, top_k: int = 3, limit: int | None = None, **kw) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        return _tool_error("query必填", 40001)
    query = query.strip()
    n = limit if limit is not None else top_k
    if not isinstance(n, int) or isinstance(n, bool) or not (1 <= n <= 10):
        return _tool_error("top_k/limit须为1-10", 40001)
    return await _call_mcp_or_mock("search", "web_search", {"query": query, "limit": n})
