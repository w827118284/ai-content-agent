import json
from typing import Any, TypeVar

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import settings
from app.graph.state import TopicOption
from app.services.llm_mock import MockLLMService


TOPIC_SYSTEM_PROMPT = """你是 AI 编程教育公司的资深技术内容策划。
你的任务是策划准确、具体、有实践价值的中文技术选题。
避免营销话术、同义改写和不存在的技术，输出必须严格符合用户要求的 JSON 格式。"""

ARTICLE_SYSTEM_PROMPT = """你是资深 Python 与 AI Agent 技术作者。
请为有一定编程基础的读者撰写准确、可实践的中文 Markdown 技术文章。
文章应多写实现思路和代码实践，少写空泛背景，不虚构 API，不写营销软文。
只输出 Markdown 文章正文，不要用代码围栏包裹整篇文章。"""

VISUAL_SYSTEM_PROMPT = """你是技术内容视觉编辑。
请从文章中提炼可独立制作成知识卡片的核心知识点。
每个知识点要简洁、具体、有信息量，并严格输出用户要求的 JSON 格式。"""


class LLMServiceError(RuntimeError):
    """Raised when the real LLM cannot produce a usable business response."""


class LLMConfigurationError(LLMServiceError):
    """Raised when real LLM mode is missing required configuration."""


class LLMResponseError(LLMServiceError):
    """Raised when the LLM response is empty or has an invalid structure."""


class _TopicPlanResponse(BaseModel):
    topics: list[str] = Field(min_length=5, max_length=5)

    @field_validator("topics")
    @classmethod
    def validate_topics(cls, topics: list[str]) -> list[str]:
        cleaned = [topic.strip() for topic in topics]
        if any(not topic for topic in cleaned):
            raise ValueError("选题标题不能为空")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("五个选题标题不能重复")
        return cleaned


class _VisualPointsResponse(BaseModel):
    visual_points: list[str] = Field(min_length=3, max_length=5)

    @field_validator("visual_points")
    @classmethod
    def validate_visual_points(cls, points: list[str]) -> list[str]:
        cleaned = [point.strip() for point in points]
        if any(not point for point in cleaned):
            raise ValueError("视觉知识点不能为空")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("视觉知识点不能重复")
        return cleaned


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        text = content.strip()
    else:
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                text_parts.append(block["text"])
        text = "\n".join(text_parts).strip()

    if not text:
        raise LLMResponseError("真实 LLM 返回了空内容")
    return text


def _parse_json_response(
    text: str,
    response_model: type[ResponseModel],
) -> ResponseModel:
    object_start = text.find("{")
    if object_start < 0:
        raise LLMResponseError("真实 LLM 未返回 JSON 对象")

    try:
        payload, _ = json.JSONDecoder().raw_decode(text[object_start:])
        return response_model.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMResponseError("真实 LLM 返回的数据格式不符合要求") from exc


class LLMService:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        model: str | None,
        temperature: float,
    ) -> None:
        normalized_api_key = api_key.strip() if api_key else ""
        normalized_model = model.strip() if model else ""
        if not normalized_api_key:
            raise LLMConfigurationError("真实 LLM 模式缺少 LLM_API_KEY")
        if not normalized_model:
            raise LLMConfigurationError("真实 LLM 模式缺少 LLM_MODEL")

        client_options: dict[str, Any] = {
            "model": normalized_model,
            "api_key": normalized_api_key,
            "temperature": temperature,
            "max_retries": 2,
        }
        if base_url and base_url.strip():
            client_options["base_url"] = base_url.strip()

        self._client = ChatOpenAI(**client_options)

    async def _invoke(self, system_prompt: str, user_prompt: str) -> str:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        try:
            response = await self._client.ainvoke(messages)
        except Exception as exc:
            raise LLMServiceError("真实 LLM API 调用失败") from exc
        return _message_text(response)

    async def plan_topics(self, topic_direction: str) -> list[TopicOption]:
        user_prompt = (
            f"内容方向：{topic_direction.strip()}\n\n"
            "请为 AI 编程教育 / 技术内容账号生成恰好 5 个差异明显的技术选题。\n"
            "要求：具体、有实践感、技术含量明确，适合公众号长文和小红书知识内容。\n"
            "只返回 JSON 对象，不要添加解释或 Markdown。格式：\n"
            '{"topics": ["选题1", "选题2", "选题3", "选题4", "选题5"]}'
        )
        raw_response = await self._invoke(TOPIC_SYSTEM_PROMPT, user_prompt)
        parsed = _parse_json_response(raw_response, _TopicPlanResponse)
        return [
            {"id": f"topic_{index}", "title": title}
            for index, title in enumerate(parsed.topics, start=1)
        ]

    async def write_article(
        self,
        *,
        topic_direction: str,
        selected_topic: str,
        previous_article: str | None,
        feedback: str | None,
        revision_count: int,
    ) -> str:
        task_context = (
            f"内容方向：{topic_direction}\n"
            f"选题：{selected_topic}\n"
            f"当前重写次数：{revision_count}\n"
        )
        if previous_article is not None and feedback is not None:
            task_context += (
                "\n这是审核后的定向重写。必须保留原文主题和有效内容，并落实修改意见。\n"
                f"\n<previous_article>\n{previous_article}\n</previous_article>\n"
                f"\n<review_feedback>\n{feedback}\n</review_feedback>\n"
            )
        else:
            task_context += "\n这是首次生成，请以所选选题为核心撰写文章。\n"

        user_prompt = (
            f"{task_context}\n"
            "文章要求：\n"
            "- 使用中文 Markdown 和清晰标题层级\n"
            "- 面向有一定编程基础的读者\n"
            "- 重点讲技术实践，可以包含准确的代码示例\n"
            "- 减少空泛背景，不虚构不存在的 API\n"
            "- 不写成营销软文\n"
        )
        return await self._invoke(ARTICLE_SYSTEM_PROMPT, user_prompt)

    async def extract_visual_points(
        self,
        *,
        selected_topic: str,
        article_content: str,
    ) -> list[str]:
        user_prompt = (
            f"文章选题：{selected_topic}\n\n"
            f"<article>\n{article_content}\n</article>\n\n"
            "请提炼 3~5 个视觉知识点。每一点都应能独立成为一张知识卡片主题，"
            "简洁但包含明确技术信息。\n"
            "只返回 JSON 对象，不要添加解释或 Markdown。格式：\n"
            '{"visual_points": ["知识点1", "知识点2", "知识点3"]}'
        )
        raw_response = await self._invoke(VISUAL_SYSTEM_PROMPT, user_prompt)
        parsed = _parse_json_response(raw_response, _VisualPointsResponse)
        return parsed.visual_points


def get_llm_service() -> MockLLMService | LLMService:
    if settings.use_mock_llm:
        return MockLLMService()
    return LLMService(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
    )
