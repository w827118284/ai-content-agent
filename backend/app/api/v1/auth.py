from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps.auth import authentication_error, get_current_user
from app.core.config import settings
from app.models.user import User
from app.repositories.user_repository import (
    DuplicateUsernameError,
    UserRepository,
    get_user_repository,
)
from app.schemas.auth import AccessTokenResponse, AuthCredentials, UserResponse
from app.services.auth_service import create_access_token, hash_password, verify_password


router = APIRouter(prefix="/auth", tags=["auth"])
UserRepositoryDependency = Annotated[
    UserRepository | None,
    Depends(get_user_repository),
]


def require_repository(repository: UserRepository | None) -> UserRepository:
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="用户数据库未配置",
        )
    return repository


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    request: AuthCredentials,
    repository: UserRepositoryDependency,
) -> UserResponse:
    try:
        user = await require_repository(repository).create_user(
            username=request.username,
            password_hash=hash_password(request.password.get_secret_value()),
        )
    except DuplicateUsernameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        ) from exc
    return UserResponse.model_validate(user)


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    request: AuthCredentials,
    repository: UserRepositoryDependency,
) -> AccessTokenResponse:
    user = await require_repository(repository).get_by_username(request.username)
    password = request.password.get_secret_value()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise authentication_error()

    expires_in = settings.jwt_access_token_expire_minutes * 60
    token = create_access_token(
        user.id,
        secret_key=settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        expires_delta=timedelta(seconds=expires_in),
    )
    return AccessTokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return UserResponse.model_validate(current_user)
