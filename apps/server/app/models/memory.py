import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Text
from sqlmodel import Field, SQLModel

# pgvector 条件启用：USE_PG=1 且已安装 pgvector 时使用 Vector(1536)，否则回退 Text(JSON)
try:
    from pgvector.sqlalchemy import Vector  # type: ignore

    _has_vector = True
except ImportError:
    Vector = None  # type: ignore
    _has_vector = False

_USE_PG_VECTOR = os.getenv("USE_PG", "0") == "1" and _has_vector


class MemoryChunk(SQLModel, table=True):
    __tablename__ = "memory_chunk"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    content: str = Field(max_length=2000)
    # PG: vector(1536) 启用 HNSW，SQLite: Text(JSON) 兼容
    embedding: Any | None = Field(
        default=None,
        sa_column=Column(Vector(1536) if _USE_PG_VECTOR else Text, nullable=True),  # type: ignore
    )
    type: str = Field(default="memory", max_length=16, index=True)  # memory/knowledge
    source_id: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_column=Column(DateTime(timezone=True)))

    # 联合索引 user_id+type 在 migration 中建
