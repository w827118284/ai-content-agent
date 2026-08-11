import asyncio
import json
import traceback
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import SecretStr

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
        )
    return service, client


def test_settings_read_unprefixed_llm_environment_variables(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "false")
    monkeypatch.setenv("LLM_API_KEY", "unit-test-placeholder")
    monkeypatch.setenv("LLM_BASE_URL", "https://unit.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "unit-test-model")

    configured = Settings(_env_file=None)

    assert configured.use_mock_llm is False
    assert configured.llm_api_key == SecretStr("unit-test-placeholder")
    assert configured.llm_base_url == "https://unit.invalid/v1"
    assert configured.llm_model == "unit-test-model"


def test_service_selector_keeps_mock_default_and_builds_real_mode(monkeypatch):
    monkeypatch.setattr(settings, "use_mock_llm", True)
    assert isinstance(get_llm_service(), MockLLMService)

    monkeypatch.setattr(settings, "use_mock_llm", False)
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("unit-test-placeholder"))
    monkeypatch.setattr(settings, "llm_base_url", "https://unit.invalid/v1")
    monkeypatch.setattr(settings, "llm_model", "unit-test-model")
    with patch("app.services.llm_service.ChatOpenAI") as chat_openai:
        service = get_llm_service()

    assert isinstance(service, LLMService)
    chat_openai.assert_called_once_with(
        model="unit-test-model",
        api_key="unit-test-placeholder",
        max_retries=0,
        base_url="https://unit.invalid/v1",
    )


def test_real_service_uses_deepseek_chat_completions_options_only():
    with patch("app.services.llm_service.ChatOpenAI") as chat_openai:
        LLMService(
            api_key="unit-test-placeholder",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-pro",
        )

    chat_openai.assert_called_once_with(
        model="deepseek-v4-pro",
        api_key="unit-test-placeholder",
        max_retries=0,
        base_url="https://api.deepseek.com",
    )


def test_responses_style_message_extracts_only_final_text():
    response = AIMessage(
        content=[
            {"type": "reasoning", "reasoning": "internal reasoning"},
            {"type": "text", "text": "最终业务文本"},
        ]
    )
    service, _ = build_service(response)

    assert run(service.write_article(
        topic_direction="AI Agent",
        selected_topic="Responses API",
        previous_article=None,
        feedback=None,
        revision_count=0,
    )) == "最终业务文本"


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
        )

    with pytest.raises(LLMServiceError, match="真实 LLM API 调用失败") as exc_info:
        run(service.plan_topics("LangGraph"))

    formatted = "".join(
        traceback.format_exception(
            type(exc_info.value),
            exc_info.value,
            exc_info.value.__traceback__,
        )
    )
    assert "provider unavailable" not in formatted


@pytest.mark.skip(reason="真实文字 Provider 仅通过显式 smoke test 调用")
def test_real_llm_plan_topics_integration():
    service = LLMService(
        api_key=(
            settings.llm_api_key.get_secret_value()
            if settings.llm_api_key is not None
            else None
        ),
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )

    topics = run(service.plan_topics("LangGraph Human-in-the-loop 实战"))

    assert len(topics) == 5
    assert all(topic["id"] == f"topic_{index}" for index, topic in enumerate(topics, 1))
