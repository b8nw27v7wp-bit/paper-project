"""003_user_tz - user.created_at 改 TIMESTAMPTZ（对齐 app/models/user.py）
Revision ID: 003
Revises: 002
Create Date: 2026-09-08
说明：
- SQLite 无感（无原生 TZ 类型，跳过）；PG 老库需 ALTER，已有 naive 时间按 UTC 解读（与 init_db 种子语义一致）。
- 全 try/except 包裹，沿 001/002 风格，失败不阻断链。
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
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
        op.execute(sa.text("ALTER TABLE \"user\" ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'"))
    except Exception:
        pass


def downgrade() -> None:
    try:
        bind = op.get_bind()
        if not _is_pg(bind):
            return
        op.execute(sa.text("ALTER TABLE \"user\" ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'"))
    except Exception:
        pass
