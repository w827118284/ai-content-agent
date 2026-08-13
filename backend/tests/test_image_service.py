import asyncio
import base64
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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
from app.services.provider_guard import CircuitBreaker


def run(coroutine):
    return asyncio.run(coroutine)


def image_response(*, b64_json: str | None = None, url: str | None = None):
    return SimpleNamespace(data=[SimpleNamespace(b64_json=b64_json, url=url)])


class StatusProviderError(RuntimeError):
    def __init__(self, status_code: int, message: str = "unit-test failure") -> None:
        super().__init__(message)
        self.status_code = status_code


def build_service(
    tmp_path,
    *,
    max_concurrency: int = 3,
    response=None,
    circuit_breaker=None,
    rate_limiter=None,
    host_resolver=None,
):
    client = MagicMock()
    client.images.generate = AsyncMock(
        return_value=response
        or image_response(b64_json=base64.b64encode(b"test-image").decode())
    )
    download_client = MagicMock()
    download_client.get = AsyncMock()
    if host_resolver is None:
        host_resolver = AsyncMock(return_value=("93.184.216.34",))
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
        circuit_breaker=circuit_breaker,
        rate_limiter=rate_limiter,
        host_resolver=host_resolver,
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
    assert configured.image_requests_per_minute == 10
    assert configured.provider_breaker_failure_threshold == 3
    assert configured.provider_breaker_cooldown_seconds == 30


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
    monkeypatch.setenv("IMAGE_REQUESTS_PER_MINUTE", "8")
    monkeypatch.setenv("PROVIDER_BREAKER_FAILURE_THRESHOLD", "4")
    monkeypatch.setenv("PROVIDER_BREAKER_COOLDOWN_SECONDS", "15")

    configured = Settings(_env_file=None)

    assert configured.use_mock_image is False
    assert configured.image_api_key is not None
    assert configured.image_api_key.get_secret_value() == "unit-test-image-key"
    assert configured.image_output_format == "webp"
    assert configured.image_max_concurrency == 2
    assert configured.image_requests_per_minute == 8
    assert configured.provider_breaker_failure_threshold == 4
    assert configured.provider_breaker_cooldown_seconds == 15


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
        "https://images.example.test/temporary.png",
        follow_redirects=False,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/image.png",
        "http://127.0.0.1/image.png",
        "http://10.0.0.8/image.png",
        "http://172.16.0.8/image.png",
        "http://192.168.0.8/image.png",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/image.png",
        "file:///tmp/image.png",
    ],
)
def test_temporary_url_rejects_local_and_private_targets_before_get(
    tmp_path,
    url,
):
    service, client, download_client = build_service(
        tmp_path,
        response=image_response(url=url),
    )

    with pytest.raises(ImageResponseError, match="图片 URL"):
        run(service.generate_image("blocked temporary URL"))

    assert client.images.generate.await_count == 1
    download_client.get.assert_not_awaited()


def test_temporary_url_rejects_hostname_resolving_to_private_address(tmp_path):
    host_resolver = AsyncMock(return_value=("10.0.0.8",))
    service, _, download_client = build_service(
        tmp_path,
        response=image_response(url="https://images.example.test/private.png"),
        host_resolver=host_resolver,
    )

    with pytest.raises(ImageResponseError, match="不安全图片 URL"):
        run(service.generate_image("private DNS target"))

    host_resolver.assert_awaited_once_with("images.example.test", 443)
    download_client.get.assert_not_awaited()


