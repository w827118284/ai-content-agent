import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.main import app
from app.repositories.content_project_repository import (
    get_content_project_repository,
)


class FakeContentProjectRepository:
    def __init__(self):
        self.projects: dict[str, SimpleNamespace] = {}
        self.fail_writes = False
        self.update_calls = 0

    async def create_project(self, **values):
        if self.fail_writes:
            raise RuntimeError("simulated history write failure")
        now = datetime.now(UTC)
        values.setdefault("selected_topic_title", None)
        project = SimpleNamespace(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            **values,
        )
        self.projects[project.thread_id] = project
        return project

    async def get_by_thread_id(self, thread_id):
        return self.projects.get(thread_id)

    async def list_projects(self, *, limit, offset):
        projects = sorted(
            self.projects.values(),
            key=lambda project: (project.updated_at, project.created_at),
            reverse=True,
        )
        return projects[offset : offset + limit], len(projects)

    async def update_from_state(self, thread_id, state):
        if self.fail_writes:
            raise RuntimeError("simulated history write failure")
        self.update_calls += 1
        project = self.projects.get(thread_id)
        if project is None:
            return None
        project.selected_topic_title = state["selected_topic"]
        project.status = state["status"]
        project.revision_count = state["revision_count"]
        project.updated_at = datetime.now(UTC)
        return project


@pytest.fixture(autouse=True)
def initialized_app_lifespan(memory_workflow_config):
    lifespan_context = app.router.lifespan_context(app)
    with asyncio.Runner() as lifespan_runner:
        lifespan_runner.run(lifespan_context.__aenter__())
        try:
            yield
        finally:
            lifespan_runner.run(lifespan_context.__aexit__(None, None, None))


@pytest.fixture
def project_repository():
    repository = FakeContentProjectRepository()
    app.dependency_overrides[get_content_project_repository] = lambda: repository
    try:
        yield repository
    finally:
        app.dependency_overrides.pop(get_content_project_repository, None)


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


def test_cors_allows_configured_frontend_origin():
    response = request(
        "OPTIONS",
        "/api/v1/workflows/start",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://localhost:5173"
    )
    assert "POST" in response.headers["access-control-allow-methods"]


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


def test_start_and_resume_keep_project_metadata_in_sync(project_repository):
    started = start_workflow()
    project = project_repository.projects[started["thread_id"]]
    assert project.topic_direction == "LangGraph Human-in-the-loop 实战"
    assert project.status == "waiting_topic_selection"

    selected = select_topic(started["thread_id"])
    assert project.selected_topic_title == selected["state"]["selected_topic"]
    assert project.status == "waiting_article_review"

    rejected = request(
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={
            "action": "reject",
            "data": {"feedback": "增加真实代码示例"},
        },
    )
    assert rejected.status_code == 200
    assert project.revision_count == 1
    assert project.status == "waiting_article_review"

    approved = request(
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={"action": "approve"},
    )
    assert approved.status_code == 200
    assert project.status == "completed"


def test_projects_endpoint_returns_recent_items_with_pagination(project_repository):
    first = start_workflow()
    second = start_workflow()
    third = start_workflow()

    response = request("GET", "/api/v1/projects?limit=1&offset=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 1
    assert payload["offset"] == 1
    assert [item["thread_id"] for item in payload["items"]] == [
        second["thread_id"]
    ]
    assert third["thread_id"] != first["thread_id"]
    assert "article_content" not in payload["items"][0]


def test_get_state_backfills_missing_project_row(project_repository):
    project_repository.fail_writes = True
    started = start_workflow()
    assert started["thread_id"] not in project_repository.projects

    project_repository.fail_writes = False
    response = request(
        "GET",
        f"/api/v1/workflows/{started['thread_id']}/state",
    )

    assert response.status_code == 200
    project = project_repository.projects[started["thread_id"]]
    assert project.topic_direction == started["state"]["topic_direction"]
    assert project.status == "waiting_topic_selection"


def test_get_state_does_not_touch_existing_project_updated_at(project_repository):
    started = start_workflow()
    project = project_repository.projects[started["thread_id"]]
    original_updated_at = project.updated_at
    original_update_calls = project_repository.update_calls

    response = request(
        "GET",
        f"/api/v1/workflows/{started['thread_id']}/state",
    )

    assert response.status_code == 200
    assert project.updated_at == original_updated_at
    assert project_repository.update_calls == original_update_calls


def test_history_sync_failure_does_not_change_graph_response(project_repository):
    project_repository.fail_writes = True

    started = start_workflow()
    assert started["status"] == "waiting_topic_selection"

    selected = select_topic(started["thread_id"])
    assert selected["status"] == "waiting_article_review"
    assert selected["state"]["article_content"]
