"""Alembic env - P0已可用"""
from logging.config import fileConfig
from sqlalchemy import pool
from sqlmodel import SQLModel
from alembic import context
import sys
from pathlib import Path

# 确保可导入 app
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 导入模型以注册 metadata
try:
    from app.models import user, goal, task, execution, log  # noqa: F401
    target_metadata = SQLModel.metadata
except Exception:
    target_metadata = None

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = context.config.attributes.get("connection", None)
    if connectable is None:
        from app.core.database import engine
        connectable = engine
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
