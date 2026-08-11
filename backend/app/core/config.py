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
    llm_api_key: str | None = Field(default=None, validation_alias="LLM_API_KEY")
    llm_base_url: str | None = Field(default=None, validation_alias="LLM_BASE_URL")
    llm_model: str | None = Field(default=None, validation_alias="LLM_MODEL")
    llm_temperature: float = Field(
        default=0.2,
        ge=0,
        le=2,
        validation_alias="LLM_TEMPERATURE",
    )
    use_mock_image: bool = Field(default=True, validation_alias="USE_MOCK_IMAGE")
    image_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="IMAGE_API_KEY",
    )
    image_base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/v3",
        validation_alias="IMAGE_BASE_URL",
    )
    image_model: str = Field(
        default="doubao-seedream-5-0-260128",
        validation_alias="IMAGE_MODEL",
    )
    image_size: str = Field(default="2K", validation_alias="IMAGE_SIZE")
    image_watermark: bool = Field(
        default=True,
        validation_alias="IMAGE_WATERMARK",
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


settings = Settings()
