from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.auth import router as auth_router
from app.api.v1.projects import router as projects_router
from app.api.v1.workflows import router as workflows_router
from app.core.config import settings
from app.core.database import business_database_runtime
from app.graph.runtime import workflow_runtime
from app.schemas.workflow import HealthResponse


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with business_database_runtime(settings):
        async with workflow_runtime(settings):
            yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.mount(
    settings.image_public_prefix,
    StaticFiles(directory=settings.resolved_image_output_dir, check_dir=False),
    name="generated-images",
)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(workflows_router, prefix=settings.api_v1_prefix)
app.include_router(projects_router, prefix=settings.api_v1_prefix)


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