def test_temporary_url_revalidates_redirect_before_private_dispatch(tmp_path):
    initial_url = "https://images.example.test/temporary.png"
    request = httpx.Request("GET", initial_url)
    redirect = httpx.Response(
        302,
        headers={"Location": "http://169.254.169.254/latest/meta-data"},
        request=request,
    )
    service, _, download_client = build_service(
        tmp_path,
        response=image_response(url=initial_url),
    )
    download_client.get.return_value = redirect

    with pytest.raises(ImageResponseError, match="不安全图片 URL"):
        run(service.generate_image("private redirect target"))

    download_client.get.assert_awaited_once_with(
        initial_url,
        follow_redirects=False,
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
    assert error.category == "rate_limit"
    assert "sensitive-details" not in formatted
    assert client.images.generate.await_count == 1


@pytest.mark.parametrize(
    ("provider_error", "category"),
    [
        (TimeoutError("unit-test timeout"), "timeout"),
        (StatusProviderError(429), "rate_limit"),
        (StatusProviderError(500), "server_error"),
        (ConnectionError("unit-test connection"), "connection"),
    ],
)
def test_generate_image_provider_failures_never_retry(
    tmp_path,
    provider_error,
    category,
):
    limiter = MagicMock()
    limiter.acquire = AsyncMock()
    service, client, _ = build_service(tmp_path, rate_limiter=limiter)
    client.images.generate.side_effect = provider_error

    with pytest.raises(ImageServiceError, match="真实图片 API 调用失败") as exc_info:
        run(service.generate_image("视觉点"))

    assert exc_info.value.category == category
    assert client.images.generate.await_count == 1
    assert limiter.acquire.await_count == 1


def test_image_breaker_fast_fails_without_second_provider_call(tmp_path):
    breaker = CircuitBreaker(1, 30)
    service, client, _ = build_service(tmp_path, circuit_breaker=breaker)
    client.images.generate.side_effect = TimeoutError("unit-test timeout")

    with pytest.raises(ImageServiceError):
        run(service.generate_image("视觉点 A"))
    with pytest.raises(ImageServiceError) as exc_info:
        run(service.generate_image("视觉点 B"))

    assert breaker.state == "open"
    assert exc_info.value.category == "circuit_open"
    assert client.images.generate.await_count == 1


def test_queued_independent_image_call_cannot_bypass_newly_open_circuit(tmp_path):
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
        service, client, _ = build_service(
            tmp_path,
            max_concurrency=1,
            circuit_breaker=breaker,
        )

        async def controlled_generate(**_kwargs):
            provider_started.set()
            await release_failure.wait()
            raise TimeoutError("unit-test queued image failure")

        client.images.generate.side_effect = controlled_generate
        first = asyncio.create_task(service.generate_image("first"))
        await provider_started.wait()
        second = asyncio.create_task(service.generate_image("second"))
        await second_operation_checked.wait()
        release_failure.set()
        first_result, second_result = await asyncio.gather(
            first,
            second,
            return_exceptions=True,
        )

        assert isinstance(first_result, ImageServiceError)
        assert first_result.category == "timeout"
        assert isinstance(second_result, ImageServiceError)
        assert second_result.category == "circuit_open"
        assert client.images.generate.await_count == 1

    run(exercise())


def download_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://images.example.test/temporary.png")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        "unit-test download status failure",
        request=request,
        response=response,
    )


@pytest.mark.parametrize(
    ("download_error", "category"),
    [
        (TimeoutError("unit-test download timeout"), "timeout"),
        (ConnectionError("unit-test download connection"), "connection"),
        (download_status_error(429), "rate_limit"),
        (download_status_error(503), "server_error"),
    ],
)
def test_temporary_url_transient_failure_counts_for_breaker(
    tmp_path,
    download_error,
    category,
):
    breaker = CircuitBreaker(3, 30)
    service, client, download_client = build_service(
        tmp_path,
        response=image_response(
            url="https://images.example.test/temporary.png"
        ),
        circuit_breaker=breaker,
    )
    download_client.get.side_effect = download_error

    with pytest.raises(ImageResponseError) as exc_info:
        run(service.generate_image("temporary URL"))

    assert exc_info.value.category == category
    assert breaker.consecutive_failures == 1
    assert breaker.state == "closed"
    assert client.images.generate.await_count == 1
    assert download_client.get.await_count == 1


def test_temporary_url_failure_logging_excludes_raw_details(
    tmp_path,
    caplog,
):
    sensitive_detail = (
        "provider raw download failure api_key=secret-value "
        "Bearer secret-jwt"
    )
    service, _, download_client = build_service(
        tmp_path,
        response=image_response(
            url="https://images.example.test/temporary.png"
        ),
    )
    download_client.get.side_effect = TimeoutError(sensitive_detail)
    caplog.set_level("WARNING", logger="app.services.image_service")

    with pytest.raises(ImageResponseError) as exc_info:
        run(service.generate_image("sensitive temporary URL"))

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
    assert "images.example.test" not in caplog.text
    assert "category=timeout" in caplog.text


