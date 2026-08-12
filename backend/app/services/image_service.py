import asyncio
import base64
import binascii
import logging
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
from app.services.image_mock import MockImageService
from app.services.provider_guard import (
    CircuitBreaker,
    ProviderCircuitOpenError,
    ProviderFailureCategory,
    SlidingWindowRateLimiter,
    classify_provider_failure,
    is_breaker_failure,
)


logger = logging.getLogger(__name__)


class ImageServiceProtocol(Protocol):
    async def generate_image(self, visual_point: str) -> str: ...

    async def generate_images(self, visual_points: list[str]) -> list[str]: ...


class ImageServiceError(RuntimeError):
    """Raised when image generation fails without exposing provider data."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        category: ProviderFailureCategory | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.category = category


class ImageConfigurationError(ImageServiceError):
    """Raised when real image mode is missing required configuration."""


class ImageResponseError(ImageServiceError):
    """Raised when an image provider response has no usable image data."""


def build_image_prompt(visual_point: str) -> str:
    point = visual_point.strip()
    if not point:
        raise ValueError("视觉知识点不能为空")
    return (
        "为小红书技术内容创作一张 AI 编程知识卡片视觉概念图。\n"
        f"核心知识点：{point}\n"
        "采用竖版 3:4 构图，简洁、专业、现代，信息层级清晰，主视觉突出。"
        "用流程、节点、连线、代码符号或抽象技术元素表达核心概念，"
        "只保留一个简短主标题，避免大量复杂小字和整段文章排版。"
        "整套图片使用统一的技术教育视觉风格，不生成品牌 Logo，"
        "不以人物肖像为画面重点。"
    )


def _provider_error_metadata(exc: Exception) -> tuple[int | None, str | None]:
    status_code = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    error_code: str | None = None
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict) and error.get("code") is not None:
            error_code = str(error["code"])
    return status_code if isinstance(status_code, int) else None, error_code


def _response_data(response: Any) -> list[Any]:
    data = (
        response.get("data")
        if isinstance(response, dict)
        else getattr(response, "data", None)
    )
    if not isinstance(data, list) or not data:
        raise ImageResponseError(
            "真实图片 API 返回结果中没有图片数据",
            category="provider_error",
        )
    return data


def _item_field(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


class OpenAIImageService:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        model: str | None,
        size: str,
        quality: str,
        output_format: str,
        moderation: str,
        n: int,
        max_concurrency: int,
        output_dir: str | Path,
        public_prefix: str,
        timeout_seconds: float,
        client: Any | None = None,
        download_client: Any | None = None,
        requests_per_minute: int = 10,
        breaker_failure_threshold: int = 3,
        breaker_cooldown_seconds: float = 30,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        normalized_api_key = api_key.strip() if api_key else ""
        normalized_base_url = base_url.strip().rstrip("/") if base_url else ""
        normalized_model = model.strip() if model else ""
        normalized_size = size.strip()
        normalized_prefix = "/" + public_prefix.strip("/")
        if not normalized_api_key:
            raise ImageConfigurationError("真实图片模式缺少 IMAGE_API_KEY")
        if not normalized_base_url:
            raise ImageConfigurationError("真实图片模式缺少 IMAGE_BASE_URL")
        if not normalized_model:
            raise ImageConfigurationError("真实图片模式缺少 IMAGE_MODEL")
        if not normalized_size:
            raise ImageConfigurationError("真实图片模式缺少 IMAGE_SIZE")
        if n != 1:
            raise ImageConfigurationError("IMAGE_N 必须为 1")
        if max_concurrency < 1:
            raise ImageConfigurationError("IMAGE_MAX_CONCURRENCY 必须大于 0")
        if requests_per_minute < 1:
            raise ImageConfigurationError("IMAGE_REQUESTS_PER_MINUTE 必须大于 0")

        self.model = normalized_model
        self.size = normalized_size
        self.quality = quality.strip()
        self.output_format = output_format.strip().lower()
        self.moderation = moderation.strip()
        self.n = n
        self.max_concurrency = max_concurrency
        self.output_dir = Path(output_dir)
        self.public_prefix = normalized_prefix
        self.timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        self._client = client or AsyncOpenAI(
            api_key=normalized_api_key,
            base_url=normalized_base_url,
            max_retries=0,
            timeout=self.timeout,
        )
        self._download_client = download_client
        self._provider_semaphore = asyncio.Semaphore(max_concurrency)
        self._rate_limiter = rate_limiter or SlidingWindowRateLimiter(
            requests_per_minute
        )
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            breaker_failure_threshold,
            breaker_cooldown_seconds,
        )

    async def _download_image(self, url: str) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ImageResponseError(
                "真实图片 API 返回了无效图片 URL",
                category="provider_error",
            )
        try:
            if self._download_client is not None:
                response = await self._download_client.get(url)
            else:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    follow_redirects=True,
                ) as client:
                    response = await client.get(url)
            response.raise_for_status()
            content = bytes(response.content)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ImageResponseError(
                "真实图片 URL 下载失败",
                category=classify_provider_failure(exc),
            ) from None
        if not content:
            raise ImageResponseError(
                "真实图片 URL 返回了空内容",
                category="provider_error",
            )
        return content

    async def _extract_image_bytes(self, response: Any) -> bytes:
        data = _response_data(response)
        first = data[0]
        encoded = _item_field(first, "b64_json")
        url = _item_field(first, "url")
        has_b64 = isinstance(encoded, str) and bool(encoded.strip())
        has_url = isinstance(url, str) and bool(url.strip())
        logger.info(
            "Image API response received data_count=%s has_b64=%s has_url=%s",
            len(data),
            has_b64,
            has_url,
        )
        if has_b64:
            try:
                return base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                raise ImageResponseError(
                    "真实图片 API 返回了无效 base64 图片数据",
                    category="provider_error",
                ) from None
        if has_url:
            return await self._download_image(url.strip())
        raise ImageResponseError(
            "真实图片 API 返回结果中没有 b64_json 或 URL",
            category="provider_error",
        )

    def _persist_sync(self, content: bytes) -> str:
        if not content:
            raise ImageResponseError("不能持久化空图片")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid4().hex}.{self.output_format}"
        target = self.output_dir / filename
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(target)
        return f"{self.public_prefix}/{filename}"

    def _cleanup_batch_files_sync(self, public_urls: list[str]) -> None:
        output_root = self.output_dir.resolve()
        expected_prefix = f"{self.public_prefix}/"
        for public_url in public_urls:
            parsed = urlparse(public_url)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                continue
            if not parsed.path.startswith(expected_prefix):
                continue
            filename = parsed.path.removeprefix(expected_prefix)
            if (
                not filename
                or "/" in filename
                or "\\" in filename
                or Path(filename).name != filename
            ):
                continue
            target = (output_root / filename).resolve()
            if target.parent != output_root:
                continue
            try:
                target.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "Failed to remove uncommitted image file error_type=%s",
                    type(exc).__name__,
                )

    async def _cleanup_batch_files(self, public_urls: list[str]) -> None:
        if not public_urls:
            return
        try:
            await asyncio.to_thread(self._cleanup_batch_files_sync, public_urls)
        except Exception as exc:
            logger.warning(
                "Failed to clean uncommitted image batch error_type=%s",
                type(exc).__name__,
            )

    async def generate_image(self, visual_point: str) -> str:
        prompt = build_image_prompt(visual_point)
        try:
            admission_generation = (
                await self._circuit_breaker.check_available()
            )
        except ProviderCircuitOpenError:
            logger.warning(
                "provider_circuit_open provider=image operation=generate_image "
                "category=circuit_open breaker_state=%s",
                self._circuit_breaker.state,
            )
            raise ImageServiceError(
                "真实图片 API 暂时不可用",
                category="circuit_open",
            ) from None

        permit = None
        try:
            async with self._provider_semaphore:
                await self._rate_limiter.acquire()
                try:
                    permit = await self._circuit_breaker.before_call(
                        admission_generation
                    )
                except ProviderCircuitOpenError:
                    logger.warning(
                        "provider_circuit_open provider=image "
                        "operation=generate_image category=circuit_open "
                        "breaker_state=%s",
                        self._circuit_breaker.state,
                    )
                    raise ImageServiceError(
                        "真实图片 API 暂时不可用",
                        category="circuit_open",
                    ) from None

                logger.info(
                    "provider_call_started provider=image operation=generate_image"
                )
                try:
                    response = await self._client.images.generate(
                        model=self.model,
                        prompt=prompt,
                        size=self.size,
                        quality=self.quality,
                        output_format=self.output_format,
                        moderation=self.moderation,
                        n=self.n,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    category = classify_provider_failure(exc)
                    status_code, error_code = _provider_error_metadata(exc)
                    breaker_state = await self._circuit_breaker.record_failure(
                        permit,
                        eligible=is_breaker_failure(category),
                    )
                    logger.warning(
                        "provider_call_failed provider=image "
                        "operation=generate_image category=%s attempt=1 "
                        "max_attempts=1 breaker_state=%s error_type=%s",
                        category,
                        breaker_state,
                        type(exc).__name__,
                    )
                    raise ImageServiceError(
                        "真实图片 API 调用失败",
                        status_code=status_code,
                        error_code=error_code,
                        category=category,
                    ) from None

                try:
                    content = await self._extract_image_bytes(response)
                except asyncio.CancelledError:
                    raise
                except ImageResponseError as exc:
                    category = exc.category or "provider_error"
                    breaker_state = await self._circuit_breaker.record_failure(
                        permit,
                        eligible=is_breaker_failure(category),
                    )
                    logger.warning(
                        "provider_call_failed provider=image "
                        "operation=fetch_image category=%s attempt=1 "
                        "max_attempts=1 breaker_state=%s error_type=%s",
                        category,
                        breaker_state,
                        type(exc).__name__,
                    )
                    raise
                except Exception as exc:
                    category = classify_provider_failure(exc)
                    breaker_state = await self._circuit_breaker.record_failure(
                        permit,
                        eligible=is_breaker_failure(category),
                    )
                    logger.warning(
                        "provider_call_failed provider=image "
                        "operation=fetch_image category=%s attempt=1 "
                        "max_attempts=1 breaker_state=%s error_type=%s",
                        category,
                        breaker_state,
                        type(exc).__name__,
                    )
                    raise ImageResponseError(
                        "真实图片 API 返回结果处理失败",
                        category=category,
                    ) from None

                await self._circuit_breaker.record_success(permit)
        except asyncio.CancelledError:
            if permit is not None:
                await self._circuit_breaker.cancel_call(permit)
            raise

        try:
            public_url = await asyncio.to_thread(self._persist_sync, content)
        except ImageServiceError:
            raise
        except Exception:
            raise ImageServiceError("图片持久化失败") from None
        logger.info("Image persisted successfully")
        return public_url

    async def generate_images(self, visual_points: list[str]) -> list[str]:
        if not visual_points:
            return []

        semaphore = asyncio.Semaphore(self.max_concurrency)
        failure_detected = asyncio.Event()

        async def generate_limited(visual_point: str) -> str:
            async with semaphore:
                if failure_detected.is_set():
                    raise asyncio.CancelledError
                try:
                    return await self.generate_image(visual_point)
                except Exception:
                    failure_detected.set()
                    raise

        tasks = [
            asyncio.create_task(generate_limited(point)) for point in visual_points
        ]
        try:
            done, _ = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in done:
                if not task.cancelled() and task.exception() is not None:
                    raise task.exception()  # type: ignore[misc]
            return [task.result() for task in tasks]
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            successful_urls = [result for result in results if isinstance(result, str)]
            await self._cleanup_batch_files(successful_urls)
            raise


def get_image_service() -> ImageServiceProtocol:
    if settings.use_mock_image:
        return MockImageService()
    return OpenAIImageService(
        api_key=(
            settings.image_api_key.get_secret_value()
            if settings.image_api_key is not None
            else None
        ),
        base_url=settings.image_base_url,
        model=settings.image_model,
        size=settings.image_size,
        quality=settings.image_quality,
        output_format=settings.image_output_format,
        moderation=settings.image_moderation,
        n=settings.image_n,
        max_concurrency=settings.image_max_concurrency,
        output_dir=settings.resolved_image_output_dir,
        public_prefix=settings.image_public_prefix,
        timeout_seconds=settings.image_timeout_seconds,
        requests_per_minute=settings.image_requests_per_minute,
        breaker_failure_threshold=settings.provider_breaker_failure_threshold,
        breaker_cooldown_seconds=settings.provider_breaker_cooldown_seconds,
    )
