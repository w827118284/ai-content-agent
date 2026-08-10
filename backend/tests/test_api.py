import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.api.v1 import workflows as workflow_api
from app.core.config import settings
from app.main import app
from app.repositories.content_project_repository import (
    get_content_project_repository,
)
from app.repositories.user_repository import (
    DuplicateUsernameError,
    get_user_repository,
)
from app.services.auth_service import (
    create_access_token,
    hash_password,
    verify_password,
)


TEST_SECRET = "unit-test-jwt-secret-at-least-32-bytes"
TEST_PASSWORD = "phase6-password"
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


class FakeUserRepository:
    def __init__(self) -> None:
        self.users_by_id: dict[UUID, SimpleNamespace] = {}
        self.users_by_username: dict[str, SimpleNamespace] = {}

    def add_user(
        self,
        username: str,
        *,
        password_hash: str = TEST_PASSWORD_HASH,
        is_active: bool = True,
    ) -> SimpleNamespace:
        user = SimpleNamespace(
            id=uuid4(),
            username=username,
            password_hash=password_hash,
            is_active=is_active,
            created_at=datetime.now(UTC),
        )
        self.users_by_id[user.id] = user
        self.users_by_username[user.username] = user
        return user

    async def create_user(self, *, username: str, password_hash: str):
        if username in self.users_by_username:
            raise DuplicateUsernameError(username)
        return self.add_user(username, password_hash=password_hash)

    async def get_by_username(self, username: str):
        return self.users_by_username.get(username)

    async def get_by_id(self, user_id: UUID):
        return self.users_by_id.get(user_id)


class FakeContentProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[str, SimpleNamespace] = {}
        self.fail_create = False
        self.fail_sync = False
        self.update_calls = 0
        self.delete_calls = 0

    def seed_project(
        self,
        *,
        user_id: UUID | None,
        thread_id: str,
        topic_direction: str = "Seeded project",
        status: str = "waiting_topic_selection",
        revision_count: int = 0,
        selected_topic_title: str | None = None,
    ) -> SimpleNamespace:
        now = datetime.now(UTC)
        project = SimpleNamespace(
            id=uuid4(),
            user_id=user_id,
            thread_id=thread_id,
            topic_direction=topic_direction,
            selected_topic_title=selected_topic_title,
            status=status,
            revision_count=revision_count,
            created_at=now,
            updated_at=now,
        )
        self.projects[thread_id] = project
        return project

    async def create_project(self, **values):
        if self.fail_create:
            raise RuntimeError("simulated ownership write failure")
        return self.seed_project(**values)

    async def get_by_thread_id(self, thread_id: str):
        return self.projects.get(thread_id)

    async def get_by_thread_id_for_user(self, thread_id: str, user_id: UUID):
        project = self.projects.get(thread_id)
        if project is None or project.user_id != user_id:
            return None
        return project

    async def list_projects(self, *, user_id: UUID, limit: int, offset: int):
        projects = sorted(
            (
                project
                for project in self.projects.values()
                if project.user_id == user_id
            ),
            key=lambda project: (project.updated_at, project.created_at),
            reverse=True,
        )
        return projects[offset : offset + limit], len(projects)

    async def update_from_state(self, thread_id: str, user_id: UUID, state):
        if self.fail_sync:
            raise RuntimeError("simulated metadata sync failure")
        self.update_calls += 1
        project = await self.get_by_thread_id_for_user(thread_id, user_id)
        if project is None:
            return None
        project.selected_topic_title = state["selected_topic"]
        project.status = state["status"]
        project.revision_count = state["revision_count"]
        project.updated_at = datetime.now(UTC)
        return project

    async def delete_by_thread_id_for_user(self, thread_id: str, user_id: UUID):
        self.delete_calls += 1
        project = await self.get_by_thread_id_for_user(thread_id, user_id)
        if project is None:
            return False
        del self.projects[thread_id]
        return True


def token_for(user_id: UUID, *, expires_delta: timedelta | None = None) -> str:
    return create_access_token(
        user_id,
        secret_key=TEST_SECRET,
        algorithm="HS256",
        expires_delta=expires_delta or timedelta(hours=1),
    )


