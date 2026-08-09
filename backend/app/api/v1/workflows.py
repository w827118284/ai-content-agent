from fastapi import APIRouter, HTTPException, status

from app.graph.runner import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
    get_workflow_state,
    resume_workflow,
    start_workflow,
)
from app.schemas.workflow import (
    WorkflowResponse,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)


router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("/start", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def start(request: WorkflowStartRequest) -> WorkflowResponse:
    result = await start_workflow(request.topic_direction)
    return WorkflowResponse.model_validate(result)


@router.post("/{thread_id}/resume", response_model=WorkflowResponse)
async def resume(thread_id: str, request: WorkflowResumeRequest) -> WorkflowResponse:
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
    return WorkflowResponse.model_validate(result)


@router.get("/{thread_id}/state", response_model=WorkflowResponse)
async def get_state(thread_id: str) -> WorkflowResponse:
    try:
        result = await get_workflow_state(thread_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return WorkflowResponse.model_validate(result)
