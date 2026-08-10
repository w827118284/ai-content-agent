import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.database import create_business_engine, initialize_business_database
from app.repositories.user_repository import DuplicateUsernameError, UserRepository


def run(coroutine):
    return asyncio.run(coroutine)


def test_user_repository_creates_and_restores_user():
    async def scenario():
        engine = create_business_engine("sqlite+aiosqlite:///:memory:")
        try:
            await initialize_business_database(engine)
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                created = await UserRepository(session).create_user(
                    username="repository_user",
                    password_hash="$argon2id$test-hash",
                )

            async with session_factory() as new_session:
                repository = UserRepository(new_session)
                by_id = await repository.get_by_id(created.id)
                by_username = await repository.get_by_username("repository_user")

            assert by_id is not None
            assert by_username is not None
            assert by_id.id == created.id == by_username.id
            assert by_id.is_active is True
            assert by_id.password_hash == "$argon2id$test-hash"
        finally:
            await engine.dispose()

    run(scenario())


def test_user_repository_rejects_duplicate_username():
    async def scenario():
        engine = create_business_engine("sqlite+aiosqlite:///:memory:")
        try:
            await initialize_business_database(engine)
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                repository = UserRepository(session)
                await repository.create_user(
                    username="duplicate_repository_user",
                    password_hash="first-hash",
                )
                with pytest.raises(DuplicateUsernameError):
                    await repository.create_user(
                        username="duplicate_repository_user",
                        password_hash="second-hash",
                    )
        finally:
            await engine.dispose()

    run(scenario())
