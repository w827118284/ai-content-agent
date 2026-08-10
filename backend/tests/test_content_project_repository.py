import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.database import create_business_engine, initialize_business_database
from app.graph.state import AgentState
from app.repositories.content_project_repository import ContentProjectRepository


def run(coroutine):
    return asyncio.run(coroutine)


def workflow_state(
    *,
    selected_topic: str | None = None,
    status: str = "waiting_topic_selection",
    revision_count: int = 0,
) -> AgentState:
    return {
        "topic_direction": "LangGraph 历史任务",
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


def test_repository_creates_and_finds_project_by_thread_id():
    async def scenario():
        engine = create_business_engine("sqlite+aiosqlite:///:memory:")
        try:
            await initialize_business_database(engine)
            session_factory = async_sessionmaker(engine, expire_on_commit=False)

            async with session_factory() as session:
                repository = ContentProjectRepository(session)
                created = await repository.create_project(
                    thread_id="repository-create-thread",
                    topic_direction="AI Agent 工程实践",
                    status="waiting_topic_selection",
                    revision_count=0,
                )

            async with session_factory() as new_session:
                restored = await ContentProjectRepository(
                    new_session
                ).get_by_thread_id("repository-create-thread")

            assert restored is not None
            assert restored.id == created.id
            assert restored.topic_direction == "AI Agent 工程实践"
            assert restored.selected_topic_title is None
            assert restored.status == "waiting_topic_selection"
            assert restored.revision_count == 0
        finally:
            await engine.dispose()

    run(scenario())


def test_repository_lists_by_recent_update_and_paginates():
    async def scenario():
        engine = create_business_engine("sqlite+aiosqlite:///:memory:")
        try:
            await initialize_business_database(engine)
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                repository = ContentProjectRepository(session)
                for suffix in ("a", "b", "c"):
                    await repository.create_project(
                        thread_id=f"repository-list-{suffix}",
                        topic_direction=f"方向 {suffix.upper()}",
                        status="waiting_topic_selection",
                        revision_count=0,
                    )
                    await asyncio.sleep(0.01)

                await repository.update_from_state(
                    "repository-list-a",
                    workflow_state(
                        selected_topic="更新后的选题",
                        status="waiting_article_review",
                        revision_count=1,
                    ),
                )
                projects, total = await repository.list_projects(
                    limit=2,
                    offset=0,
                )
                second_page, second_total = await repository.list_projects(
                    limit=1,
                    offset=2,
                )

            assert total == 3
            assert second_total == 3
            assert [project.thread_id for project in projects] == [
                "repository-list-a",
                "repository-list-c",
            ]
            assert [project.thread_id for project in second_page] == [
                "repository-list-b"
            ]
            assert projects[0].selected_topic_title == "更新后的选题"
            assert projects[0].revision_count == 1
        finally:
            await engine.dispose()

    run(scenario())
