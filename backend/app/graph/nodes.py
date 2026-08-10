from typing import Any

from langgraph.types import interrupt

from app.graph.state import AgentState
from app.services.image_mock import MockImageService
from app.services.llm_service import get_llm_service


class WorkflowNodeInputError(ValueError):
    """Raised when a human resume payload is invalid for the paused node."""


llm_service = get_llm_service()
image_service = MockImageService()


async def plan_topics(state: AgentState) -> dict[str, Any]:
    topics = await llm_service.plan_topics(state["topic_direction"])
    return {
        "generated_topics": topics,
        "status": "waiting_topic_selection",
    }


async def human_select_topic(state: AgentState) -> dict[str, Any]:
    resume_payload = interrupt(
        {
            "type": "topic_selection",
            "message": "请选择一个选题",
            "topics": state["generated_topics"],
        }
    )

    if not isinstance(resume_payload, dict):
        raise WorkflowNodeInputError("选题恢复数据必须是对象")

    topic_id = resume_payload.get("topic_id")
    selected = next(
        (topic for topic in state["generated_topics"] if topic["id"] == topic_id),
        None,
    )
    if selected is None:
        raise WorkflowNodeInputError(f"无效的 topic_id: {topic_id!r}")

    return {
        "selected_topic": selected["title"],
        "status": "drafting",
    }


async def write_draft(state: AgentState) -> dict[str, Any]:
    selected_topic = state["selected_topic"]
    if selected_topic is None:
        raise WorkflowNodeInputError("生成文章前必须先选择选题")

    is_rewrite = state["review_status"] == "rejected"
    article = await llm_service.write_article(
        topic_direction=state["topic_direction"],
        selected_topic=selected_topic,
        previous_article=state["article_content"] if is_rewrite else None,
        feedback=state["review_feedback"] if is_rewrite else None,
        revision_count=state["revision_count"],
    )
    return {
        "article_content": article,
        "review_status": "pending",
        "status": "waiting_article_review",
    }


async def human_review(state: AgentState) -> dict[str, Any]:
    resume_payload = interrupt(
        {
            "type": "article_review",
            "message": "请审核文章",
            "article_content": state["article_content"],
            "revision_count": state["revision_count"],
            "actions": ["approve", "reject"],
        }
    )

    if not isinstance(resume_payload, dict):
        raise WorkflowNodeInputError("审核恢复数据必须是对象")

    action = resume_payload.get("action")
    if action == "approve":
        return {
            "review_status": "approved",
            "review_feedback": None,
            "status": "extracting_visuals",
        }

    if action == "reject":
        feedback = resume_payload.get("feedback")
        if not isinstance(feedback, str) or not feedback.strip():
            raise WorkflowNodeInputError("Reject 时 feedback 不能为空")
        return {
            "review_status": "rejected",
            "review_feedback": feedback.strip(),
            "revision_count": state["revision_count"] + 1,
            "status": "rewriting",
        }

    raise WorkflowNodeInputError(f"无效的审核 action: {action!r}")


async def extract_visuals(state: AgentState) -> dict[str, Any]:
    selected_topic = state["selected_topic"]
    article_content = state["article_content"]
    if selected_topic is None or article_content is None:
        raise WorkflowNodeInputError("提炼视觉知识点前必须存在已审核文章")

    visual_points = await llm_service.extract_visual_points(
        selected_topic=selected_topic,
        article_content=article_content,
    )
    return {
        "visual_points": visual_points,
        "status": "generating_images",
    }


async def generate_images(state: AgentState) -> dict[str, Any]:
    image_urls = await image_service.generate_images(state["visual_points"])
    return {
        "image_urls": image_urls,
        "status": "completed",
    }
