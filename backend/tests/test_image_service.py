import asyncio
import traceback
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.config import Settings, settings
from app.services.image_mock import MockImageService
from app.services.image_service import (
    SEEDREAM_2K_PORTRAIT_SIZE,
    ImageConfigurationError,
    ImageResponseError,
    ImageServiceError,
    SeedreamImageService,
    build_image_prompt,
    get_image_service,
)


def run(coroutine):
    return asyncio.run(coroutine)


def image_response(url: str = "https://images.example.test/generated.jpeg"):
    return SimpleNamespace(data=[SimpleNamespace(url=url)])


def build_service(*, max_concurrency: int = 3):
    client = MagicMock()
    client.images.generate.return_value = image_response()
    with patch("app.services.image_service.OpenAI", return_value=client) as openai:
        service = SeedreamImageService(
            api_key="unit-test-image-key",
            base_url="https://unit.invalid/api/v3",
            model="unit-test-seedream-model",
            size="2K",
            watermark=True,
            max_concurrency=max_concurrency,
        )
    return service, client, openai


def test_image_settings_default_to_mock():
    configured = Settings(_env_file=None)

    assert configured.use_mock_image is True
    assert configured.image_api_key is None
    assert configured.image_model == "doubao-seedream-5-0-260128"
    assert configured.image_size == "2K"
    assert configured.image_max_concurrency == 3


def test_image_settings_read_real_mode_environment(monkeypatch):
    monkeypatch.setenv("USE_MOCK_IMAGE", "false")
    monkeypatch.setenv("IMAGE_API_KEY", "unit-test-image-key")
    monkeypatch.setenv("IMAGE_BASE_URL", "https://unit.invalid/api/v3")
    monkeypatch.setenv("IMAGE_MODEL", "unit-test-seedream-model")
    monkeypatch.setenv("IMAGE_SIZE", "custom-size")
    monkeypatch.setenv("IMAGE_WATERMARK", "false")
    monkeypatch.setenv("IMAGE_MAX_CONCURRENCY", "2")

    configured = Settings(_env_file=None)

    assert configured.use_mock_image is False
    assert configured.image_api_key is not None
    assert configured.image_api_key.get_secret_value() == "unit-test-image-key"
    assert configured.image_base_url == "https://unit.invalid/api/v3"
    assert configured.image_model == "unit-test-seedream-model"
    assert configured.image_size == "custom-size"
    assert configured.image_watermark is False
    assert configured.image_max_concurrency == 2


def test_real_selector_requires_image_api_key(monkeypatch):
    monkeypatch.setattr(settings, "use_mock_image", False)
    monkeypatch.setattr(settings, "image_api_key", None)

    with pytest.raises(ImageConfigurationError, match="IMAGE_API_KEY"):
        get_image_service()


def test_selector_uses_mock_or_configured_seedream(monkeypatch):
    monkeypatch.setattr(settings, "use_mock_image", True)
    assert isinstance(get_image_service(), MockImageService)

    monkeypatch.setattr(settings, "use_mock_image", False)
    monkeypatch.setattr(settings, "image_api_key", SecretStr("unit-test-image-key"))
    monkeypatch.setattr(settings, "image_base_url", "https://unit.invalid/api/v3")
    monkeypatch.setattr(settings, "image_model", "unit-test-seedream-model")
    monkeypatch.setattr(settings, "image_size", "2K")
    monkeypatch.setattr(settings, "image_watermark", True)
    monkeypatch.setattr(settings, "image_max_concurrency", 2)
    with patch("app.services.image_service.OpenAI") as openai:
        service = get_image_service()

    assert isinstance(service, SeedreamImageService)
    assert service.size == SEEDREAM_2K_PORTRAIT_SIZE
    openai.assert_called_once_with(
        api_key="unit-test-image-key",
        base_url="https://unit.invalid/api/v3",
        max_retries=2,
    )


def test_prompt_contains_visual_point_and_card_constraints():
    point = "LangGraph interrupt 与 Command(resume) 的恢复机制"

    prompt = build_image_prompt(point)

    assert point in prompt
    assert "技术内容" in prompt
    assert "知识卡片" in prompt
    assert "竖版 3:4" in prompt
    assert "简洁" in prompt


