from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel


class AgentRunLog(SQLModel, table=True):
    __tablename__ = "agent_run_log"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    trace_id: str = Field(index=True, max_length=36)
    agent_name: str = Field(max_length=32)  # planner/executor/critic/mentor
    input: Any | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    output: Any | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    tool_calls: Any | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_column=Column(DateTime(timezone=True)))
