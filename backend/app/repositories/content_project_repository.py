from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_business_session
from app.graph.state import AgentState
from app.models.content_project import ContentProject


class ContentProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_project(
        self,
        *,
        thread_id: str,
        topic_direction: str,
        status: str,
        revision_count: int,
        selected_topic_title: str | None = None,
    ) -> ContentProject:
        project = ContentProject(
            thread_id=thread_id,
            topic_direction=topic_direction,
            selected_topic_title=selected_topic_title,
            status=status,
            revision_count=revision_count,
        )
        self._session.add(project)
        try:
            await self._session.commit()
            await self._session.refresh(project)
        except Exception:
            await self._session.rollback()
            raise
        return project

    async def get_by_thread_id(self, thread_id: str) -> ContentProject | None:
        result = await self._session.execute(
            select(ContentProject).where(ContentProject.thread_id == thread_id)
        )
        return result.scalar_one_or_none()

    async def list_projects(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ContentProject], int]:
        total_result = await self._session.execute(
            select(func.count()).select_from(ContentProject)
        )
        total = int(total_result.scalar_one())
        result = await self._session.execute(
            select(ContentProject)
            .order_by(
                ContentProject.updated_at.desc(),
                ContentProject.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

    async def update_from_state(
        self,
        thread_id: str,
        state: AgentState,
    ) -> ContentProject | None:
        project = await self.get_by_thread_id(thread_id)
        if project is None:
            return None

        project.selected_topic_title = state["selected_topic"]
        project.status = state["status"]
        project.revision_count = state["revision_count"]
        project.updated_at = datetime.now(UTC)
        try:
            await self._session.commit()
            await self._session.refresh(project)
        except Exception:
            await self._session.rollback()
            raise
        return project


async def get_content_project_repository(
    session: Annotated[AsyncSession | None, Depends(get_business_session)],
) -> ContentProjectRepository | None:
    if session is None:
        return None
    return ContentProjectRepository(session)