def test_temporary_url_failures_open_breaker_and_block_next_post(tmp_path):
    breaker = CircuitBreaker(2, 30)
    service, client, download_client = build_service(
        tmp_path,
        response=image_response(
            url="https://images.example.test/temporary.png"
        ),
        circuit_breaker=breaker,
    )
    download_client.get.side_effect = TimeoutError("unit-test download timeout")

    for _ in range(2):
        with pytest.raises(ImageResponseError):
            run(service.generate_image("temporary URL"))

    with pytest.raises(ImageServiceError) as exc_info:
        run(service.generate_image("blocked image"))

    assert breaker.state == "open"
    assert exc_info.value.category == "circuit_open"
    assert client.images.generate.await_count == 2
    assert download_client.get.await_count == 2


def test_successful_url_download_records_provider_success(tmp_path):
    breaker = CircuitBreaker(3, 30)
    prior_failure = run(breaker.before_call())
    run(breaker.record_failure(prior_failure, eligible=True))
    service, _, download_client = build_service(
        tmp_path,
        response=image_response(
            url="https://images.example.test/temporary.png"
        ),
        circuit_breaker=breaker,
    )
    response = MagicMock(content=b"downloaded-image")
    response.raise_for_status.return_value = None
    download_client.get.return_value = response

    result = run(service.generate_image("successful URL"))

    assert result.startswith("/media/images/")
    assert breaker.state == "closed"
    assert breaker.consecutive_failures == 0


def test_local_persist_failure_does_not_count_for_provider_breaker(tmp_path):
    breaker = CircuitBreaker(2, 30)
    service, client, _ = build_service(tmp_path, circuit_breaker=breaker)
    service._persist_sync = MagicMock(  # type: ignore[method-assign]
        side_effect=OSError("unit-test local disk failure")
    )

    with pytest.raises(ImageServiceError, match="图片持久化失败"):
        run(service.generate_image("local persist"))

    assert client.images.generate.await_count == 1
    assert breaker.state == "closed"
    assert breaker.consecutive_failures == 0


def test_image_max_concurrency_limits_provider_dispatch(tmp_path):
    async def exercise():
        service, client, _ = build_service(tmp_path, max_concurrency=2)
        active_calls = 0
        max_active_calls = 0
        first_two_started = asyncio.Event()
        release_calls = asyncio.Event()

        async def controlled_generate(**_kwargs):
            nonlocal active_calls, max_active_calls
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            if active_calls == 2:
                first_two_started.set()
            await release_calls.wait()
            active_calls -= 1
            return image_response(
                b64_json=base64.b64encode(b"test-image").decode()
            )

        client.images.generate.side_effect = controlled_generate
        tasks = [
            asyncio.create_task(service.generate_image(f"visual point {index}"))
            for index in range(4)
        ]
        await asyncio.wait_for(first_two_started.wait(), timeout=1)

        assert client.images.generate.await_count == 2
        release_calls.set()
        urls = await asyncio.gather(*tasks)

        assert len(urls) == 4
        assert client.images.generate.await_count == 4
        assert max_active_calls == 2

    run(exercise())


def test_image_failure_logging_excludes_raw_exception_details(
    tmp_path,
    caplog,
):
    sensitive_detail = (
        "provider raw failure api_key=secret-value Bearer secret-jwt"
    )
    service, client, _ = build_service(tmp_path)
    client.images.generate.side_effect = StatusProviderError(500, sensitive_detail)
    caplog.set_level("WARNING", logger="app.services.image_service")

    with pytest.raises(ImageServiceError) as exc_info:
        run(service.generate_image("sensitive visual prompt"))

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
    assert "sensitive visual prompt" not in caplog.text
    assert "provider=image" in caplog.text
    assert "category=server_error" in caplog.text
    assert "StatusProviderError" in caplog.text


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
