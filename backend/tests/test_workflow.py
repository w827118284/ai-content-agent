import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.graph.runner import (
    WorkflowConflictError,
    WorkflowValidationError,
    get_workflow_state,
    resume_workflow,
    start_workflow,
)
from app.main import app
from app.graph import nodes
from app.services.image_service import ImageServiceError


@pytest.fixture(autouse=True)
def initialized_workflow_runtime(memory_workflow_config):
    lifespan_context = app.router.lifespan_context(app)
    with asyncio.Runner() as lifespan_runner:
        lifespan_runner.run(lifespan_context.__aenter__())
        try:
            yield
        finally:
            lifespan_runner.run(lifespan_context.__aexit__(None, None, None))


def run(coroutine):
    return asyncio.run(coroutine)


def start_and_select(topic_id: str = "topic_1"):
    started = run(start_workflow("LangGraph Agent 开发"))
    selected = run(resume_workflow(started["thread_id"], {"topic_id": topic_id}))
    return started, selected


def test_start_stops_at_topic_selection():
    result = run(start_workflow("LangGraph Agent 开发"))

    assert result["thread_id"]
    assert result["status"] == "waiting_topic_selection"
    assert result["is_completed"] is False
    assert result["interrupt"]["type"] == "topic_selection"
    assert len(result["state"]["generated_topics"]) == 5
    assert "thread_id" not in result["state"]


