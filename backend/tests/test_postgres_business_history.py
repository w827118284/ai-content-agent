import asyncio
from contextlib import suppress
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.database import create_business_engine
from app.graph.state import AgentState
from app.models.content_project import ContentProject
from app.models.user import User
from app.repositories.content_project_repository import ContentProjectRepository
from app.repositories.user_repository import UserRepository


DATABASE_URL = (
    settings.database_url.get_secret_value()
    if settings.database_url is not None
    else None
)
EXPECTED_TABLES = {
    "alembic_version",
    "users",
    "content_projects",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
}


def workflow_state() -> AgentState:
    return {
        "topic_direction": "PostgreSQL Auth Ownership",
        "generated_topics": [],
        "selected_topic": "PostgreSQL 用户归属实战",
        "article_content": None,
        "review_feedback": None,
        "review_status": None,
        "visual_points": [],
        "image_urls": [],
        "status": "waiting_article_review",
        "revision_count": 2,
    }


@pytest.mark.skipif(
    DATABASE_URL is None,
    reason="未配置 DATABASE_URL，跳过真实 PostgreSQL business history 集成测试",
)
def test_postgres_migration_and_user_ownership_persist_across_sessions():
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "head")

    test_run_id = uuid4().hex
    user_ids: list[UUID] = []
    thread_ids = {
        "a1": f"phase6-postgres-{test_run_id}-a1",
        "a2": f"phase6-postgres-{test_run_id}-a2",
        "b1": f"phase6-postgres-{test_run_id}-b1",
        "legacy": f"phase6-postgres-{test_run_id}-legacy",
    }

    async def scenario():
        assert DATABASE_URL is not None
        engine = create_business_engine(DATABASE_URL)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.connect() as connection:
                table_rows = await connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
                assert EXPECTED_TABLES <= {row[0] for row in table_rows}
                revision = await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
                assert revision.scalar_one() == "0002_add_auth_ownership"

            async with session_factory() as user_session:
                users = UserRepository(user_session)
                user_a = await users.create_user(
                    username=f"phase6_pg_a_{test_run_id}",
                    password_hash="$argon2id$phase6-test-a",
                )
                user_ids.append(user_a.id)
                user_b = await users.create_user(
                    username=f"phase6_pg_b_{test_run_id}",
                    password_hash="$argon2id$phase6-test-b",
                )
                user_ids.append(user_b.id)

            async with session_factory() as project_session:
                projects = ContentProjectRepository(project_session)
                await projects.create_project(
                    user_id=user_a.id,
                    thread_id=thread_ids["a1"],
                    topic_direction="User A first",
                    status="waiting_topic_selection",
                    revision_count=0,
                )
                await projects.create_project(
                    user_id=user_a.id,
                    thread_id=thread_ids["a2"],
                    topic_direction="User A second",
                    status="waiting_topic_selection",
                    revision_count=0,
                )
                await projects.create_project(
                    user_id=user_b.id,
                    thread_id=thread_ids["b1"],
                    topic_direction="User B only",
                    status="waiting_topic_selection",
                    revision_count=0,
                )
                project_session.add(
                    ContentProject(
                        user_id=None,
                        thread_id=thread_ids["legacy"],
                        topic_direction="Legacy unowned",
                        status="waiting_topic_selection",
                        revision_count=0,
                    )
                )
                await project_session.commit()
                await projects.update_from_state(
                    thread_ids["a1"],
                    user_a.id,
                    workflow_state(),
                )

            async with session_factory() as restored_session:
                restored = ContentProjectRepository(restored_session)
                user_a_projects, user_a_total = await restored.list_projects(
                    user_id=user_a.id,
                    limit=20,
                    offset=0,
                )
                user_b_projects, user_b_total = await restored.list_projects(
                    user_id=user_b.id,
                    limit=20,
                    offset=0,
                )
                cross_user = await restored.get_by_thread_id_for_user(
                    thread_ids["a1"],
                    user_b.id,
                )
                own_project = await restored.get_by_thread_id_for_user(
                    thread_ids["a1"],
                    user_a.id,
                )

            assert user_a_total == 2
            assert {project.thread_id for project in user_a_projects} == {
                thread_ids["a1"],
                thread_ids["a2"],
            }
            assert user_b_total == 1
            assert [project.thread_id for project in user_b_projects] == [
                thread_ids["b1"]
            ]
            assert cross_user is None
            assert own_project is not None
            assert own_project.selected_topic_title == "PostgreSQL 用户归属实战"
            assert own_project.revision_count == 2
        finally:
            with suppress(Exception):
                async with session_factory() as cleanup_session:
                    await cleanup_session.execute(
                        delete(ContentProject).where(
                            ContentProject.thread_id.in_(thread_ids.values())
                        )
                    )
                    if user_ids:
                        await cleanup_session.execute(
                            delete(User).where(User.id.in_(user_ids))
                        )
                    await cleanup_session.commit()
            await engine.dispose()

    asyncio.run(scenario())
