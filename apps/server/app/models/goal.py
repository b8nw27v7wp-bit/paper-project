from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime


class LearningGoal(SQLModel, table=True):
    __tablename__ = "learning_goal"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    title: str = Field(max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    deadline: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    subject: Optional[str] = Field(default=None, max_length=64)
    status: str = Field(default="active", max_length=16, index=True)  # active/archived
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


# Pydantic schemas
class GoalCreate(SQLModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    deadline: datetime
    subject: Optional[str] = Field(default=None, max_length=64)
    status: Optional[str] = Field(default="active", max_length=16)

    # deadline > now+1d 在路由层校验，保持模型纯净


class GoalUpdate(SQLModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    deadline: Optional[datetime] = None
    subject: Optional[str] = Field(default=None, max_length=64)
    status: Optional[str] = Field(default=None, max_length=16)
