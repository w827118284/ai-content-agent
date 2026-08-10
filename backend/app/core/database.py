from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.models.content_project import Base


_session_factory: async_sessionmaker[AsyncSession] | None = None


def sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def create_business_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        sqlalchemy_database_url(database_url),
        pool_pre_ping=True,
    )


async def initialize_business_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


def get_business_session_factory() -> async_sessionmaker[AsyncSession] | None:
    return _session_factory


async def get_business_session() -> AsyncIterator[AsyncSession | None]:
    session_factory = get_business_session_factory()
    if session_factory is None:
        yield None
        return

    async with session_factory() as session:
        yield session


@asynccontextmanager
async def business_database_runtime(config: Settings) -> AsyncIterator[None]:
    global _session_factory

    if _session_factory is not None:
        raise RuntimeError("Business database runtime 已经初始化")

    if config.database_url is None:
        yield
        return

    engine = create_business_engine(config.database_url.get_secret_value())
    try:
        await initialize_business_database(engine)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
        yield
    finally:
        _session_factory = None
        await engine.dispose()
