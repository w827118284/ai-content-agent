import asyncio
from contextlib import suppress
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.database import create_business_engine, initialize_business_database
from app.graph.state import AgentState
from app.models.content_project import ContentProject
from app.repositories.content_project_repository import ContentProjectRepository


DATABASE_URL = (
    settings.database_url.get_secret_value()
    if settings.database_url is not None
    else None
)


def workflow_state(
    *,
    selected_topic: str | None,
    status: str,
    revision_count: int,
) -> AgentState:
    return {
        "topic_direction": "PostgreSQL Business History",
        "generated_topics": [],
        "selected_topic": selected_topic,
        "article_content": None,
        "review_feedback": None,
        "review_status": None,
        "visual_points": [],
        "image_urls": [],
        "status": status,
        "revision_count": revision_count,
    }


@pytest.mark.skipif(
    DATABASE_URL is None,
    reason="未配置 DATABASE_URL，跳过真实 PostgreSQL business history 集成测试",
)
def test_business_history_persists_in_postgres_and_enforces_constraints():
    test_run_id = str(uuid4())
    thread_ids = [
        f"business-integration-{test_run_id}-{suffix}" for suffix in ("a", "b", "c")
    ]

    async def scenario():
        assert DATABASE_URL is not None
        engine = create_business_engine(DATABASE_URL)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await initialize_business_database(engine)

            async with session_factory() as session:
                repository = ContentProjectRepository(session)
                for index, thread_id in enumerate(thread_ids):
                    await repository.create_project(
                        thread_id=thread_id,
                        topic_direction=f"PostgreSQL 任务 {index + 1}",
                        status="waiting_topic_selection",
                        revision_count=0,
                    )
                    await asyncio.sleep(0.01)

            async with session_factory() as duplicate_session:
                duplicate_repository = ContentProjectRepository(duplicate_session)
                with pytest.raises(IntegrityError):
                    await duplicate_repository.create_project(
                        thread_id=thread_ids[0],
                        topic_direction="重复 thread",
                        status="waiting_topic_selection",
                        revision_count=0,
                    )

            async with session_factory() as update_session:
                update_repository = ContentProjectRepository(update_session)
                await update_repository.update_from_state(
                    thread_ids[0],
                    workflow_state(
                        selected_topic="PostgreSQL 恢复实战",
                        status="waiting_article_review",
                        revision_count=2,
                    ),
                )
                projects, total = await update_repository.list_projects(
                    limit=100,
                    offset=0,
                )

            integration_projects = [
                project for project in projects if project.thread_id in thread_ids
            ]
            assert total >= 3
            assert [project.thread_id for project in integration_projects] == [
                thread_ids[0],
                thread_ids[2],
                thread_ids[1],
            ]

            async with session_factory() as new_session:
                restored = await ContentProjectRepository(
                    new_session
                ).get_by_thread_id(thread_ids[0])
                assert restored is not None
                assert restored.selected_topic_title == "PostgreSQL 恢复实战"
                assert restored.status == "waiting_article_review"
                assert restored.revision_count == 2
        finally:
            with suppress(Exception):
                async with session_factory() as cleanup_session:
                    await cleanup_session.execute(
                        delete(ContentProject).where(
                            ContentProject.thread_id.in_(thread_ids)
                        )
                    )
                    await cleanup_session.commit()
            await engine.dispose()

    asyncio.run(scenario())
