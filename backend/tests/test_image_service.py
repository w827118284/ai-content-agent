import asyncio
import base64
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.config import Settings, settings
from app.services.image_mock import MockImageService
from app.services.image_service import (
    ImageConfigurationError,
    ImageResponseError,
    ImageServiceError,
    OpenAIImageService,
    build_image_prompt,
    get_image_service,
)


def run(coroutine):
    return asyncio.run(coroutine)


def image_response(*, b64_json: str | None = None, url: str | None = None):
    return SimpleNamespace(data=[SimpleNamespace(b64_json=b64_json, url=url)])


def build_service(tmp_path, *, max_concurrency: int = 3, response=None):
    client = MagicMock()
    client.images.generate = AsyncMock(
        return_value=response
        or image_response(b64_json=base64.b64encode(b"test-image").decode())
    )
    download_client = MagicMock()
    download_client.get = AsyncMock()
    service = OpenAIImageService(
        api_key="unit-test-image-key",
        base_url="https://unit.invalid/v1",
        model="unit-test-image-model",
        size="1008x1344",
        quality="auto",
        output_format="png",
        moderation="auto",
        n=1,
        max_concurrency=max_concurrency,
        output_dir=tmp_path,
        public_prefix="/media/images",
        timeout_seconds=300,
        client=client,
        download_client=download_client,
    )
    return service, client, download_client


def test_image_settings_default_to_mock():
    configured = Settings(_env_file=None)

    assert configured.use_mock_image is True
    assert configured.image_api_key is None
    assert configured.image_base_url == "https://api.iotwq.top/v1"
    assert configured.image_model == "gpt-image-2"
    assert configured.image_size == "1008x1344"
    assert configured.resolved_image_output_dir.name == "images"
    assert configured.resolved_image_output_dir.parent.name == "outputs"
    assert configured.image_n == 1
    assert configured.image_max_concurrency == 3


def test_image_settings_read_real_mode_environment(monkeypatch):
    monkeypatch.setenv("USE_MOCK_IMAGE", "false")
    monkeypatch.setenv("IMAGE_API_KEY", "unit-test-image-key")
    monkeypatch.setenv("IMAGE_BASE_URL", "https://unit.invalid/v1")
    monkeypatch.setenv("IMAGE_MODEL", "unit-test-image-model")
    monkeypatch.setenv("IMAGE_SIZE", "1008x1344")
    monkeypatch.setenv("IMAGE_QUALITY", "auto")
    monkeypatch.setenv("IMAGE_OUTPUT_FORMAT", "webp")
    monkeypatch.setenv("IMAGE_MODERATION", "auto")
    monkeypatch.setenv("IMAGE_N", "1")
    monkeypatch.setenv("IMAGE_MAX_CONCURRENCY", "2")

    configured = Settings(_env_file=None)

    assert configured.use_mock_image is False
    assert configured.image_api_key is not None
    assert configured.image_api_key.get_secret_value() == "unit-test-image-key"
    assert configured.image_output_format == "webp"
    assert configured.image_max_concurrency == 2


def test_real_selector_requires_image_api_key(monkeypatch):
    monkeypatch.setattr(settings, "use_mock_image", False)
    monkeypatch.setattr(settings, "image_api_key", None)

    with pytest.raises(ImageConfigurationError, match="IMAGE_API_KEY"):
        get_image_service()


def test_selector_uses_mock_or_configured_openai_provider(monkeypatch):
    monkeypatch.setattr(settings, "use_mock_image", True)
    assert isinstance(get_image_service(), MockImageService)

    monkeypatch.setattr(settings, "use_mock_image", False)
    monkeypatch.setattr(settings, "image_api_key", SecretStr("unit-test-image-key"))
    monkeypatch.setattr(settings, "image_base_url", "https://unit.invalid/v1")
    monkeypatch.setattr(settings, "image_model", "unit-test-image-model")
    with patch("app.services.image_service.AsyncOpenAI") as openai:
        service = get_image_service()

    assert isinstance(service, OpenAIImageService)
    assert service.size == "1008x1344"
    assert openai.call_args.kwargs["max_retries"] == 0


def test_prompt_contains_visual_point_and_card_constraints():
    point = "LangGraph interrupt 与 Command(resume) 的恢复机制"

    prompt = build_image_prompt(point)

    assert point in prompt
    assert "知识卡片" in prompt
    assert "竖版 3:4" in prompt


def test_generate_image_decodes_b64_and_persists_public_url(tmp_path):
    content = b"binary-png-content"
    service, client, _ = build_service(
        tmp_path,
        response=image_response(b64_json=base64.b64encode(content).decode()),
    )

    result = run(service.generate_image("LangGraph 状态恢复"))

    assert result.startswith("/media/images/") and result.endswith(".png")
    assert (tmp_path / result.rsplit("/", 1)[1]).read_bytes() == content
    kwargs = client.images.generate.await_args.kwargs
    assert kwargs == {
        "model": "unit-test-image-model",
        "prompt": kwargs["prompt"],
        "size": "1008x1344",
        "quality": "auto",
        "output_format": "png",
        "moderation": "auto",
        "n": 1,
    }
    assert "watermark" not in kwargs
    assert "response_format" not in kwargs


