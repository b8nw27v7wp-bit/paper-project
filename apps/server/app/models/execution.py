from datetime import UTC, datetime

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class TaskExecutionLog(SQLModel, table=True):
    __tablename__ = "task_execution_log"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id", index=True)
    actual_duration: int = Field(ge=0, le=600)
    completion_rate: float = Field(ge=0, le=1)
    delay_reason: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_column=Column(DateTime(timezone=True)))


class ExecutionCreate(SQLModel):
    actual_duration: int = Field(ge=0, le=600)
    completion_rate: float = Field(ge=0, le=1)
    delay_reason: str | None = Field(default=None, max_length=500)


class PomodoroCreate(SQLModel):
    # 番茄钟独立上报（L3）：duration 1-600 秒，focus 0-1
    duration_seconds: int = Field(ge=1, le=600)
    focus_score: float = Field(ge=0, le=1)
