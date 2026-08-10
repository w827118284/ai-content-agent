import logging
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps.auth import get_current_user
from app.graph.runner import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
    get_workflow_state,
    resume_workflow,
    start_workflow,
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
