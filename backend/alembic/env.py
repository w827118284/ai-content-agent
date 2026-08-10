import asyncio
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.database import sqlalchemy_database_url
from app.models import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if settings.database_url is None:
    raise RuntimeError("Alembic requires DATABASE_URL")

database_url = sqlalchemy_database_url(settings.database_url.get_secret_value())
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata
business_tables = frozenset(target_metadata.tables)


def include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    del reflected, compare_to
    if type_ == "table":
        return name in business_tables

    table = getattr(object_, "table", None)
    return table is None or table.name in business_tables


def configure_context(connection: Connection | None = None) -> None:
    options = {
        "target_metadata": target_metadata,
        "include_object": include_object,
        "compare_type": True,
    }
    if connection is None:
        context.configure(url=database_url, literal_binds=True, **options)
    else:
        context.configure(connection=connection, **options)


def run_migrations_offline() -> None:
    configure_context()
    with context.begin_transaction():
        context.run_migrations()


def run_sync_migrations(connection: Connection) -> None:
    configure_context(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(run_sync_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
