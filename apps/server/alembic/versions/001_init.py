"""001_init - P0初始建表 (2026-08-23)

Revision ID: 001
Revises:
Create Date: 2026-08-23

说明：
- P0阶段用 SQLModel.metadata.create_all 建表，Alembic 仅作占位；
- 后续增量变更用 `alembic revision --autogenerate` 生成。
"""
from typing import Sequence, Union
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401
import sqlmodel  # noqa: F401

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # P0: 已由 app/core/database.py init_db() 创建 user/learning_goal/task/task_execution_log/agent_run_log
    # 此处留空，保持可执行 `alembic upgrade head` 不报错
    pass


def downgrade() -> None:
    pass
