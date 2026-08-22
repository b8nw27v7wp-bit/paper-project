from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime


class TaskExecutionLog(SQLModel, table=True):
    __tablename__ = "task_execution_log"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id", index=True)
    actual_duration: int = Field(ge=0, le=600)
    completion_rate: float = Field(ge=0, le=1)
    delay_reason: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class ExecutionCreate(SQLModel):
    actual_duration: int = Field(ge=0, le=600)
    completion_rate: float = Field(ge=0, le=1)
    delay_reason: Optional[str] = Field(default=None, max_length=500)
