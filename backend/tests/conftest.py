import asyncio
import sys

import pytest

from app.core.config import settings
from app.graph import nodes
from app.services.llm_mock import MockLLMService


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
def memory_workflow_config(monkeypatch):
    monkeypatch.setattr(settings, "checkpointer_backend", "memory")
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(settings, "use_mock_llm", True)
    monkeypatch.setattr(nodes, "llm_service", MockLLMService())