def test_generate_image_downloads_url_and_persists_public_url(tmp_path):
    service, _, download_client = build_service(
        tmp_path,
        response=image_response(url="https://images.example.test/temporary.png"),
    )
    response = MagicMock(content=b"downloaded-image")
    response.raise_for_status.return_value = None
    download_client.get.return_value = response

    result = run(service.generate_image("临时 URL 转存"))

    assert result.startswith("/media/images/")
    assert (tmp_path / result.rsplit("/", 1)[1]).read_bytes() == b"downloaded-image"
    download_client.get.assert_awaited_once_with(
        "https://images.example.test/temporary.png"
    )


@pytest.mark.parametrize(
    "response",
    [SimpleNamespace(data=[]), image_response(), image_response(b64_json="not-base64")],
)
def test_generate_image_rejects_empty_or_invalid_response(tmp_path, response):
    service, _, _ = build_service(tmp_path, response=response)

    with pytest.raises(ImageResponseError):
        run(service.generate_image("视觉点"))


def test_generate_image_wraps_provider_errors_without_message_leak(tmp_path):
    service, client, _ = build_service(tmp_path)

    class ProviderError(RuntimeError):
        status_code = 429
        body = {"error": {"code": "RateLimitExceeded"}}

    client.images.generate.side_effect = ProviderError(
        "provider response api_key=sensitive-details"
    )

    with pytest.raises(ImageServiceError) as exc_info:
        run(service.generate_image("视觉点"))

    error = exc_info.value
    formatted = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    assert str(error) == "真实图片 API 调用失败"
    assert error.status_code == 429
    assert error.error_code == "RateLimitExceeded"
    assert "sensitive-details" not in formatted


def test_generate_image_timeout_is_terminal_and_sanitized(tmp_path):
    service, client, _ = build_service(tmp_path)
    client.images.generate.side_effect = TimeoutError("provider timed out with secret")

    with pytest.raises(ImageServiceError, match="真实图片 API 调用失败"):
        run(service.generate_image("视觉点"))


def test_generate_images_preserves_input_order(tmp_path):
    service, _, _ = build_service(tmp_path, max_concurrency=5)
    points = [f"视觉点 {index}" for index in range(5)]

    async def delayed_generate(point: str) -> str:
        index = points.index(point)
        await asyncio.sleep((len(points) - index) * 0.002)
        return f"/media/images/{index}.png"

    service.generate_image = delayed_generate  # type: ignore[method-assign]

    assert run(service.generate_images(points)) == [
        f"/media/images/{index}.png" for index in range(5)
    ]


def test_generate_images_keeps_files_after_successful_batch(tmp_path):
    service, _, _ = build_service(tmp_path, max_concurrency=2)

    urls = run(service.generate_images(["A", "B"]))

    assert len(urls) == 2
    assert all((tmp_path / url.rsplit("/", 1)[1]).is_file() for url in urls)


def test_generate_images_removes_successful_files_when_batch_fails(tmp_path):
    service, _, _ = build_service(tmp_path, max_concurrency=3)

    async def exercise():
        persisted: list[str] = []
        successful_files_ready = asyncio.Event()

        async def controlled_generate(point: str) -> str:
            if point == "C":
                await successful_files_ready.wait()
                raise ImageServiceError("controlled failure")
            target = tmp_path / f"{point.lower()}.png"
            target.write_bytes(point.encode())
            persisted.append(target.name)
            if len(persisted) == 2:
                successful_files_ready.set()
            return f"/media/images/{target.name}"

        service.generate_image = controlled_generate  # type: ignore[method-assign]
        with pytest.raises(ImageServiceError, match="controlled failure"):
            await service.generate_images(["A", "B", "C"])

        assert persisted == ["a.png", "b.png"]
        assert not (tmp_path / "a.png").exists()
        assert not (tmp_path / "b.png").exists()

    run(exercise())


def test_generate_images_removes_successful_files_when_batch_is_cancelled(tmp_path):
    service, _, _ = build_service(tmp_path, max_concurrency=1)

    async def exercise():
        second_started = asyncio.Event()
        hold_second = asyncio.Event()

        async def controlled_generate(point: str) -> str:
            if point == "A":
                target = tmp_path / "a.png"
                target.write_bytes(b"A")
                return "/media/images/a.png"
            second_started.set()
            await hold_second.wait()
            return "/media/images/b.png"

        service.generate_image = controlled_generate  # type: ignore[method-assign]
        batch = asyncio.create_task(service.generate_images(["A", "B"]))
        await second_started.wait()
        batch.cancel()
        with pytest.raises(asyncio.CancelledError):
            await batch

        assert not (tmp_path / "a.png").exists()

    run(exercise())


def test_generate_images_does_not_start_queued_calls_after_failure(tmp_path):
    service, _, _ = build_service(tmp_path, max_concurrency=2)

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
                return "/media/images/a.png"
            if point == "B":
                second_started.set()
                await fail_second.wait()
                raise ImageServiceError("controlled failure")
            return f"/media/images/{point.lower()}.png"

        service.generate_image = controlled_generate  # type: ignore[method-assign]
        batch = asyncio.create_task(service.generate_images(["A", "B", "C", "D", "E"]))

        await first_started.wait()
        await second_started.wait()
        fail_second.set()
        with pytest.raises(ImageServiceError, match="controlled failure"):
            await batch

        assert started == ["A", "B"]

    run(exercise())
