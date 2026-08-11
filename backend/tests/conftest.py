import asyncio
import sys

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.graph import nodes
from app.services.image_mock import MockImageService
from app.services.llm_mock import MockLLMService


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(autouse=True)
def jwt_test_configuration(monkeypatch):
    monkeypatch.setenv(
        "JWT_SECRET_KEY",
        "unit-test-jwt-secret-at-least-32-bytes",
    )


@pytest.fixture
def memory_workflow_config(monkeypatch):
    monkeypatch.setattr(settings, "checkpointer_backend", "memory")
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(settings, "use_mock_llm", True)
    monkeypatch.setattr(settings, "use_mock_image", True)
    monkeypatch.setattr(
        settings,
        "jwt_secret_key",
        SecretStr("unit-test-jwt-secret-at-least-32-bytes"),
    )
    monkeypatch.setattr(nodes, "llm_service", MockLLMService())
    monkeypatch.setattr(nodes, "image_service", MockImageService())
