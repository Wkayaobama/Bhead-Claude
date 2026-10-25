"""Claude wiring — the single seam between this app and the model.

Every Claude call in the codebase goes through this module; nothing else
imports `anthropic`. That invariant is what makes swapping the model, adding
a gateway `base_url`, caching, or usage metering a one-file edit.

Auth: `ANTHROPIC_API_KEY` from `.env` (via `settings`) or the process
environment — or `ANTHROPIC_AUTH_TOKEN`, which the SDK reads itself — talking
directly to api.anthropic.com. `get_client()` raises `LLMNotConfigured` when
neither is present so the failure is a clear message at the first call, not a
connection error to a host that no longer exists.

Helpers:
  - chat_once           non-streaming chat → text
  - stream_chat         streaming chat → async iterator of text chunks
  - extract_structured  guaranteed-shape JSON via `output_config.format`

Response guards: `stop_reason == "refusal"` raises `LLMRefused` and
`stop_reason == "max_tokens"` raises `LLMTruncated`, so callers never
persist a partial or declined answer as if it were complete.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, AsyncIterator, Optional

from anthropic import AsyncAnthropic

from app.config import settings

# Beta flag for the scalar `fallbacks: "default"` form (refusal → Anthropic's
# category-routed fallback model). Pairing it with the array form is a 400.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """Base class for failures the routes can turn into user-facing errors."""


class LLMNotConfigured(LLMError):
    pass


class LLMRefused(LLMError):
    def __init__(self, category: Optional[str], explanation: Optional[str]):
        self.category = category
        self.explanation = explanation
        super().__init__(
            f"The model declined this request ({category or 'unspecified'})"
            + (f": {explanation}" if explanation else ".")
        )


class LLMTruncated(LLMError):
    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens
        super().__init__(
            f"The reply hit max_tokens={max_tokens} before finishing; "
            "raise EXTRACT_MAX_TOKENS / CHAT_MAX_TOKENS or send less input."
        )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_client: Optional[AsyncAnthropic] = None


def _api_key() -> str:
    return (settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()


def is_configured() -> bool:
    return bool(_api_key() or os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip())


def get_client() -> AsyncAnthropic:
    """Construct (once) the shared async client. The SDK pools connections and
    retries 429/5xx itself (max_retries=2), so one instance serves the app."""
    global _client
    if _client is None:
        if not is_configured():
            raise LLMNotConfigured(
                "No Anthropic credential: set ANTHROPIC_API_KEY (or "
                "ANTHROPIC_AUTH_TOKEN) in .env — see .env.example — and "
                "restart the backend."
            )
        # api_key=None hands auth to the SDK, which then reads
        # ANTHROPIC_AUTH_TOKEN — the only other credential is_configured accepts.
        _client = AsyncAnthropic(api_key=_api_key() or None)
    return _client


def reset_client() -> None:
    """Drop the cached client (tests, credential rotation)."""
    global _client
    _client = None


def describe() -> dict[str, Any]:
    """Non-secret summary for /api/health and the UI."""
    return {
        "provider": "anthropic",
        "model": settings.ai_model,
        "effort": settings.ai_effort or None,
        "refusal_fallback": settings.ai_refusal_fallback,
        "configured": is_configured(),
    }


def _api():
    """Return (messages resource, extra kwargs). The refusal fallback lives on
    the beta surface, so the choice is made once here, not at each call."""
    client = get_client()
    if settings.ai_refusal_fallback:
        return client.beta.messages, {"betas": [_FALLBACK_BETA], "fallbacks": "default"}
    return client.messages, {}


def _output_config(extra: Optional[dict] = None) -> dict:
    cfg: dict[str, Any] = dict(extra or {})
    if settings.ai_effort:
        cfg["effort"] = settings.ai_effort
    return cfg


def _raise_for_stop(resp: Any, max_tokens: int) -> None:
    if resp.stop_reason == "refusal":
        details = getattr(resp, "stop_details", None)
        raise LLMRefused(
            getattr(details, "category", None), getattr(details, "explanation", None)
        )
    if resp.stop_reason == "max_tokens":
        raise LLMTruncated(max_tokens)


def _text_of(resp: Any) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


# ---------------------------------------------------------------------------
# Non-streaming chat
# ---------------------------------------------------------------------------


async def chat_once(
    *,
    user_message: str,
    system_prompt: Optional[str] = None,
    history: Optional[list[dict]] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """Send one user message (+ optional prior turns), return the reply text.

    `history` is the list of prior turns: [{"role": "user"|"assistant",
    "content": "..."}].
    """
    api, extra = _api()
    limit = max_tokens or settings.chat_max_tokens
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})
    kwargs: dict[str, Any] = {
        "model": model or settings.ai_model,
        "max_tokens": limit,
        "messages": messages,
        **extra,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    cfg = _output_config()
    if cfg:
        kwargs["output_config"] = cfg
    resp = await api.create(**kwargs)
    _raise_for_stop(resp, limit)
    return _text_of(resp)


# ---------------------------------------------------------------------------
# Streaming chat — bridge to SSE in routes/documents.py
# ---------------------------------------------------------------------------


async def stream_chat(
    *,
    user_message: str,
    system_prompt: Optional[str] = None,
    history: Optional[list[dict]] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> AsyncIterator[str]:
    """Yield text chunks as the model generates them. Raises `LLMRefused` /
    `LLMTruncated` after the stream ends when the reply was not complete."""
    api, extra = _api()
    limit = max_tokens or settings.chat_max_tokens
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})
    kwargs: dict[str, Any] = {
        "model": model or settings.ai_model,
        "max_tokens": limit,
        "messages": messages,
        **extra,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    cfg = _output_config()
    if cfg:
        kwargs["output_config"] = cfg

    async with api.stream(**kwargs) as stream:
        async for text in stream.text_stream:
            yield text
        final = await stream.get_final_message()
    _raise_for_stop(final, limit)


# ---------------------------------------------------------------------------
# Structured JSON output
# ---------------------------------------------------------------------------


def _strict_schema(schema: dict) -> dict:
    """Deep-copy `schema` with `additionalProperties: false` on every object
    node that does not set it — the structured-output format requires it, and
    call sites should not have to remember."""
    out = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node.setdefault("additionalProperties", False)
            for key in ("properties", "$defs", "definitions"):
                if isinstance(node.get(key), dict):
                    for child in node[key].values():
                        walk(child)
            if "items" in node:
                walk(node["items"])
            for key in ("anyOf", "oneOf", "allOf"):
                if isinstance(node.get(key), list):
                    for child in node[key]:
                        walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(out)
    return out


async def extract_structured(
    *,
    user_message: str,
    schema: dict,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> dict:
    """Return a dict matching `schema`, produced under `output_config.format`.

    The API guarantees the first content block is text holding valid JSON for
    the schema, so there is no markdown stripping and no forced tool call
    (forced `tool_choice` is rejected by current models).
    """
    api, extra = _api()
    limit = max_tokens or settings.extract_max_tokens
    kwargs: dict[str, Any] = {
        "model": model or settings.ai_model,
        "max_tokens": limit,
        "messages": [{"role": "user", "content": user_message}],
        "output_config": _output_config(
            {"format": {"type": "json_schema", "schema": _strict_schema(schema)}}
        ),
        **extra,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    resp = await api.create(**kwargs)
    _raise_for_stop(resp, limit)
    text = _text_of(resp)
    if not text:
        raise LLMError("The model returned no text block for the structured output.")
    return json.loads(text)
