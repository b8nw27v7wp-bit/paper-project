"""004_task_source_agent - task.source_agent 32→64（对齐 app/models/task.py H1 修复）
Revision ID: 004
Revises: 003
Create Date: 2026-09-09
说明：
- H1 写侧统一 f"planner:{trace_id}"（planner:+32位hex=40字符），原 max_length=32 在 PG 下会炸。
- SQLite 无感（无原生 VARCHAR 约束，跳过）；PG 老库需 ALTER 扩到 64。
- 全 try/except 包裹，沿 003 风格，失败不阻断链。
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def _is_pg(bind) -> bool:
    try:
        return bind.dialect.name == "postgresql"
    except Exception:
        return False


def upgrade() -> None:
    try:
        bind = op.get_bind()
        if not _is_pg(bind):
            return
        op.execute(sa.text("ALTER TABLE task ALTER COLUMN source_agent TYPE VARCHAR(64)"))
    except Exception:
        pass


def downgrade() -> None:
    try:
        bind = op.get_bind()
        if not _is_pg(bind):
            return
        op.execute(sa.text("ALTER TABLE task ALTER COLUMN source_agent TYPE VARCHAR(32)"))
    except Exception:
        pass
