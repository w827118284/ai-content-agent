from typing import Any
from uuid import uuid4

from langgraph.types import Command

from app.graph.nodes import WorkflowNodeInputError
from app.graph.runtime import get_content_workflow
from app.graph.state import AgentState


class WorkflowNotFoundError(LookupError):
    pass


class WorkflowConflictError(RuntimeError):
    pass


class WorkflowValidationError(ValueError):
    pass


def _graph_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def _initial_state(topic_direction: str) -> AgentState:
    return {
        "topic_direction": topic_direction,
        "generated_topics": [],
        "selected_topic": None,
        "article_content": None,
        "review_feedback": None,
        "review_status": None,
        "visual_points": [],
        "image_urls": [],
        "status": "planning_topics",
        "revision_count": 0,
    }


def _extract_interrupt(snapshot: Any) -> dict[str, Any] | None:
    for task in snapshot.tasks:
        for graph_interrupt in task.interrupts:
            if isinstance(graph_interrupt.value, dict):
                return graph_interrupt.value
    return None


def _requested_interrupt_type(payload: dict[str, Any]) -> str:
    if "topic_id" in payload and "action" not in payload:
        return "topic_selection"
    if payload.get("action") in {"approve", "reject"}:
        return "article_review"
    raise WorkflowValidationError("无法识别 resume payload")


def _validate_resume_payload(
    snapshot: Any,
    interrupt_type: str,
    payload: dict[str, Any],
) -> None:
    # Reject invalid input before LangGraph records it as the resume value.
    if interrupt_type == "topic_selection":
        topic_id = payload.get("topic_id")
        topics = snapshot.values.get("generated_topics", [])
        if not any(topic["id"] == topic_id for topic in topics):
            raise WorkflowValidationError(f"无效的 topic_id: {topic_id!r}")
        return

    action = payload.get("action")
    if action == "approve":
        return
    if action == "reject":
        feedback = payload.get("feedback")
        if not isinstance(feedback, str) or not feedback.strip():
            raise WorkflowValidationError("Reject 时 feedback 不能为空")
        return
    raise WorkflowValidationError(f"无效的审核 action: {action!r}")


def _result_from_snapshot(thread_id: str, snapshot: Any) -> dict[str, Any]:
    state = dict(snapshot.values)
    graph_interrupt = _extract_interrupt(snapshot)
    return {
        "thread_id": thread_id,
        "status": state["status"],
        "is_completed": state["status"] == "completed" and not snapshot.next,
        "interrupt": graph_interrupt,
        "state": state,
    }


async def _get_snapshot(thread_id: str) -> Any:
    snapshot = await get_content_workflow().aget_state(_graph_config(thread_id))
    if not snapshot.values:
        raise WorkflowNotFoundError(f"workflow thread_id 不存在: {thread_id}")
    return snapshot


async def start_workflow(topic_direction: str) -> dict[str, Any]:
    thread_id = str(uuid4())
    config = _graph_config(thread_id)
    workflow = get_content_workflow()
    await workflow.ainvoke(_initial_state(topic_direction), config=config)
    snapshot = await workflow.aget_state(config)
    return _result_from_snapshot(thread_id, snapshot)


async def resume_workflow(
    thread_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    snapshot = await _get_snapshot(thread_id)
    current_interrupt = _extract_interrupt(snapshot)
    if current_interrupt is None:
        raise WorkflowConflictError("workflow 当前没有等待中的人工操作")

    expected_type = current_interrupt.get("type")
    requested_type = _requested_interrupt_type(payload)
    if expected_type != requested_type:
        raise WorkflowConflictError(
            f"workflow 当前等待 {expected_type}，不能提交 {requested_type} 操作"
        )
    _validate_resume_payload(snapshot, requested_type, payload)

    try:
        await get_content_workflow().ainvoke(
            Command(resume=payload),
            config=_graph_config(thread_id),
        )
    except WorkflowNodeInputError as exc:
        raise WorkflowValidationError(str(exc)) from exc

    updated_snapshot = await _get_snapshot(thread_id)
    return _result_from_snapshot(thread_id, updated_snapshot)


async def get_workflow_state(thread_id: str) -> dict[str, Any]:
    snapshot = await _get_snapshot(thread_id)
    return _result_from_snapshot(thread_id, snapshot)
