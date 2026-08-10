import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.config import Settings, settings
from app.services.llm_mock import MockLLMService
from app.services.llm_service import (
    LLMResponseError,
    LLMService,
    LLMServiceError,
    get_llm_service,
)


def run(coroutine):
    return asyncio.run(coroutine)


def build_service(*responses: AIMessage):
    client = MagicMock()
    client.ainvoke = AsyncMock(side_effect=responses)
    with patch("app.services.llm_service.ChatOpenAI", return_value=client):
        service = LLMService(
            api_key="unit-test-placeholder",
            base_url="https://unit.invalid/v1",
            model="unit-test-model",
            temperature=0.2,
        )
    return service, client


def test_settings_read_unprefixed_llm_environment_variables(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "false")
    monkeypatch.setenv("LLM_API_KEY", "unit-test-placeholder")
    monkeypatch.setenv("LLM_BASE_URL", "https://unit.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "unit-test-model")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.35")

    configured = Settings(_env_file=None)

    assert configured.use_mock_llm is False
    assert configured.llm_api_key == "unit-test-placeholder"
    assert configured.llm_base_url == "https://unit.invalid/v1"
    assert configured.llm_model == "unit-test-model"
    assert configured.llm_temperature == 0.35


def test_service_selector_keeps_mock_default_and_builds_real_mode(monkeypatch):
    monkeypatch.setattr(settings, "use_mock_llm", True)
    assert isinstance(get_llm_service(), MockLLMService)

    monkeypatch.setattr(settings, "use_mock_llm", False)
    monkeypatch.setattr(settings, "llm_api_key", "unit-test-placeholder")
    monkeypatch.setattr(settings, "llm_base_url", "https://unit.invalid/v1")
    monkeypatch.setattr(settings, "llm_model", "unit-test-model")
    monkeypatch.setattr(settings, "llm_temperature", 0.4)
    with patch("app.services.llm_service.ChatOpenAI") as chat_openai:
        service = get_llm_service()

    assert isinstance(service, LLMService)
    chat_openai.assert_called_once_with(
        model="unit-test-model",
        api_key="unit-test-placeholder",
        temperature=0.4,
        max_retries=2,
        base_url="https://unit.invalid/v1",
    )


def test_plan_topics_parses_exactly_five_titles():
    titles = [f"技术选题 {index}" for index in range(1, 6)]
    response = AIMessage(content=json.dumps({"topics": titles}, ensure_ascii=False))
    service, client = build_service(response)

    topics = run(service.plan_topics("LangGraph Agent 开发"))

    assert topics == [
        {"id": f"topic_{index}", "title": title}
        for index, title in enumerate(titles, start=1)
    ]
    messages = client.ainvoke.await_args.args[0]
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert "LangGraph Agent 开发" in messages[1].content


def test_plan_topics_rejects_an_invalid_topic_count():
    response = AIMessage(content=json.dumps({"topics": ["选题 1", "选题 2"]}))
    service, _ = build_service(response)

    with pytest.raises(LLMResponseError, match="数据格式不符合要求"):
        run(service.plan_topics("LangGraph"))


def test_write_article_builds_initial_generation_prompt():
    response = AIMessage(content="# LangGraph 实战\n\n文章正文")
    service, client = build_service(response)

    article = run(
        service.write_article(
            topic_direction="AI Agent",
            selected_topic="LangGraph 人工审核实战",
            previous_article=None,
            feedback=None,
            revision_count=0,
        )
    )

    assert article.startswith("# LangGraph 实战")
    user_prompt = client.ainvoke.await_args.args[0][1].content
    assert "AI Agent" in user_prompt
    assert "LangGraph 人工审核实战" in user_prompt
    assert "这是首次生成" in user_prompt


def test_write_article_includes_previous_article_and_reject_feedback():
    response = AIMessage(content="# 重写后的文章\n\n增加了代码示例。")
    service, client = build_service(response)
    previous_article = "# 原文章\n\n这里是原始内容。"
    feedback = "增加 interrupt 代码示例，删除空泛背景"

    article = run(
        service.write_article(
            topic_direction="LangGraph",
            selected_topic="Human-in-the-loop 实战",
            previous_article=previous_article,
            feedback=feedback,
            revision_count=2,
        )
    )

    assert article.startswith("# 重写后的文章")
    user_prompt = client.ainvoke.await_args.args[0][1].content
    assert previous_article in user_prompt
    assert feedback in user_prompt
    assert "当前重写次数：2" in user_prompt
    assert "必须保留原文主题和有效内容" in user_prompt


def test_extract_visual_points_parses_three_to_five_items():
    points = ["状态流转", "interrupt 恢复机制", "Reject 条件路由", "checkpoint 持久化"]
    response = AIMessage(
        content=f"```json\n{json.dumps({'visual_points': points}, ensure_ascii=False)}\n```"
    )
    service, client = build_service(response)

    result = run(
        service.extract_visual_points(
            selected_topic="LangGraph 工作流",
            article_content="# LangGraph 工作流\n\n文章内容",
        )
    )

    assert result == points
    user_prompt = client.ainvoke.await_args.args[0][1].content
    assert "LangGraph 工作流" in user_prompt
    assert "文章内容" in user_prompt


def test_real_llm_api_failure_raises_a_clear_service_error():
    client = MagicMock()
    client.ainvoke = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    with patch("app.services.llm_service.ChatOpenAI", return_value=client):
        service = LLMService(
            api_key="unit-test-placeholder",
            base_url="https://unit.invalid/v1",
            model="unit-test-model",
            temperature=0.2,
        )

    with pytest.raises(LLMServiceError, match="真实 LLM API 调用失败"):
        run(service.plan_topics("LangGraph"))


@pytest.mark.skipif(
    not all([settings.llm_api_key, settings.llm_base_url, settings.llm_model]),
    reason="缺少 LLM_API_KEY、LLM_BASE_URL 或 LLM_MODEL",
)
def test_real_llm_plan_topics_integration():
    service = LLMService(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
    )

    topics = run(service.plan_topics("LangGraph Human-in-the-loop 实战"))

    assert len(topics) == 5
    assert all(topic["id"] == f"topic_{index}" for index, topic in enumerate(topics, 1))
