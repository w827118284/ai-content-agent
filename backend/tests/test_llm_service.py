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
from app.services.provider_guard import CircuitBreaker


def run(coroutine):
    return asyncio.run(coroutine)


class StatusProviderError(RuntimeError):
    def __init__(self, status_code: int, message: str = "unit-test failure") -> None:
        super().__init__(message)
        self.status_code = status_code


def build_service(*responses: object, **service_options):
    client = MagicMock()
    client.ainvoke = AsyncMock(side_effect=responses)
    service_options.setdefault("retry_sleep", AsyncMock())
    with patch("app.services.llm_service.ChatOpenAI", return_value=client):
        service = LLMService(
            api_key="unit-test-placeholder",
            base_url="https://unit.invalid/v1",
            model="unit-test-model",
            **service_options,
        )
    return service, client


def topic_response() -> AIMessage:
    return AIMessage(
        content=json.dumps({"topics": [f"技术选题 {index}" for index in range(1, 6)]})
    )


def test_settings_read_unprefixed_llm_environment_variables(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "false")
    monkeypatch.setenv("LLM_API_KEY", "unit-test-placeholder")
    monkeypatch.setenv("LLM_BASE_URL", "https://unit.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "unit-test-model")
    monkeypatch.setenv("LLM_MAX_CONCURRENCY", "2")
    monkeypatch.setenv("LLM_REQUESTS_PER_MINUTE", "12")
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("LLM_RETRY_BASE_DELAY_SECONDS", "0.25")

    configured = Settings(_env_file=None)

    assert configured.use_mock_llm is False
    assert configured.llm_api_key == SecretStr("unit-test-placeholder")
    assert configured.llm_base_url == "https://unit.invalid/v1"
    assert configured.llm_model == "unit-test-model"
    assert configured.llm_max_concurrency == 2
    assert configured.llm_requests_per_minute == 12
    assert configured.llm_max_attempts == 2
    assert configured.llm_retry_base_delay_seconds == 0.25


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
    assert service._client.ainvoke.await_count == 1


def test_timeout_retries_once_then_succeeds():
    limiter = MagicMock()
    limiter.acquire = AsyncMock()
    service, client = build_service(
        TimeoutError("unit-test transient timeout"),
        topic_response(),
        rate_limiter=limiter,
    )

    topics = run(service.plan_topics("LangGraph"))

    assert len(topics) == 5
    assert client.ainvoke.await_count == 2
    assert limiter.acquire.await_count == 2


def test_rate_limit_retries_once_then_succeeds():
    service, client = build_service(
        StatusProviderError(429),
        topic_response(),
    )

    assert len(run(service.plan_topics("LangGraph"))) == 5
    assert client.ainvoke.await_count == 2


def test_server_error_retries_once_then_returns_sanitized_failure():
    service, client = build_service(
        StatusProviderError(500),
        StatusProviderError(503),
    )

    with pytest.raises(LLMServiceError) as exc_info:
        run(service.plan_topics("LangGraph"))

    assert str(exc_info.value) == "真实 LLM API 调用失败"
    assert exc_info.value.category == "server_error"
    assert client.ainvoke.await_count == 2


@pytest.mark.parametrize(
    ("status_code", "category"),
    [
        (400, "bad_request"),
        (401, "authentication"),
        (403, "permission"),
        (404, "not_found"),
    ],
)
def test_nonretryable_http_failure_uses_one_attempt(status_code, category):
    service, client = build_service(StatusProviderError(status_code))

    with pytest.raises(LLMServiceError) as exc_info:
        run(service.plan_topics("LangGraph"))

    assert exc_info.value.category == category
    assert client.ainvoke.await_count == 1


def test_connection_failure_retries_once():
    service, client = build_service(
        ConnectionError("unit-test connection failure"),
        topic_response(),
    )

    assert len(run(service.plan_topics("LangGraph"))) == 5
    assert client.ainvoke.await_count == 2


def test_llm_max_concurrency_limits_provider_dispatch():
    async def exercise():
        service, client = build_service(max_concurrency=2)
        active_calls = 0
        max_active_calls = 0
        first_two_started = asyncio.Event()
        release_calls = asyncio.Event()

        async def controlled_invoke(_messages):
            nonlocal active_calls, max_active_calls
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            if active_calls == 2:
                first_two_started.set()
            await release_calls.wait()
            active_calls -= 1
            return topic_response()

        client.ainvoke.side_effect = controlled_invoke
        tasks = [
            asyncio.create_task(service.plan_topics(f"LangGraph {index}"))
            for index in range(4)
        ]
        await asyncio.wait_for(first_two_started.wait(), timeout=1)

        assert client.ainvoke.await_count == 2
        release_calls.set()
        results = await asyncio.gather(*tasks)

        assert all(len(topics) == 5 for topics in results)
        assert client.ainvoke.await_count == 4
        assert max_active_calls == 2

    run(exercise())


def test_queued_llm_operation_cannot_bypass_newly_open_circuit():
    async def exercise():
        breaker = CircuitBreaker(1, 30)
        provider_started = asyncio.Event()
        release_failure = asyncio.Event()
        second_operation_checked = asyncio.Event()
        check_count = 0
        original_check = breaker.check_available

        async def observed_check() -> int:
            nonlocal check_count
            admission_generation = await original_check()
            check_count += 1
            if check_count == 2:
                second_operation_checked.set()
            return admission_generation

        breaker.check_available = observed_check  # type: ignore[method-assign]
        service, client = build_service(
            max_attempts=1,
            max_concurrency=1,
            circuit_breaker=breaker,
        )

        async def controlled_invoke(_messages):
            provider_started.set()
            await release_failure.wait()
            raise TimeoutError("unit-test queued failure")

        client.ainvoke.side_effect = controlled_invoke
        first = asyncio.create_task(service.plan_topics("first"))
        await provider_started.wait()
        second = asyncio.create_task(service.plan_topics("second"))
        await second_operation_checked.wait()
        release_failure.set()
        first_result, second_result = await asyncio.gather(
            first,
            second,
            return_exceptions=True,
        )

        assert isinstance(first_result, LLMServiceError)
        assert first_result.category == "timeout"
        assert isinstance(second_result, LLMServiceError)
        assert second_result.category == "circuit_open"
        assert client.ainvoke.await_count == 1

    run(exercise())


def test_llm_retry_rechecks_circuit_before_second_dispatch():
    async def exercise():
        breaker = CircuitBreaker(1, 30)
        retry_started = asyncio.Event()
        release_retry = asyncio.Event()

        async def controlled_retry_sleep(_delay: float) -> None:
            retry_started.set()
            await release_retry.wait()

        retrying_service, retrying_client = build_service(
            TimeoutError("unit-test first attempt"),
            topic_response(),
            circuit_breaker=breaker,
            retry_sleep=controlled_retry_sleep,
        )
        failing_service, failing_client = build_service(
            TimeoutError("unit-test breaker opener"),
            circuit_breaker=breaker,
            max_attempts=1,
        )

        retrying_operation = asyncio.create_task(
            retrying_service.plan_topics("retrying operation")
        )
        await retry_started.wait()

        with pytest.raises(LLMServiceError) as opener_error:
            await failing_service.plan_topics("breaker opener")
        assert opener_error.value.category == "timeout"
        assert breaker.state == "open"

        release_retry.set()
        with pytest.raises(LLMServiceError) as retry_error:
            await retrying_operation

        assert retry_error.value.category == "circuit_open"
        assert retrying_client.ainvoke.await_count == 1
        assert failing_client.ainvoke.await_count == 1
        assert breaker.consecutive_failures == 1

    run(exercise())


def test_breaker_counts_final_operation_failure_once_and_fast_fails():
    breaker = CircuitBreaker(2, 30)
    service, client = build_service(
        TimeoutError("operation one attempt one"),
        TimeoutError("operation one attempt two"),
        TimeoutError("operation two attempt one"),
        TimeoutError("operation two attempt two"),
        circuit_breaker=breaker,
    )

    for _ in range(2):
        with pytest.raises(LLMServiceError, match="真实 LLM API 调用失败"):
            run(service.plan_topics("LangGraph"))

    assert client.ainvoke.await_count == 4
    assert breaker.consecutive_failures == 2
    assert breaker.state == "open"

    with pytest.raises(LLMServiceError) as exc_info:
        run(service.plan_topics("LangGraph"))
    assert exc_info.value.category == "circuit_open"
    assert client.ainvoke.await_count == 4


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


def test_llm_failure_logging_excludes_raw_exception_details(caplog):
    sensitive_detail = (
        "provider raw failure api_key=secret-value Bearer secret-jwt"
    )
    service, _ = build_service(
        StatusProviderError(500, sensitive_detail),
        max_attempts=1,
    )
    caplog.set_level("WARNING", logger="app.services.llm_service")

    with pytest.raises(LLMServiceError) as exc_info:
        run(service.plan_topics("sensitive topic"))

    formatted = "".join(
        traceback.format_exception(
            type(exc_info.value),
            exc_info.value,
            exc_info.value.__traceback__,
        )
    )
    assert sensitive_detail not in formatted
    assert sensitive_detail not in caplog.text
    assert "secret-value" not in caplog.text
    assert "secret-jwt" not in caplog.text
    assert "provider=llm" in caplog.text
    assert "category=server_error" in caplog.text
    assert "StatusProviderError" in caplog.text


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
