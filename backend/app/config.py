from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "app"

    # Mongo (each generated app has its own Mongo container).
    mongo_url: str = "mongodb://mongo:27017"
    mongo_db: str = "app"

    # AI runtime — handled by the Understand Tech LLM gateway. The
    # generated app does NOT hold a raw provider key; instead it
    # presents its per-app `UT_API_KEY` (already in .env) as a bearer
    # token against `ut_llm_base_url`. The Anthropic SDK uses these
    # to talk to Claude transparently — see `claude_examples.get_client()`.
    ut_api_key: str = ""
    ut_llm_base_url: str = "http://orchestrator:8001/api/llm/anthropic"
    # Default to the latest Sonnet — fast, capable, cheap for most apps.
    # Use "claude-opus-4-7" for hard reasoning, "claude-haiku-4-5" for
    # high-volume simple tasks. Just a model identifier — not a secret.
    ai_model: str = "claude-sonnet-4-6"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