@pytest.fixture(autouse=True)
def api_context(memory_workflow_config):
    user_repository = FakeUserRepository()
    project_repository = FakeContentProjectRepository()
    user = user_repository.add_user("phase6_user_a")
    context = SimpleNamespace(
        user_repository=user_repository,
        project_repository=project_repository,
        user=user,
        token=token_for(user.id),
    )
    app.dependency_overrides[get_user_repository] = lambda: user_repository
    app.dependency_overrides[get_content_project_repository] = lambda: project_repository

    lifespan_context = app.router.lifespan_context(app)
    with asyncio.Runner() as lifespan_runner:
        lifespan_runner.run(lifespan_context.__aenter__())
        try:
            yield context
        finally:
            lifespan_runner.run(lifespan_context.__aexit__(None, None, None))
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_content_project_repository, None)


def request(
    context,
    method: str,
    path: str,
    *,
    authenticated: bool = True,
    token: str | None = None,
    raise_app_exceptions: bool = True,
    **kwargs,
) -> Response:
    headers = dict(kwargs.pop("headers", {}))
    if authenticated:
        headers["Authorization"] = f"Bearer {token or context.token}"

    async def send() -> Response:
        transport = ASGITransport(
            app=app,
            raise_app_exceptions=raise_app_exceptions,
        )
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, headers=headers, **kwargs)

    return asyncio.run(send())


def start_workflow(context, *, token: str | None = None) -> dict:
    response = request(
        context,
        "POST",
        "/api/v1/workflows/start",
        token=token,
        json={"topic_direction": "LangGraph Human-in-the-loop 实战"},
    )
    assert response.status_code == 201
    return response.json()


def select_topic(
    context,
    thread_id: str,
    topic_id: str = "topic_1",
    *,
    token: str | None = None,
) -> dict:
    response = request(
        context,
        "POST",
        f"/api/v1/workflows/{thread_id}/resume",
        token=token,
        json={"action": "select_topic", "data": {"topic_id": topic_id}},
    )
    assert response.status_code == 200
    return response.json()


def test_health_and_swagger_are_available(api_context):
    assert request(api_context, "GET", "/health", authenticated=False).json() == {
        "status": "ok"
    }
    assert (
        request(api_context, "GET", "/docs", authenticated=False).status_code == 200
    )


