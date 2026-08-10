from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_business_session
from app.models.user import User


class DuplicateUsernameError(ValueError):
    pass


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_user(self, *, username: str, password_hash: str) -> User:
        user = User(username=username, password_hash=password_hash)
        self._session.add(user)
        try:
            await self._session.commit()
            await self._session.refresh(user)
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateUsernameError(username) from exc
        except Exception:
            await self._session.rollback()
            raise
        return user

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)


async def get_user_repository(
    session: Annotated[AsyncSession | None, Depends(get_business_session)],
) -> UserRepository | None:
    if session is None:
        return None
    return UserRepository(session)
