from datetime import datetime, timezone
from typing import Optional, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime, JSON
import uuid


class AgentRunLog(SQLModel, table=True):
    __tablename__ = "agent_run_log"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    trace_id: str = Field(index=True, max_length=36)
    agent_name: str = Field(max_length=32)  # planner/executor/critic/mentor
    input: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    output: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    tool_calls: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
