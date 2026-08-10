from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph.state import CompiledStateGraph

from app.core.config import Settings
from app.graph.workflow import compile_content_workflow


class WorkflowRuntimeConfigurationError(RuntimeError):
    pass


class WorkflowRuntimeNotInitializedError(RuntimeError):
    pass


_content_workflow: CompiledStateGraph | None = None


def get_content_workflow() -> CompiledStateGraph:
    if _content_workflow is None:
        raise WorkflowRuntimeNotInitializedError(
            "Workflow runtime 尚未初始化；请通过 FastAPI lifespan 启动应用"
        )
    return _content_workflow


def _checkpoint_serializer(config: Settings) -> JsonPlusSerializer:
    allowed_modules = None if config.langgraph_strict_msgpack else True
    return JsonPlusSerializer(allowed_msgpack_modules=allowed_modules)


@asynccontextmanager
async def workflow_runtime(
    config: Settings,
) -> AsyncIterator[CompiledStateGraph]:
    global _content_workflow

    if _content_workflow is not None:
        raise RuntimeError("Workflow runtime 已经初始化")

    serializer = _checkpoint_serializer(config)

    if config.checkpointer_backend == "memory":
        graph = compile_content_workflow(InMemorySaver(serde=serializer))
        _content_workflow = graph
        try:
            yield graph
        finally:
            if _content_workflow is graph:
                _content_workflow = None
        return

    if config.database_url is None:
        raise WorkflowRuntimeConfigurationError(
            "CHECKPOINTER_BACKEND=postgres 时必须配置 DATABASE_URL"
        )

    database_url = config.database_url.get_secret_value()
    async with AsyncPostgresSaver.from_conn_string(
        database_url,
        serde=serializer,
    ) as checkpointer:
        await checkpointer.setup()
        graph = compile_content_workflow(checkpointer)
        _content_workflow = graph
        try:
            yield graph
        finally:
            if _content_workflow is graph:
                _content_workflow = None
