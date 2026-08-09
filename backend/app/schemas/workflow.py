from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.graph.state import AgentState, WorkflowStatus


class HealthResponse(BaseModel):
    status: Literal["ok"]


class WorkflowStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_direction: str = Field(min_length=1, max_length=200)

    @field_validator("topic_direction")
    @classmethod
    def strip_topic_direction(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("topic_direction 不能为空")
        return stripped


class WorkflowResumeData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_id: str | None = None
    feedback: str | None = None


class WorkflowResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["select_topic", "approve", "reject"]
    data: WorkflowResumeData | None = None

    @model_validator(mode="after")
    def validate_action_data(self) -> "WorkflowResumeRequest":
        if self.action == "select_topic":
            topic_id = self.data.topic_id if self.data else None
            if not topic_id or not topic_id.strip():
                raise ValueError("select_topic 操作必须提供非空 topic_id")

        if self.action == "reject":
            feedback = self.data.feedback if self.data else None
            if not feedback or not feedback.strip():
                raise ValueError("reject 操作必须提供非空 feedback")

        return self

    def to_resume_payload(self) -> dict[str, Any]:
        if self.action == "select_topic":
            assert self.data is not None and self.data.topic_id is not None
            return {"topic_id": self.data.topic_id.strip()}
        if self.action == "reject":
            assert self.data is not None and self.data.feedback is not None
            return {"action": "reject", "feedback": self.data.feedback.strip()}
        return {"action": "approve"}


class WorkflowResponse(BaseModel):
    thread_id: str
    status: WorkflowStatus
    is_completed: bool
    interrupt: dict[str, Any] | None
    state: AgentState
