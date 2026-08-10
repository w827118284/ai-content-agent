import asyncio
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command

from app.core.config import settings
from app.graph import nodes
from app.graph.state import AgentState
from app.graph.workflow import compile_content_workflow
from app.services.llm_mock import MockLLMService


DATABASE_URL = (
    settings.database_url.get_secret_value()
    if settings.database_url is not None
    else None
)


def initial_state() -> AgentState:
    return {
        "topic_direction": "LangGraph Checkpoint 持久化实战",
        "generated_topics": [],
        "selected_topic": None,
        "article_content": None,
        "review_feedback": None,
        "review_status": None,
        "visual_points": [],
        "image_urls": [],
        "status": "planning_topics",
        "revision_count": 0,
    }


@asynccontextmanager
async def postgres_graph(database_url: str):
    serializer = JsonPlusSerializer(allowed_msgpack_modules=None)
    async with AsyncPostgresSaver.from_conn_string(
        database_url,
        serde=serializer,
    ) as saver:
        await saver.setup()
        yield saver, compile_content_workflow(saver)


@pytest.mark.skipif(
    DATABASE_URL is None,
    reason="未配置 DATABASE_URL，跳过真实 PostgreSQL checkpoint 集成测试",
)
def test_workflow_recovers_across_new_postgres_graph_instances(monkeypatch):
    monkeypatch.setattr(nodes, "llm_service", MockLLMService())
    thread_id = f"postgres-integration-{uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    async def run_scenario():
        assert DATABASE_URL is not None
        generated_topics = []

        try:
            async with postgres_graph(DATABASE_URL) as (_, graph_a):
                await graph_a.ainvoke(initial_state(), config=config)
                snapshot_a = await graph_a.aget_state(config)
                generated_topics = snapshot_a.values["generated_topics"]
                assert snapshot_a.values["status"] == "waiting_topic_selection"
                assert len(generated_topics) == 5

            async with postgres_graph(DATABASE_URL) as (_, graph_b):
                restored_a = await graph_b.aget_state(config)
                assert restored_a.values["generated_topics"] == generated_topics
                assert restored_a.values["status"] == "waiting_topic_selection"

                await graph_b.ainvoke(
                    Command(resume={"topic_id": generated_topics[0]["id"]}),
                    config=config,
                )
                article_review = await graph_b.aget_state(config)
                assert article_review.values["status"] == "waiting_article_review"
                assert article_review.values["article_content"]

                await graph_b.ainvoke(
                    Command(
                        resume={
                            "action": "reject",
                            "feedback": "增加 checkpoint 恢复代码示例",
                        }
                    ),
                    config=config,
                )
                rejected = await graph_b.aget_state(config)
                assert rejected.values["status"] == "waiting_article_review"
                assert rejected.values["revision_count"] == 1

            async with postgres_graph(DATABASE_URL) as (saver_c, graph_c):
                restored_b = await graph_c.aget_state(config)
                assert restored_b.values["status"] == "waiting_article_review"
                assert restored_b.values["revision_count"] == 1

                await graph_c.ainvoke(
                    Command(resume={"action": "approve"}),
                    config=config,
                )
                completed = await graph_c.aget_state(config)
                assert completed.values["status"] == "completed"
                assert completed.values["revision_count"] == 1
                await saver_c.adelete_thread(thread_id)
        finally:
            with suppress(Exception):
                async with postgres_graph(DATABASE_URL) as (cleanup_saver, _):
                    await cleanup_saver.adelete_thread(thread_id)

    asyncio.run(run_scenario())
