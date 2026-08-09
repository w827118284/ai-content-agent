from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CONTENT_AGENT_",
        extra="ignore",
    )

    app_name: str = "AI Content Operations Agent"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"


settings = Settings()
