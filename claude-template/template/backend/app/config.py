from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "__app_name__"

    # Default model for every helper in app/llm.py. Override per-call:
    # "claude-haiku-4-5" for high-volume simple tasks, "claude-sonnet-4-6"
    # for a speed/cost balance. Just an identifier — not a secret.
    # (ANTHROPIC_API_KEY is read directly by the SDK, not by Settings.)
    ai_model: str = "claude-opus-4-8"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
