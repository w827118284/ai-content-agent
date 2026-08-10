import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.graph.runner import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
    get_workflow_state,
    resume_workflow,
    start_workflow,
)
from app.graph.state import AgentState
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

ProjectRepository = Annotated[
    ContentProjectRepository | None,
    Depends(get_content_project_repository),
]


async def _create_history_row(
    repository: ContentProjectRepository | None,
    result: dict[str, Any],
) -> None:
    if repository is None:
        return
    state: AgentState = result["state"]
    try:
        await repository.create_project(
            thread_id=result["thread_id"],
            topic_direction=state["topic_direction"],
            selected_topic_title=state["selected_topic"],
            status=state["status"],
            revision_count=state["revision_count"],
        )
    except Exception:
        logger.exception(
            "Failed to create content project history for thread_id=%s",
            result["thread_id"],
        )


async def _sync_history_row(
    repository: ContentProjectRepository | None,
    result: dict[str, Any],
) -> None:
    if repository is None:
        return
    state: AgentState = result["state"]
    try:
        project = await repository.update_from_state(result["thread_id"], state)
        if project is None:
            await repository.create_project(
                thread_id=result["thread_id"],
                topic_direction=state["topic_direction"],
                selected_topic_title=state["selected_topic"],
                status=state["status"],
                revision_count=state["revision_count"],
            )
    except Exception:
        logger.exception(
            "Failed to sync content project history for thread_id=%s",
            result["thread_id"],
        )


async def _backfill_missing_history_row(
    repository: ContentProjectRepository | None,
    result: dict[str, Any],
) -> None:
    if repository is None:
        return
    try:
        project = await repository.get_by_thread_id(result["thread_id"])
        if project is None:
            await _create_history_row(repository, result)
    except Exception:
        logger.exception(
            "Failed to backfill content project history for thread_id=%s",
            result["thread_id"],
        )


@router.post("/start", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def start(
    request: WorkflowStartRequest,
    repository: ProjectRepository,
) -> WorkflowResponse:
    result = await start_workflow(request.topic_direction)
    await _create_history_row(repository, result)
    return WorkflowResponse.model_validate(result)


@router.post("/{thread_id}/resume", response_model=WorkflowResponse)
async def resume(
    thread_id: str,
    request: WorkflowResumeRequest,
    repository: ProjectRepository,
) -> WorkflowResponse:
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
    await _sync_history_row(repository, result)
    return WorkflowResponse.model_validate(result)


@router.get("/{thread_id}/state", response_model=WorkflowResponse)
async def get_state(
    thread_id: str,
    repository: ProjectRepository,
) -> WorkflowResponse:
    try:
        result = await get_workflow_state(thread_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await _backfill_missing_history_row(repository, result)
    return WorkflowResponse.model_validate(result)
