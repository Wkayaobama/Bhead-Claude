"""Declarative configuration as a class.

Every tunable the app reads lives here as a typed field with a safe default.
Values come from the process environment first, then from `.env` files
resolved relative to this module — the repo-root `.env` (the one docker
compose also reads for `${VAR}` substitution) and then `backend/.env`, which
overrides it. Anchoring on `__file__` rather than the working directory means
`uvicorn` and `pytest` find the same file whichever directory they start in,
and never pick up an unrelated `.env` a level above. `extra="ignore"` keeps
unrelated keys in a shared `.env` from failing startup.

Adding a setting means three edits: a field here, a line in
`docker-compose.yml`'s explicit `environment:` allowlist (otherwise the
container silently runs on the default), and a row in `.env.example`.
"""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    project_name: str = "HR Scout"

    # --- storage -----------------------------------------------------------
    mongo_url: str = "mongodb://mongo:27017"
    mongo_db: str = "app"

    # --- AI (direct Anthropic API; see app/llm.py — the only module that
    # imports the SDK) ------------------------------------------------------
    # The key is read here so `.env` works for local uvicorn too; an empty
    # value makes `llm.get_client()` fail loudly instead of guessing.
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    # Effort steers reasoning depth on Claude 4.6+ models (low|medium|high|
    # xhigh|max). Leave empty to omit the parameter for a model that rejects it.
    ai_effort: str = "medium"
    # Server-side refusal fallback (beta): when the model's safety classifiers
    # decline a request, the API re-runs it on Anthropic's recommended
    # fallback model inside the same call instead of returning a refusal.
    ai_refusal_fallback: bool = True
    extract_max_tokens: int = Field(16000, ge=1)
    chat_max_tokens: int = Field(4096, ge=1)

    # --- scraping caps (characters of page text sent to the model) --------
    scrape_page_chars: int = Field(12_000, ge=1)
    apify_text_chars: int = Field(15_000, ge=1)
    # Optional server-side Apify token; a token in the request body wins.
    apify_api_key: str = ""

    # --- secrets vault ----------------------------------------------------
    # Passphrase the Fernet key is derived from. Empty disables the vault
    # routes (503) rather than encrypting with a guessable constant.
    secrets_encryption_key: str = ""

    # --- HTTP -------------------------------------------------------------
    # Comma-separated browser origins allowed to call the API cross-origin.
    # Empty installs no CORS middleware: the Vite dev server and any
    # production reverse proxy forward /api same-origin, so none is needed.
    cors_origins: str = ""

    # --- scheduler --------------------------------------------------------
    # ge=1: a zero tick would turn the scheduler into a hot loop.
    scheduler_tick_seconds: int = Field(60, ge=1)

    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ROOT / ".env"), str(_BACKEND_DIR / ".env")),
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
