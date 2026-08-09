from fastapi import FastAPI

from app.api.v1.workflows import router as workflows_router
from app.core.config import settings
from app.schemas.workflow import HealthResponse


app = FastAPI(title=settings.app_name, version=settings.app_version)
app.include_router(workflows_router, prefix=settings.api_v1_prefix)


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
