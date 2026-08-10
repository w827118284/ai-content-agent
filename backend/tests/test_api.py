import asyncio

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.main import app


@pytest.fixture(autouse=True)
def initialized_app_lifespan(memory_workflow_config):
    lifespan_context = app.router.lifespan_context(app)
    with asyncio.Runner() as lifespan_runner:
        lifespan_runner.run(lifespan_context.__aenter__())
        try:
            yield
        finally:
            lifespan_runner.run(lifespan_context.__aexit__(None, None, None))


def request(method: str, path: str, **kwargs) -> Response:
    async def send() -> Response:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def start_workflow() -> dict:
    response = request(
        "POST",
        "/api/v1/workflows/start",
        json={"topic_direction": "LangGraph Human-in-the-loop 实战"},
    )
    assert response.status_code == 201
    return response.json()


def select_topic(
    thread_id: str,
    topic_id: str = "topic_1",
) -> dict:
    response = request(
        "POST",
        f"/api/v1/workflows/{thread_id}/resume",
        json={"action": "select_topic", "data": {"topic_id": topic_id}},
    )
    assert response.status_code == 200
    return response.json()


def test_health_and_swagger_are_available():
    assert request("GET", "/health").json() == {"status": "ok"}
    assert request("GET", "/docs").status_code == 200


def test_api_runs_complete_human_in_the_loop_flow():
    started = start_workflow()
    assert started["interrupt"]["type"] == "topic_selection"

    selected = select_topic(started["thread_id"])
    assert selected["interrupt"]["type"] == "article_review"

    rejected_response = request(
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={
            "action": "reject",
            "data": {"feedback": "增加代码示例"},
        },
    )
    assert rejected_response.status_code == 200
    rejected = rejected_response.json()
    assert rejected["state"]["revision_count"] == 1
    assert rejected["status"] == "waiting_article_review"

    approved_response = request(
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={"action": "approve"},
    )
    assert approved_response.status_code == 200
    approved = approved_response.json()
    assert approved["status"] == "completed"
    assert approved["is_completed"] is True

    state_response = request(
        "GET",
        f"/api/v1/workflows/{started['thread_id']}/state"
    )
    assert state_response.status_code == 200
    assert state_response.json()["state"] == approved["state"]


def test_unknown_thread_returns_404():
    response = request("GET", "/api/v1/workflows/unknown-thread/state")
    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]


def test_invalid_topic_id_returns_422():
    started = start_workflow()
    response = request(
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={"action": "select_topic", "data": {"topic_id": "not-found"}},
    )
    assert response.status_code == 422
    assert "无效的 topic_id" in response.json()["detail"]


def test_reject_without_feedback_returns_422():
    started = start_workflow()
    select_topic(started["thread_id"])

    response = request(
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={"action": "reject"},
    )
    assert response.status_code == 422
    assert "feedback" in str(response.json())


def test_invalid_action_returns_422():
    started = start_workflow()
    response = request(
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={"action": "publish"},
    )
    assert response.status_code == 422


def test_action_must_match_current_interrupt():
    started = start_workflow()
    response = request(
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={"action": "approve"},
    )
    assert response.status_code == 409
    assert "不能提交" in response.json()["detail"]
