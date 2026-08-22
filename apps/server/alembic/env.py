"""Alembic env - P0 stub"""
from logging.config import fileConfig
from sqlalchemy import pool
from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = None

def run_migrations_offline(): pass
def run_migrations_online(): pass

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
