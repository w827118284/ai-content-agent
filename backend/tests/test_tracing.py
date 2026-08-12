import json
import os
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import Settings, configure_langsmith_environment, settings
from app.graph.runner import WORKFLOW_METADATA_ALLOWLIST, build_workflow_config


LANGSMITH_ENV_VARS = (
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGSMITH_ENDPOINT",
    "LANGSMITH_WORKSPACE_ID",
    "LANGSMITH_HIDE_INPUTS",
    "LANGSMITH_HIDE_OUTPUTS",
)


def test_langsmith_configuration_has_private_optional_defaults(monkeypatch):
    for name in LANGSMITH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    configured = Settings(_env_file=None)

    assert configured.langsmith_tracing is False
    assert configured.langsmith_api_key is None
    assert configured.langsmith_project == "ai-content-agent"
    assert configured.langsmith_endpoint is None
    assert configured.langsmith_workspace_id is None
    assert configured.langsmith_hide_inputs is True
    assert configured.langsmith_hide_outputs is True


def test_official_langsmith_settings_are_forwarded_to_runtime(monkeypatch):
    values = {
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_API_KEY": "unit-test-langsmith-placeholder",
        "LANGSMITH_PROJECT": "unit-test-project",
        "LANGSMITH_ENDPOINT": "https://langsmith.unit.invalid",
        "LANGSMITH_WORKSPACE_ID": "unit-test-workspace",
        "LANGSMITH_HIDE_INPUTS": "true",
        "LANGSMITH_HIDE_OUTPUTS": "true",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    configured = Settings(_env_file=None)

    configure_langsmith_environment(configured)

    assert configured.langsmith_api_key == SecretStr(values["LANGSMITH_API_KEY"])
    assert all(os.environ[name] == value for name, value in values.items())


@pytest.mark.parametrize(
    ("action", "transport", "run_name"),
    [
        ("start", "rest", "content_workflow.start"),
        ("start", "sse", "content_workflow.start"),
        ("resume", "rest", "content_workflow.resume"),
        ("resume", "sse", "content_workflow.resume"),
    ],
)
def test_workflow_config_names_and_transports(
    monkeypatch,
    action,
    transport,
    run_name,
):
    monkeypatch.setattr(settings, "use_mock_llm", True)
    monkeypatch.setattr(settings, "use_mock_image", True)
    thread_id = "trace-thread"

    config = build_workflow_config(
        thread_id,
        action=action,
        transport=transport,
    )

    assert config["configurable"] == {"thread_id": thread_id}
    assert config["run_name"] == run_name
    assert config["metadata"]["workflow_action"] == action
    assert config["metadata"]["transport"] == transport
    assert config["metadata"]["llm_mode"] == "mock"
    assert config["metadata"]["image_mode"] == "mock"
    assert action in config["tags"]
    assert transport in config["tags"]


def test_workflow_config_uses_real_modes_and_allowlisted_metadata(monkeypatch):
    monkeypatch.setattr(settings, "use_mock_llm", False)
    monkeypatch.setattr(settings, "use_mock_image", False)
    project_id = uuid4()
    user_id = uuid4()

    config = build_workflow_config(
        "private-thread-id",
        action="resume",
        transport="sse",
        project_id=project_id,
        user_id=user_id,
    )
    metadata = config["metadata"]

    assert metadata == {
        "thread_id": "private-thread-id",
        "project_id": str(project_id),
        "user_id": str(user_id),
        "workflow_action": "resume",
        "transport": "sse",
        "llm_mode": "real",
        "image_mode": "real",
    }
    assert set(metadata) <= WORKFLOW_METADATA_ALLOWLIST
    assert "real-llm" in config["tags"]
    assert "real-image" in config["tags"]
    assert "private-thread-id" not in config["tags"]
    assert str(project_id) not in config["tags"]
    assert str(user_id) not in config["tags"]


def test_workflow_config_does_not_leak_business_content_or_credentials():
    config = build_workflow_config(
        "safe-thread",
        action="start",
        transport="rest",
        project_id="safe-project",
        user_id="safe-user",
    )
    serialized = json.dumps(config, ensure_ascii=False)
    sensitive_values = (
        "敏感主题正文",
        "敏感文章正文",
        "敏感审核意见",
        "Bearer unit-test-jwt",
        "unit-test-api-key",
    )

    assert all(value not in serialized for value in sensitive_values)
    assert set(config["metadata"]) <= WORKFLOW_METADATA_ALLOWLIST
