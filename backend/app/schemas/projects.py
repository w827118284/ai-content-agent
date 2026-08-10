from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.graph.state import WorkflowStatus


ProjectStatus = WorkflowStatus | Literal["starting"]


class ContentProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    thread_id: str
    topic_direction: str
    selected_topic_title: str | None
    status: ProjectStatus
    revision_count: int
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    items: list[ContentProjectSummary]
    total: int
    limit: int
    offset: int
