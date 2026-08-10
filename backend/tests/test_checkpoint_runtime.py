import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import ValidationError

from app.core.config import Settings
from app.graph.runtime import (
    WorkflowRuntimeConfigurationError,
    WorkflowRuntimeNotInitializedError,
    get_content_workflow,
    workflow_runtime,
)


CHECKPOINTER_ENV_VARS = (
    "CHECKPOINTER_BACKEND",
    "DATABASE_URL",
    "LANGGRAPH_STRICT_MSGPACK",
    "CORS_ORIGINS",
)


def run(coroutine):
    return asyncio.run(coroutine)


def clear_checkpointer_environment(monkeypatch):
    for name in CHECKPOINTER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_jwt_secret_is_required(monkeypatch):
    clear_checkpointer_environment(monkeypatch)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None)


def test_jwt_secret_must_be_at_least_32_utf8_bytes(monkeypatch):
    clear_checkpointer_environment(monkeypatch)
    monkeypatch.setenv("JWT_SECRET_KEY", "too-short")

    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(_env_file=None)


def test_checkpointer_configuration_defaults_to_memory(monkeypatch):
    clear_checkpointer_environment(monkeypatch)

    configured = Settings(_env_file=None)

    assert configured.checkpointer_backend == "memory"
    assert configured.database_url is None
    assert configured.langgraph_strict_msgpack is True


def test_cors_origins_parse_from_comma_separated_environment(monkeypatch):
    clear_checkpointer_environment(monkeypatch)
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "http://localhost:5173, http://127.0.0.1:5173",
    )

    configured = Settings(_env_file=None)

    assert configured.cors_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_checkpointer_configuration_parses_postgres_environment(monkeypatch):
    clear_checkpointer_environment(monkeypatch)
    monkeypatch.setenv("CHECKPOINTER_BACKEND", "postgres")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:placeholder@localhost:5432/ai_content_agent",
    )
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "false")

    configured = Settings(_env_file=None)

    assert configured.checkpointer_backend == "postgres"
    assert configured.database_url is not None
    assert configured.database_url.get_secret_value().endswith("/ai_content_agent")
    assert configured.langgraph_strict_msgpack is False


def test_postgres_runtime_requires_database_url(monkeypatch):
    clear_checkpointer_environment(monkeypatch)
    monkeypatch.setenv("CHECKPOINTER_BACKEND", "postgres")
    configured = Settings(_env_file=None)

    async def start_runtime():
        async with workflow_runtime(configured):
            pass

    with pytest.raises(
        WorkflowRuntimeConfigurationError,
        match="必须配置 DATABASE_URL",
    ):
        run(start_runtime())


def test_memory_runtime_reuses_one_compiled_graph(monkeypatch):
    clear_checkpointer_environment(monkeypatch)
    configured = Settings(_env_file=None)

    async def use_runtime():
        async with workflow_runtime(configured) as graph:
            assert get_content_workflow() is graph
            assert get_content_workflow() is graph
            assert isinstance(graph.checkpointer.serde, JsonPlusSerializer)
            assert graph.checkpointer.serde._allowed_msgpack_modules is None

    run(use_runtime())

    with pytest.raises(WorkflowRuntimeNotInitializedError):
        get_content_workflow()


def test_postgres_runtime_calls_setup_and_closes_context(monkeypatch):
    clear_checkpointer_environment(monkeypatch)
    database_url = (
        "postgresql://postgres:placeholder@localhost:5432/ai_content_agent"
    )
    monkeypatch.setenv("CHECKPOINTER_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", database_url)
    configured = Settings(_env_file=None)
    saver = MagicMock()
    saver.setup = AsyncMock()
    graph = MagicMock()
    context_closed = False

    @asynccontextmanager
    async def saver_context():
        nonlocal context_closed
        try:
            yield saver
        finally:
            context_closed = True

    async def use_runtime():
        with (
            patch(
                "app.graph.runtime.AsyncPostgresSaver.from_conn_string",
                return_value=saver_context(),
            ) as from_conn_string,
            patch(
                "app.graph.runtime.compile_content_workflow",
                return_value=graph,
            ) as compile_workflow,
        ):
            async with workflow_runtime(configured) as active_graph:
                assert active_graph is graph
                assert get_content_workflow() is graph

            from_conn_string.assert_called_once()
            assert from_conn_string.call_args.args == (database_url,)
            assert isinstance(
                from_conn_string.call_args.kwargs["serde"],
                JsonPlusSerializer,
            )
            saver.setup.assert_awaited_once_with()
            compile_workflow.assert_called_once_with(saver)

    run(use_runtime())

    assert context_closed is True
    with pytest.raises(WorkflowRuntimeNotInitializedError):
        get_content_workflow()
