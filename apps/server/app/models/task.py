from datetime import datetime, timezone
from typing import Optional, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime, JSON


class Task(SQLModel, table=True):
    __tablename__ = "task"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="learning_goal.id", index=True)
    title: str = Field(max_length=200)
    planned_start: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    planned_end: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    priority: int = Field(default=3, ge=1, le=5)
    status: str = Field(default="todo", max_length=16, index=True)  # todo/doing/done/delayed
    source_agent: Optional[str] = Field(default=None, max_length=32)
    citations: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class TaskCreate(SQLModel):
    goal_id: Optional[int] = None  # 批量时可省略，由路由注入
    title: str = Field(min_length=1, max_length=200)
    planned_start: datetime
    planned_end: datetime
    priority: Optional[int] = Field(default=3, ge=1, le=5)
    status: Optional[str] = Field(default="todo", max_length=16)
    source_agent: Optional[str] = Field(default=None, max_length=32)
    citations: Optional[Any] = None


class TaskUpdate(SQLModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    status: Optional[str] = Field(default=None, max_length=16)
    source_agent: Optional[str] = Field(default=None, max_length=32)
    citations: Optional[Any] = None


class TaskBatchCreate(SQLModel):
    tasks: list[TaskCreate]
