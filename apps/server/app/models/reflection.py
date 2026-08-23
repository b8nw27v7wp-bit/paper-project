from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel


class ReflectionReport(SQLModel, table=True):
    __tablename__ = "reflection_report"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    week: str = Field(max_length=16, index=True)  # 2026-W34
    completion_rate: float = Field(default=0)
    delay_rate: float = Field(default=0)
    avg_load: float = Field(default=0)
    analysis: str | None = None
    next_plan_patch: Any | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_column=Column(DateTime(timezone=True)))