def test_cors_allows_authorization_from_configured_frontend_origin(api_context):
    response = request(
        api_context,
        "OPTIONS",
        "/api/v1/workflows/start",
        authenticated=False,
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers
    assert response.headers.get("access-control-allow-credentials") is None


def test_register_hashes_password_and_does_not_return_hash(api_context):
    response = request(
        api_context,
        "POST",
        "/api/v1/auth/register",
        authenticated=False,
        json={"username": "registered_user", "password": "registered-password"},
    )

    assert response.status_code == 201
    assert "password_hash" not in response.json()
    user = api_context.user_repository.users_by_username["registered_user"]
    assert user.password_hash != "registered-password"
    assert verify_password("registered-password", user.password_hash)


def test_duplicate_username_returns_409(api_context):
    body = {"username": "duplicate_user", "password": "duplicate-password"}
    first = request(
        api_context,
        "POST",
        "/api/v1/auth/register",
        authenticated=False,
        json=body,
    )
    second = request(
        api_context,
        "POST",
        "/api/v1/auth/register",
        authenticated=False,
        json=body,
    )
    assert first.status_code == 201
    assert second.status_code == 409


def test_valid_login_returns_access_token(api_context):
    response = request(
        api_context,
        "POST",
        "/api/v1/auth/login",
        authenticated=False,
        json={"username": api_context.user.username, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["expires_in"] == 3600
    assert response.json()["access_token"]


def test_wrong_password_returns_generic_401(api_context):
    response = request(
        api_context,
        "POST",
        "/api/v1/auth/login",
        authenticated=False,
        json={"username": api_context.user.username, "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_returns_current_user_for_valid_token(api_context):
    response = request(api_context, "GET", "/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["id"] == str(api_context.user.id)
    assert response.json()["username"] == api_context.user.username
    assert "password_hash" not in response.json()


def test_invalid_and_expired_tokens_return_401(api_context):
    invalid = request(
        api_context,
        "GET",
        "/api/v1/auth/me",
        token="not-a-jwt",
    )
    expired = create_access_token(
        api_context.user.id,
        secret_key=TEST_SECRET,
        algorithm="HS256",
        now=datetime.now(UTC) - timedelta(minutes=2),
        expires_delta=timedelta(minutes=1),
    )
    expired_response = request(
        api_context,
        "GET",
        "/api/v1/auth/me",
        token=expired,
    )
    assert invalid.status_code == 401
    assert expired_response.status_code == 401


def test_protected_projects_and_workflows_require_token(api_context):
    projects = request(
        api_context,
        "GET",
        "/api/v1/projects",
        authenticated=False,
    )
    state = request(
        api_context,
        "GET",
        "/api/v1/workflows/missing/state",
        authenticated=False,
    )
    resume = request(
        api_context,
        "POST",
        "/api/v1/workflows/missing/resume",
        authenticated=False,
        json={"action": "approve"},
    )
    assert projects.status_code == 401
    assert state.status_code == 401
    assert resume.status_code == 401


def test_api_runs_complete_human_in_the_loop_flow(api_context):
    started = start_workflow(api_context)
    assert started["interrupt"]["type"] == "topic_selection"

    selected = select_topic(api_context, started["thread_id"])
    assert selected["interrupt"]["type"] == "article_review"

    rejected_response = request(
        api_context,
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
        api_context,
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={"action": "approve"},
    )
    assert approved_response.status_code == 200
    approved = approved_response.json()
    assert approved["status"] == "completed"
    assert approved["is_completed"] is True

    state_response = request(
        api_context,
        "GET",
        f"/api/v1/workflows/{started['thread_id']}/state",
    )
    assert state_response.status_code == 200
    assert state_response.json()["state"] == approved["state"]


def test_unknown_thread_returns_404(api_context):
    response = request(
        api_context,
        "GET",
        "/api/v1/workflows/unknown-thread/state",
    )
    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]


def test_invalid_topic_id_returns_422(api_context):
    started = start_workflow(api_context)
    response = request(
        api_context,
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={"action": "select_topic", "data": {"topic_id": "not-found"}},
    )
    assert response.status_code == 422
    assert "无效的 topic_id" in response.json()["detail"]


def test_reject_without_feedback_returns_422(api_context):
    started = start_workflow(api_context)
    select_topic(api_context, started["thread_id"])
    response = request(
        api_context,
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={"action": "reject"},
    )
    assert response.status_code == 422
    assert "feedback" in str(response.json())


def test_invalid_action_returns_422(api_context):
    started = start_workflow(api_context)
    response = request(
        api_context,
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={"action": "publish"},
    )
    assert response.status_code == 422


def test_action_must_match_current_interrupt(api_context):
    started = start_workflow(api_context)
    response = request(
        api_context,
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={"action": "approve"},
    )
    assert response.status_code == 409
    assert "不能提交" in response.json()["detail"]


def test_start_and_resume_keep_owned_project_metadata_in_sync(api_context):
    started = start_workflow(api_context)
    project = api_context.project_repository.projects[started["thread_id"]]
    assert project.user_id == api_context.user.id
    assert project.topic_direction == "LangGraph Human-in-the-loop 实战"
    assert project.status == "waiting_topic_selection"

    selected = select_topic(api_context, started["thread_id"])
    assert project.selected_topic_title == selected["state"]["selected_topic"]
    assert project.status == "waiting_article_review"

    rejected = request(
        api_context,
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        json={
            "action": "reject",
            "data": {"feedback": "增加真实代码示例"},
        },
    )
    assert rejected.status_code == 200
    assert project.revision_count == 1


def test_start_rejects_client_supplied_user_id(api_context):
    response = request(
        api_context,
        "POST",
        "/api/v1/workflows/start",
        json={
            "topic_direction": "伪造归属",
            "user_id": str(uuid4()),
        },
    )
    assert response.status_code == 422
    assert not api_context.project_repository.projects


def test_projects_endpoint_filters_by_current_user_and_paginates(api_context):
    first = start_workflow(api_context)
    second = start_workflow(api_context)
    third = start_workflow(api_context)
    user_b = api_context.user_repository.add_user("phase6_user_b")
    api_context.project_repository.seed_project(
        user_id=user_b.id,
        thread_id="user-b-project",
    )

    response = request(api_context, "GET", "/api/v1/projects?limit=1&offset=1")
    payload = response.json()
    assert response.status_code == 200
    assert payload["total"] == 3
    assert [item["thread_id"] for item in payload["items"]] == [second["thread_id"]]
    assert third["thread_id"] != first["thread_id"]
    assert "article_content" not in payload["items"][0]
    assert all(item["thread_id"] != "user-b-project" for item in payload["items"])


def test_legacy_unowned_project_is_hidden(api_context):
    api_context.project_repository.seed_project(
        user_id=None,
        thread_id="legacy-unowned",
    )
    response = request(api_context, "GET", "/api/v1/projects")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


def test_user_b_cannot_get_user_a_thread_before_graph_access(api_context, monkeypatch):
    started = start_workflow(api_context)
    user_b = api_context.user_repository.add_user("ownership_user_b")
    called = False

    async def forbidden_graph_access(thread_id: str):
        nonlocal called
        called = True
        raise AssertionError(f"Graph accessed for {thread_id}")

    monkeypatch.setattr(workflow_api, "get_workflow_state", forbidden_graph_access)
    response = request(
        api_context,
        "GET",
        f"/api/v1/workflows/{started['thread_id']}/state",
        token=token_for(user_b.id),
    )
    assert response.status_code == 404
    assert called is False


def test_user_b_cannot_resume_user_a_thread_before_graph_access(
    api_context,
    monkeypatch,
):
    started = start_workflow(api_context)
    user_b = api_context.user_repository.add_user("resume_user_b")
    called = False

    async def forbidden_graph_access(thread_id: str, payload: dict):
        nonlocal called
        called = True
        raise AssertionError(f"Graph accessed for {thread_id}: {payload}")

    monkeypatch.setattr(workflow_api, "resume_workflow", forbidden_graph_access)
    response = request(
        api_context,
        "POST",
        f"/api/v1/workflows/{started['thread_id']}/resume",
        token=token_for(user_b.id),
        json={"action": "select_topic", "data": {"topic_id": "topic_1"}},
    )
    assert response.status_code == 404
    assert called is False


def test_get_state_does_not_backfill_missing_ownership_row(api_context):
    started = start_workflow(api_context)
    del api_context.project_repository.projects[started["thread_id"]]
    response = request(
        api_context,
        "GET",
        f"/api/v1/workflows/{started['thread_id']}/state",
    )
    assert response.status_code == 404
    assert started["thread_id"] not in api_context.project_repository.projects


def test_get_state_does_not_touch_existing_project_updated_at(api_context):
    started = start_workflow(api_context)
    project = api_context.project_repository.projects[started["thread_id"]]
    original_updated_at = project.updated_at
    original_update_calls = api_context.project_repository.update_calls
    response = request(
        api_context,
        "GET",
        f"/api/v1/workflows/{started['thread_id']}/state",
    )
    assert response.status_code == 200
    assert project.updated_at == original_updated_at
    assert api_context.project_repository.update_calls == original_update_calls


def test_graph_start_failure_removes_starting_ownership_row(api_context, monkeypatch):
    async def fail_start(topic_direction: str, thread_id: str | None = None):
        raise RuntimeError(f"simulated graph failure: {topic_direction} {thread_id}")

    monkeypatch.setattr(workflow_api, "start_workflow", fail_start)
    response = request(
        api_context,
        "POST",
        "/api/v1/workflows/start",
        json={"topic_direction": "Graph failure compensation"},
        raise_app_exceptions=False,
    )
    assert response.status_code == 500
    assert api_context.project_repository.projects == {}
    assert api_context.project_repository.delete_calls == 1


def test_resume_metadata_sync_failure_does_not_change_graph_response(api_context):
    started = start_workflow(api_context)
    api_context.project_repository.fail_sync = True
    selected = select_topic(api_context, started["thread_id"])
    assert selected["status"] == "waiting_article_review"
    assert selected["state"]["article_content"]
