import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps.auth import get_current_user
from app.api.sse import encode_sse
from app.graph.runner import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowStreamUpdate,
    WorkflowValidationError,
    get_workflow_state,
    prepare_resume_workflow,
    resume_workflow,
    start_workflow,
    stream_resume_workflow,
    stream_start_workflow,
)
from app.graph.state import AgentState
from app.models.user import User
from app.repositories.content_project_repository import (
    ContentProjectRepository,
    get_content_project_repository,
)
from app.schemas.workflow import (
    WorkflowResponse,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)


router = APIRouter(prefix="/workflows", tags=["workflows"])
logger = logging.getLogger(__name__)

StreamAction = Literal["start", "select_topic", "reject", "approve"]
STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}
NODE_MESSAGES = {
    "plan_topics": "选题生成完成",
    "human_select_topic": "选题已确认",
    "write_draft": "文章生成完成",
    "human_review": "审核意见已确认",
    "extract_visuals": "视觉知识点提取完成",
    "generate_images": "配图生成完成",
}

ProjectRepository = Annotated[
    ContentProjectRepository | None,
    Depends(get_content_project_repository),
]


def _require_repository(
    repository: ContentProjectRepository | None,
) -> ContentProjectRepository:
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="历史记录数据库未配置",
        )
    return repository


async def _sync_history_row(
    repository: ContentProjectRepository,
    user_id: UUID,
    result: dict[str, Any],
) -> None:
    state: AgentState = result["state"]
    try:
        await repository.update_from_state(result["thread_id"], user_id, state)
    except Exception:
        logger.exception(
            "Failed to sync content project history for thread_id=%s",
            result["thread_id"],
        )


async def _require_owned_project(
    repository: ContentProjectRepository,
    thread_id: str,
    current_user: User,
) -> None:
    project = await repository.get_by_thread_id_for_user(thread_id, current_user.id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"workflow thread_id 不存在: {thread_id}",
        )


def _stream_response(content: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        content,
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


def _progress_message(node: str, action: StreamAction) -> str:
    if node == "write_draft" and action == "reject":
        return "文章重写完成"
    return NODE_MESSAGES.get(node, "工作流节点执行完成")


def _terminal_event(result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    response = WorkflowResponse.model_validate(result).model_dump(mode="json")
    if result["is_completed"]:
        return "completed", response
    if result["interrupt"] is not None:
        return "interrupt", response
    if response["status"] == "failed":
        return (
            "error",
            {
                "thread_id": response["thread_id"],
                "code": "workflow_stream_failed",
                "message": "图片生成失败，请稍后新建任务重试",
                "workflow": response,
            },
        )
    raise RuntimeError("workflow stream ended without interrupt or completion")


async def _delete_starting_project(
    repository: ContentProjectRepository,
    user_id: UUID,
    thread_id: str,
) -> None:
    try:
        await repository.delete_by_thread_id_for_user(thread_id, user_id)
    except Exception:
        logger.exception(
            "Failed to compensate starting project for thread_id=%s",
            thread_id,
        )


async def _stream_events(
    *,
    thread_id: str,
    action: StreamAction,
    updates: AsyncIterator[WorkflowStreamUpdate],
    repository: ContentProjectRepository,
    user_id: UUID,
    compensate_start: bool = False,
) -> AsyncIterator[str]:
    yield encode_sse("meta", {"thread_id": thread_id, "action": action})
    try:
        async for update in updates:
            if update["type"] == "progress":
                node = update["node"]
                yield encode_sse(
                    "progress",
                    {
                        "thread_id": thread_id,
                        "node": node,
                        "status": "completed",
                        "message": _progress_message(node, action),
                    },
                )
                continue

            result = update["result"]
            await _sync_history_row(repository, user_id, result)
            event, payload = _terminal_event(result)
            yield encode_sse(event, payload)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error(
            "Workflow stream failed for thread_id=%s error_type=%s",
            thread_id,
            type(exc).__name__,
        )
        if compensate_start:
            await _delete_starting_project(repository, user_id, thread_id)
        yield encode_sse(
            "error",
            {
                "thread_id": thread_id,
                "code": "workflow_stream_failed",
                "message": "工作流执行失败，请稍后重试",
            },
        )


@router.post("/start", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def start(
    request: WorkflowStartRequest,
    repository: ProjectRepository,
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkflowResponse:
    owned_projects = _require_repository(repository)
    thread_id = str(uuid4())
    await owned_projects.create_project(
        user_id=current_user.id,
        thread_id=thread_id,
        topic_direction=request.topic_direction,
        status="starting",
        revision_count=0,
    )
    try:
        result = await start_workflow(request.topic_direction, thread_id=thread_id)
    except Exception:
        try:
            await owned_projects.delete_by_thread_id_for_user(thread_id, current_user.id)
        except Exception:
            logger.exception(
                "Failed to compensate starting project for thread_id=%s",
                thread_id,
            )
        raise
    await _sync_history_row(owned_projects, current_user.id, result)
    return WorkflowResponse.model_validate(result)


@router.post("/start/stream")
async def start_stream(
    request: WorkflowStartRequest,
    repository: ProjectRepository,
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    owned_projects = _require_repository(repository)
    thread_id = str(uuid4())
    await owned_projects.create_project(
        user_id=current_user.id,
        thread_id=thread_id,
        topic_direction=request.topic_direction,
        status="starting",
        revision_count=0,
    )
    try:
        updates = stream_start_workflow(request.topic_direction, thread_id)
    except Exception:
        await _delete_starting_project(owned_projects, current_user.id, thread_id)
        raise
    return _stream_response(
        _stream_events(
            thread_id=thread_id,
            action="start",
            updates=updates,
            repository=owned_projects,
            user_id=current_user.id,
            compensate_start=True,
        )
    )


@router.post("/{thread_id}/resume", response_model=WorkflowResponse)
async def resume(
    thread_id: str,
    request: WorkflowResumeRequest,
    repository: ProjectRepository,
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkflowResponse:
    owned_projects = _require_repository(repository)
    await _require_owned_project(owned_projects, thread_id, current_user)
    try:
        result = await resume_workflow(thread_id, request.to_resume_payload())
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WorkflowConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except WorkflowValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    await _sync_history_row(owned_projects, current_user.id, result)
    return WorkflowResponse.model_validate(result)


@router.post("/{thread_id}/resume/stream")
async def resume_stream(
    thread_id: str,
    request: WorkflowResumeRequest,
    repository: ProjectRepository,
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    owned_projects = _require_repository(repository)
    await _require_owned_project(owned_projects, thread_id, current_user)
    try:
        command = await prepare_resume_workflow(
            thread_id,
            request.to_resume_payload(),
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WorkflowConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _stream_response(
        _stream_events(
            thread_id=thread_id,
            action=request.action,
            updates=stream_resume_workflow(thread_id, command),
            repository=owned_projects,
            user_id=current_user.id,
        )
    )


@router.get("/{thread_id}/state", response_model=WorkflowResponse)
async def get_state(
    thread_id: str,
    repository: ProjectRepository,
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkflowResponse:
    owned_projects = _require_repository(repository)
    await _require_owned_project(owned_projects, thread_id, current_user)
    try:
        result = await get_workflow_state(thread_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return WorkflowResponse.model_validate(result)
