from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()
