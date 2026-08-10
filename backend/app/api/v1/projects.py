from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps.auth import get_current_user
from app.models.user import User
from app.repositories.content_project_repository import (
    ContentProjectRepository,
    get_content_project_repository,
)
from app.schemas.projects import ProjectListResponse


router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        ContentProjectRepository | None,
        Depends(get_content_project_repository),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectListResponse:
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="历史记录数据库未配置",
        )

    projects, total = await repository.list_projects(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return ProjectListResponse(
        items=projects,
        total=total,
        limit=limit,
        offset=offset,
    )