def test_generate_image_sends_ark_parameters_and_extracts_url():
    service, client, _ = build_service()

    result = run(service.generate_image("LangGraph 状态恢复"))

    assert result == "https://images.example.test/generated.jpeg"
    kwargs = client.images.generate.call_args.kwargs
    assert kwargs["model"] == "unit-test-seedream-model"
    assert "LangGraph 状态恢复" in kwargs["prompt"]
    assert kwargs["size"] == SEEDREAM_2K_PORTRAIT_SIZE
    assert kwargs["response_format"] == "url"
    assert kwargs["extra_body"] == {
        "watermark": True,
        "sequential_image_generation": "disabled",
    }


@pytest.mark.parametrize(
    "response",
    [SimpleNamespace(data=[]), SimpleNamespace(data=[SimpleNamespace(url=None)])],
)
def test_generate_image_rejects_missing_url(response):
    service, client, _ = build_service()
    client.images.generate.return_value = response

    with pytest.raises(ImageResponseError, match="图片|URL"):
        run(service.generate_image("视觉点"))


def test_generate_image_wraps_provider_errors_without_message_leak():
    service, client, _ = build_service()
    sanitized_message = "真实图片 API 调用失败"

    class ProviderError(RuntimeError):
        status_code = 429
        body = {"error": {"code": "RateLimitExceeded"}}

    provider_error = ProviderError("provider response with sensitive details")
    client.images.generate.side_effect = provider_error

    with pytest.raises(ImageServiceError, match=sanitized_message) as exc_info:
        run(service.generate_image("视觉点"))

    error = exc_info.value
    formatted_exception = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    assert str(error) == sanitized_message
    assert error.status_code == 429
    assert error.error_code == "RateLimitExceeded"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "sensitive details" not in str(error)
    assert "sensitive details" not in formatted_exception


def test_generate_images_preserves_input_order():
    service, _, _ = build_service(max_concurrency=5)
    points = [f"视觉点 {index}" for index in range(5)]

    async def delayed_generate(point: str) -> str:
        index = points.index(point)
        await asyncio.sleep((len(points) - index) * 0.002)
        return f"https://images.example.test/{index}.jpeg"

    service.generate_image = delayed_generate  # type: ignore[method-assign]

    assert run(service.generate_images(points)) == [
        f"https://images.example.test/{index}.jpeg" for index in range(5)
    ]


def test_generate_images_respects_concurrency_limit():
    service, _, _ = build_service(max_concurrency=2)
    active = 0
    maximum_active = 0

    async def tracked_generate(point: str) -> str:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.005)
        active -= 1
        return f"https://images.example.test/{point}.jpeg"

    service.generate_image = tracked_generate  # type: ignore[method-assign]

    results = run(service.generate_images([str(index) for index in range(5)]))

    assert len(results) == 5
    assert maximum_active == 2


def test_generate_images_is_all_or_nothing():
    service, _, _ = build_service(max_concurrency=3)

    async def sometimes_fails(point: str) -> str:
        if point == "失败知识点":
            raise ImageServiceError("单图失败")
        return f"https://images.example.test/{point}.jpeg"

    service.generate_image = sometimes_fails  # type: ignore[method-assign]

    with pytest.raises(ImageServiceError, match="单图失败"):
        run(service.generate_images(["成功一", "失败知识点", "成功二"]))


def test_generate_images_does_not_start_queued_calls_after_failure():
    service, _, _ = build_service(max_concurrency=2)

    async def exercise():
        started: list[str] = []
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        fail_second = asyncio.Event()
        hold_first = asyncio.Event()

        async def controlled_generate(point: str) -> str:
            started.append(point)
            if point == "A":
                first_started.set()
                await hold_first.wait()
                return "https://images.example.test/a.jpeg"
            if point == "B":
                second_started.set()
                await fail_second.wait()
                raise ImageServiceError("controlled failure")
            return f"https://images.example.test/{point.lower()}.jpeg"

        service.generate_image = controlled_generate  # type: ignore[method-assign]
        batch = asyncio.create_task(
            service.generate_images(["A", "B", "C", "D", "E"])
        )

        await first_started.wait()
        await second_started.wait()
        assert started == ["A", "B"]

        fail_second.set()
        with pytest.raises(ImageServiceError, match="controlled failure"):
            await batch

        assert started == ["A", "B"]

    run(exercise())
