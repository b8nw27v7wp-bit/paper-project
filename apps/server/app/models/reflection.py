from datetime import datetime, timezone
from typing import Optional, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime, JSON

class ReflectionReport(SQLModel, table=True):
    __tablename__ = "reflection_report"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    week: str = Field(max_length=16, index=True)  # 2026-W34
    completion_rate: float = Field(default=0)
    delay_rate: float = Field(default=0)
    avg_load: float = Field(default=0)
    analysis: Optional[str] = None
    next_plan_patch: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
