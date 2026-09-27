"""
codeguard/core/config.py
Application configuration loaded from environment variables.
"""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    github_token: str
    openai_api_key: str
    openai_model: str = "llama-3.1-8b-instant"
    openai_base_url: str = "https://api.groq.com/openai/v1"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
