from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel


class Task(SQLModel, table=True):
    __tablename__ = "task"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="learning_goal.id", index=True)
    title: str = Field(max_length=200)
    planned_start: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    planned_end: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    priority: int = Field(default=3, ge=1, le=5)
    status: str = Field(default="todo", max_length=16, index=True)  # todo/doing/done/delayed
    # H1: source_agent 存 f"planner:{trace_id}"（planner:+32位hex=40字符），PG 安全扩到 64（迁移 004）。
    source_agent: str | None = Field(default=None, max_length=64)
    citations: Any | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_column=Column(DateTime(timezone=True)))


class TaskCreate(SQLModel):
    goal_id: int | None = None  # 批量时可省略，由路由注入
    title: str = Field(min_length=1, max_length=200)
    planned_start: datetime
    planned_end: datetime
    priority: int | None = Field(default=3, ge=1, le=5)
    status: str | None = Field(default="todo", max_length=16)
    # H1: 同上，PG 安全扩到 64（迁移 004）。
    source_agent: str | None = Field(default=None, max_length=64)
    citations: Any | None = None


class TaskUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    planned_start: datetime | None = None
    planned_end: datetime | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    status: str | None = Field(default=None, max_length=16)
    source_agent: str | None = Field(default=None, max_length=64)
    citations: Any | None = None


class TaskBatchCreate(SQLModel):
    tasks: list[TaskCreate]
