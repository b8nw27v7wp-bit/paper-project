"""002_vector_idx - pgvector Vector(1536) + 索引（P1 12-13）
Revision ID: 002
Revises: 001
Create Date: 2026-08-26
说明：
- 条件：USE_PG=1 且 pgvector 已装时，memory_chunk.embedding 改 Vector(1536) + HNSW，已在 app/models/memory.py 条件分支；
- 本迁移为 SQLite 兼容：仅建通用索引（user_id,type, created_at），PG 侧额外建 HNSW（若扩展已装则成功，否则跳过）。
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 通用索引（SQLite/PG 通用）
    try:
        op.create_index("idx_memory_user_type", "memory_chunk", ["user_id", "type"])
    except Exception:
        pass
    try:
        op.create_index("idx_memory_created", "memory_chunk", ["created_at"])
    except Exception:
        pass
    try:
        op.create_index("idx_exec_created", "task_execution_log", ["created_at"])
    except Exception:
        pass
    try:
        op.create_index("idx_task_goal_status", "task", ["goal_id", "status"])
    except Exception:
        pass
    # PG HNSW（仅 PG 且扩展存在时）
    try:
        # 需在 PG 上执行，SQLite 会抛错，捕获跳过
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_memory_embedding_hnsw ON memory_chunk USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)"))
    except Exception:
        pass

def downgrade() -> None:
    try:
        op.drop_index("idx_memory_user_type", table_name="memory_chunk")
    except Exception:
        pass
    try:
        op.drop_index("idx_memory_created", table_name="memory_chunk")
    except Exception:
        pass
    try:
        op.drop_index("idx_exec_created", table_name="task_execution_log")
    except Exception:
        pass
    try:
        op.drop_index("idx_task_goal_status", table_name="task")
    except Exception:
        pass
    try:
        op.execute(sa.text("DROP INDEX IF EXISTS idx_memory_embedding_hnsw"))
    except Exception:
        pass
