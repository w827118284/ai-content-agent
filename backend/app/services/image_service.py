import asyncio
from typing import Any, Protocol
from urllib.parse import urlparse

from openai import OpenAI

from app.core.config import settings
from app.services.image_mock import MockImageService


SEEDREAM_2K_PORTRAIT_SIZE = "1728x2304"


class ImageServiceProtocol(Protocol):
    async def generate_image(self, visual_point: str) -> str: ...

    async def generate_images(self, visual_points: list[str]) -> list[str]: ...


class ImageServiceError(RuntimeError):
    """Raised when an image provider call fails without exposing provider data."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class ImageConfigurationError(ImageServiceError):
    """Raised when real image mode is missing required configuration."""


class ImageResponseError(ImageServiceError):
    """Raised when the image provider response has no usable URL."""


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


def resolve_image_request_size(configured_size: str) -> str:
    size = configured_size.strip()
    if not size:
        raise ImageConfigurationError("真实图片模式缺少 IMAGE_SIZE")
    if size.upper() == "2K":
        return SEEDREAM_2K_PORTRAIT_SIZE
    return size


def _provider_error_metadata(exc: Exception) -> tuple[int | None, str | None]:
    status_code = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    error_code: str | None = None
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict) and error.get("code") is not None:
            error_code = str(error["code"])
    return status_code if isinstance(status_code, int) else None, error_code


def _extract_image_url(response: Any) -> str:
    data = getattr(response, "data", None)
    if not data:
        raise ImageResponseError("真实图片 API 返回结果中没有图片")

    first = data[0]
    url = first.get("url") if isinstance(first, dict) else getattr(first, "url", None)
    if not isinstance(url, str) or not url.strip():
        raise ImageResponseError("真实图片 API 返回结果中没有图片 URL")

    normalized_url = url.strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ImageResponseError("真实图片 API 返回了无效图片 URL")
    return normalized_url


class SeedreamImageService:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        model: str | None,
        size: str,
        watermark: bool,
        max_concurrency: int,
    ) -> None:
        normalized_api_key = api_key.strip() if api_key else ""
        normalized_base_url = base_url.strip().rstrip("/") if base_url else ""
        normalized_model = model.strip() if model else ""
        if not normalized_api_key:
            raise ImageConfigurationError("真实图片模式缺少 IMAGE_API_KEY")
        if not normalized_base_url:
            raise ImageConfigurationError("真实图片模式缺少 IMAGE_BASE_URL")
        if not normalized_model:
            raise ImageConfigurationError("真实图片模式缺少 IMAGE_MODEL")
        if max_concurrency < 1:
            raise ImageConfigurationError("IMAGE_MAX_CONCURRENCY 必须大于 0")

        self.model = normalized_model
        self.size = resolve_image_request_size(size)
        self.watermark = watermark
        self.max_concurrency = max_concurrency
        self._client = OpenAI(
            api_key=normalized_api_key,
            base_url=normalized_base_url,
            max_retries=2,
        )

    def _generate_sync(self, prompt: str) -> Any:
        return self._client.images.generate(
            model=self.model,
            prompt=prompt,
            size=self.size,
            response_format="url",
            extra_body={
                "watermark": self.watermark,
                "sequential_image_generation": "disabled",
            },
        )

    async def generate_image(self, visual_point: str) -> str:
        prompt = build_image_prompt(visual_point)
        try:
            response = await asyncio.to_thread(self._generate_sync, prompt)
        except ImageServiceError:
            raise
        except Exception as exc:
            status_code, error_code = _provider_error_metadata(exc)
            sanitized_error = ImageServiceError(
                "真实图片 API 调用失败",
                status_code=status_code,
                error_code=error_code,
            )
        else:
            return _extract_image_url(response)
        raise sanitized_error from None

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
                if task.cancelled():
                    continue
                error = task.exception()
                if error is not None:
                    raise error
            return [task.result() for task in tasks]
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise


def get_image_service() -> ImageServiceProtocol:
    if settings.use_mock_image:
        return MockImageService()
    return SeedreamImageService(
        api_key=(
            settings.image_api_key.get_secret_value()
            if settings.image_api_key is not None
            else None
        ),
        base_url=settings.image_base_url,
        model=settings.image_model,
        size=settings.image_size,
        watermark=settings.image_watermark,
        max_concurrency=settings.image_max_concurrency,
    )
