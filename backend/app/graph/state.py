from typing import Literal, TypeAlias

from typing_extensions import TypedDict


class TopicOption(TypedDict):
    id: str
    title: str


ReviewStatus: TypeAlias = Literal["pending", "rejected", "approved"] | None
WorkflowStatus: TypeAlias = Literal[
    "planning_topics",
    "waiting_topic_selection",
    "drafting",
    "waiting_article_review",
    "rewriting",
    "extracting_visuals",
    "generating_images",
    "failed",
    "completed",
]


class AgentState(TypedDict):
    topic_direction: str
    generated_topics: list[TopicOption]
    selected_topic: str | None
    article_content: str | None
    review_feedback: str | None
    review_status: ReviewStatus
    visual_points: list[str]
    image_urls: list[str]
    status: WorkflowStatus
    revision_count: int