def test_tracing_disabled_keeps_workflow_behavior_without_tracer(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")

    with patch("langchain_core.tracers.langchain.LangChainTracer") as tracer:
        result = run(start_workflow("LangGraph tracing disabled"))

    assert result["status"] == "waiting_topic_selection"
    assert result["interrupt"]["type"] == "topic_selection"
    tracer.assert_not_called()


def test_select_topic_generates_article_and_stops_at_review():
    started = run(start_workflow("LangGraph Agent 开发"))
    chosen = started["state"]["generated_topics"][1]

    result = run(
        resume_workflow(started["thread_id"], {"topic_id": chosen["id"]})
    )

    assert result["state"]["selected_topic"] == chosen["title"]
    assert result["state"]["article_content"]
    assert result["state"]["review_status"] == "pending"
    assert result["status"] == "waiting_article_review"
    assert result["interrupt"]["type"] == "article_review"


def test_reject_rewrites_article_and_returns_to_review():
    started, selected = start_and_select()
    old_article = selected["state"]["article_content"]
    feedback = "增加 interrupt 示例，减少废话"

    result = run(
        resume_workflow(
            started["thread_id"],
            {"action": "reject", "feedback": feedback},
        )
    )

    new_article = result["state"]["article_content"]
    assert result["state"]["revision_count"] == 1
    assert new_article != old_article
    assert feedback in new_article
    assert result["state"]["review_status"] == "pending"
    assert result["status"] == "waiting_article_review"
    assert result["interrupt"]["type"] == "article_review"


def test_three_consecutive_rejects_keep_looping():
    started, _ = start_and_select()

    for index in range(1, 4):
        result = run(
            resume_workflow(
                started["thread_id"],
                {"action": "reject", "feedback": f"第 {index} 次增加具体示例"},
            )
        )
        assert result["state"]["revision_count"] == index
        assert result["status"] == "waiting_article_review"
        assert result["interrupt"]["type"] == "article_review"


def test_approve_after_rejects_completes_graph():
    started, _ = start_and_select()
    for index in range(2):
        run(
            resume_workflow(
                started["thread_id"],
                {"action": "reject", "feedback": f"补充案例 {index + 1}"},
            )
        )

    result = run(resume_workflow(started["thread_id"], {"action": "approve"}))

    visual_points = result["state"]["visual_points"]
    image_urls = result["state"]["image_urls"]
    assert result["state"]["review_status"] == "approved"
    assert result["state"]["review_feedback"] is None
    assert 3 <= len(visual_points) <= 5
    assert len(image_urls) == len(visual_points)
    assert result["status"] == "completed"
    assert result["is_completed"] is True
    assert result["interrupt"] is None


def test_image_service_runs_once_on_approve_and_not_on_state_reads(monkeypatch):
    image_service = MagicMock()
    image_service.generate_images = AsyncMock(
        side_effect=lambda points: [
            f"https://images.example.test/{index}.jpeg"
            for index, _ in enumerate(points)
        ]
    )
    monkeypatch.setattr(nodes, "image_service", image_service)
    started, _ = start_and_select()

    completed = run(resume_workflow(started["thread_id"], {"action": "approve"}))
    first_read = run(get_workflow_state(started["thread_id"]))
    second_read = run(get_workflow_state(started["thread_id"]))

    points = completed["state"]["visual_points"]
    image_service.generate_images.assert_awaited_once_with(points)
    assert completed["state"]["image_urls"] == first_read["state"]["image_urls"]
    assert first_read["state"]["image_urls"] == second_read["state"]["image_urls"]


def test_generate_images_node_reuses_existing_urls_without_provider_call(monkeypatch):
    image_service = MagicMock()
    image_service.generate_images = AsyncMock()
    monkeypatch.setattr(nodes, "image_service", image_service)
    state = {
        "visual_points": ["A", "B"],
        "image_urls": ["/media/images/a.png", "/media/images/b.png"],
    }

    result = run(nodes.generate_images(state))  # type: ignore[arg-type]

    assert result == {"image_urls": state["image_urls"], "status": "completed"}
    image_service.generate_images.assert_not_awaited()


def test_image_failure_persists_terminal_failed_state(monkeypatch):
    image_service = MagicMock()
    image_service.generate_images = AsyncMock(
        side_effect=ImageServiceError(
            "真实图片 API 调用失败",
            status_code=504,
            error_code="timeout",
        )
    )
    monkeypatch.setattr(nodes, "image_service", image_service)
    started, _ = start_and_select()

    failed = run(resume_workflow(started["thread_id"], {"action": "approve"}))
    restored = run(get_workflow_state(started["thread_id"]))

    assert failed["status"] == "failed"
    assert failed["is_completed"] is False
    assert failed["interrupt"] is None
    assert restored["state"]["status"] == "failed"
    assert restored["state"]["image_urls"] == []
    image_service.generate_images.assert_awaited_once()


def test_reject_path_does_not_call_image_service(monkeypatch):
    image_service = MagicMock()
    image_service.generate_images = AsyncMock()
    monkeypatch.setattr(nodes, "image_service", image_service)
    started, _ = start_and_select()

    result = run(
        resume_workflow(
            started["thread_id"],
            {"action": "reject", "feedback": "增加具体代码"},
        )
    )

    assert result["status"] == "waiting_article_review"
    image_service.generate_images.assert_not_awaited()


def test_threads_are_isolated():
    thread_a = run(start_workflow("LangGraph 工作流 A"))
    thread_b = run(start_workflow("LangGraph 工作流 B"))

    result_a = run(resume_workflow(thread_a["thread_id"], {"topic_id": "topic_1"}))
    result_b = run(resume_workflow(thread_b["thread_id"], {"topic_id": "topic_3"}))
    state_a = run(get_workflow_state(thread_a["thread_id"]))["state"]
    state_b = run(get_workflow_state(thread_b["thread_id"]))["state"]

    assert result_a["state"]["selected_topic"] != result_b["state"]["selected_topic"]
    assert state_a["topic_direction"] == "LangGraph 工作流 A"
    assert state_b["topic_direction"] == "LangGraph 工作流 B"
    assert state_a["article_content"] != state_b["article_content"]


def test_invalid_topic_and_mismatched_action_are_rejected():
    started = run(start_workflow("LangGraph Agent 开发"))

    with pytest.raises(WorkflowValidationError, match="无效的 topic_id"):
        run(resume_workflow(started["thread_id"], {"topic_id": "missing"}))

    with pytest.raises(WorkflowConflictError, match="不能提交"):
        run(resume_workflow(started["thread_id"], {"action": "approve"}))

    recovered = run(
        resume_workflow(started["thread_id"], {"topic_id": "topic_1"})
    )
    assert recovered["status"] == "waiting_article_review"
    assert recovered["interrupt"]["type"] == "article_review"
