
from pydantic import BaseModel


class PlanCreate(BaseModel):
    goal_id: int
    preferences: dict | None = None  # {hours_per_day:1-8, preferred_time}
    require_approval: bool = False  # 写库审批网关：仅 multi 模式生效，默认 False 保持旧流程
    approval: str | None = None  # Wave A 四档：untrusted/on-request/never/granular，默认on-request；兼容旧require_approval=true→untrusted
    # Wave B 会话语义（Codex对标 exec cli + thread/resume + rollout三元组）：全可选，默认旧语义零变化
    resume: str | None = None  # trace_id直通 / 标题匹配 / "--last"按用户最近trace
    fork: bool = False  # true时新trace_id并记forked_from_seq（取源events长度）
    ephemeral: bool = False  # true时只走内存+SSE，不写DB不写Redis
    output_schema: str | None = None  # 非空时终态tasks校验失败则降级mock重算一次


class ApproveRequest(BaseModel):
    approved: bool
    token: str

class PlanResponse(BaseModel):
    trace_id: str
    tasks: list
    mentor_msg: str
    citations: list = []
