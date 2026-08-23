from datetime import UTC, datetime

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class LearningGoal(SQLModel, table=True):
    __tablename__ = "learning_goal"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    title: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    deadline: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    subject: str | None = Field(default=None, max_length=64)
    status: str = Field(default="active", max_length=16, index=True)  # active/archived
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_column=Column(DateTime(timezone=True)))


# Pydantic schemas
class GoalCreate(SQLModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    deadline: datetime
    subject: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default="active", max_length=16)

    # deadline > now+1d 在路由层校验，保持模型纯净


class GoalUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    deadline: datetime | None = None
    subject: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=16)
