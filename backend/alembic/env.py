"""Alembic async migration environment.

CRITICAL patterns (from RESEARCH.md Pattern 1):
- pool.NullPool is MANDATORY to prevent connection pool interference in migration scripts.
- asyncio.run() wraps the async function — omitting it causes silent no-op.
- from app.db.models import Base MUST be imported BEFORE target_metadata = Base.metadata
  so autogenerate can see all tables (RESEARCH.md Pitfall 1).
- DATABASE_URL env var overrides alembic.ini to avoid hardcoded credentials (Pitfall 6).
"""
import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# CRITICAL: Import ALL ORM models so autogenerate can see Base.metadata
from app.db.models import Base  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override alembic.ini URL with DATABASE_URL environment variable (RESEARCH.md Pitfall 6)
# CR-03: Fail-fast if DATABASE_URL is absent — silent fallback causes mysterious migration errors
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is required to run migrations. "
        "Set it before invoking alembic."
    )
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # MANDATORY: prevents connection pool interference
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())  # MANDATORY: wraps async in sync entry point


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
