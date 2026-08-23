from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Text
from sqlmodel import Field, SQLModel


class MemoryChunk(SQLModel, table=True):
    __tablename__ = "memory_chunk"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    content: str = Field(max_length=2000)
    # PG: vector(1536), SQLite: JSON text
    embedding: Any | None = Field(default=None, sa_column=Column(Text, nullable=True))
    type: str = Field(default="memory", max_length=16, index=True)  # memory/knowledge
    source_id: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_column=Column(DateTime(timezone=True)))

    # 联合索引 user_id+type 在 migration 中建
