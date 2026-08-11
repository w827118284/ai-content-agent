from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CONTENT_AGENT_",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_name: str = "AI Content Operations Agent"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        validation_alias="CORS_ORIGINS",
    )
    checkpointer_backend: Literal["memory", "postgres"] = Field(
        default="memory",
        validation_alias="CHECKPOINTER_BACKEND",
    )
    database_url: SecretStr | None = Field(
        default=None,
        validation_alias="DATABASE_URL",
    )
    langgraph_strict_msgpack: bool = Field(
        default=True,
        validation_alias="LANGGRAPH_STRICT_MSGPACK",
    )
    jwt_secret_key: SecretStr = Field(validation_alias="JWT_SECRET_KEY")
    jwt_algorithm: Literal["HS256"] = Field(
        default="HS256",
        validation_alias="JWT_ALGORITHM",
    )
    jwt_access_token_expire_minutes: int = Field(
        default=60,
        ge=1,
        validation_alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    use_mock_llm: bool = Field(default=True, validation_alias="USE_MOCK_LLM")
    llm_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="LLM_API_KEY",
    )
    llm_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias="LLM_BASE_URL",
    )
    llm_model: str = Field(
        default="deepseek-v4-pro",
        validation_alias="LLM_MODEL",
    )
    use_mock_image: bool = Field(default=True, validation_alias="USE_MOCK_IMAGE")
    image_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="IMAGE_API_KEY",
    )
    image_base_url: str = Field(
        default="https://api.iotwq.top/v1",
        validation_alias="IMAGE_BASE_URL",
    )
    image_model: str = Field(
        default="gpt-image-2",
        validation_alias="IMAGE_MODEL",
    )
    image_size: str = Field(default="1280x1280", validation_alias="IMAGE_SIZE")
    image_quality: str = Field(default="auto", validation_alias="IMAGE_QUALITY")
    image_output_format: Literal["png", "jpeg", "webp"] = Field(
        default="png",
        validation_alias="IMAGE_OUTPUT_FORMAT",
    )
    image_moderation: str = Field(
        default="auto",
        validation_alias="IMAGE_MODERATION",
    )
    image_n: int = Field(default=1, ge=1, le=1, validation_alias="IMAGE_N")
    image_output_dir: str = Field(
        default="outputs/images",
        validation_alias="IMAGE_OUTPUT_DIR",
    )
    image_public_prefix: str = Field(
        default="/media/images",
        validation_alias="IMAGE_PUBLIC_PREFIX",
    )
    image_timeout_seconds: float = Field(
        default=300,
        ge=1,
        validation_alias="IMAGE_TIMEOUT_SECONDS",
    )
    image_max_concurrency: int = Field(
        default=3,
        ge=1,
        validation_alias="IMAGE_MAX_CONCURRENCY",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 bytes when UTF-8 encoded")
        return value

    @property
    def resolved_image_output_dir(self) -> Path:
        output_dir = Path(self.image_output_dir)
        if output_dir.is_absolute():
            return output_dir
        return Path(__file__).resolve().parents[2] / output_dir


settings = Settings()
