"""Claude wiring — the single seam between this app and the LLM.

THE ONE RULE: every Claude call in this codebase goes through this
module. Routes import these helpers; nothing else imports `anthropic`.
Keep that invariant and swapping models, adding caching, inserting a
gateway, or metering usage is a one-file edit.

Auth: the SDK resolves credentials from the environment on its own —
set ANTHROPIC_API_KEY in `.env` and construct AsyncAnthropic() with no
arguments. To route through a self-hosted Anthropic-compatible gateway
instead, this is the only place a `base_url=` would ever be added.

Patterns covered:
  - chat_once          non-streaming chat
  - stream_chat        streaming chat (bridge to SSE in routes/chat.py)
  - chat_with_tools    manual tool-use loop (function calling)
  - extract_structured guaranteed-shape JSON via output_config.format
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from anthropic import AsyncAnthropic

from app.config import settings

# ---------------------------------------------------------------------------
# Single shared client. The SDK pools connections and retries 429/5xx
# internally (default max_retries=2), so one instance serves the app.
# ---------------------------------------------------------------------------

_client: Optional[AsyncAnthropic] = None


def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        # No args: the SDK reads ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN /
        # an `ant auth login` profile) from the environment.
        _client = AsyncAnthropic()
    return _client


# Adaptive thinking lets Claude decide when and how much to reason.
# Recommended default for Claude 4.6+ models; remove per-call if a
# route needs the absolute lowest latency.
_THINKING = {"type": "adaptive"}


# ---------------------------------------------------------------------------
# Non-streaming chat
# ---------------------------------------------------------------------------


async def chat_once(
    *,
    user_message: str,
    system_prompt: Optional[str] = None,
    history: Optional[list[dict]] = None,
    model: Optional[str] = None,
    max_tokens: int = 16000,
) -> str:
    """Send one user message (+ optional prior turns), return the reply text.

    `history` is a list of prior turns: [{"role": "user"|"assistant",
    "content": "..."}].
    """
    client = get_client()
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})

    kwargs: dict[str, Any] = {
        "model": model or settings.ai_model,
        "max_tokens": max_tokens,
        "thinking": _THINKING,
        "messages": messages,
    }
    if system_prompt:
        kwargs["system"] = system_prompt

    resp = await client.messages.create(**kwargs)
    return "".join(b.text for b in resp.content if b.type == "text")


# ---------------------------------------------------------------------------
# Streaming chat — yields text chunks as they are generated.
# See routes/chat.py for the SSE bridge to the browser.
# ---------------------------------------------------------------------------


async def stream_chat(
    *,
    user_message: str,
    system_prompt: Optional[str] = None,
    history: Optional[list[dict]] = None,
    model: Optional[str] = None,
    max_tokens: int = 64000,
) -> AsyncIterator[str]:
    client = get_client()
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})

    kwargs: dict[str, Any] = {
        "model": model or settings.ai_model,
        "max_tokens": max_tokens,
        "thinking": _THINKING,
        "messages": messages,
    }
    if system_prompt:
        kwargs["system"] = system_prompt

    async with client.messages.stream(**kwargs) as stream:
        async for text in stream.text_stream:
            yield text


# ---------------------------------------------------------------------------
# Tool use — manual loop so you can gate, log, or approve each call.
# ---------------------------------------------------------------------------


async def chat_with_tools(
    *,
    user_message: str,
    tools: list[dict],
    tool_handler: Callable[[str, dict], Awaitable[Any]],
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 16000,
    max_rounds: int = 5,
) -> str:
    """Run a tool-use loop until Claude answers in text.

    `tools` is a list of tool schemas:
        [{"name": "search_products",
          "description": "Search the product catalog",
          "input_schema": {"type": "object",
                           "properties": {"query": {"type": "string"}},
                           "required": ["query"]}}]

    `tool_handler(name, input) -> str | dict` executes each tool.
    """
    client = get_client()
    messages: list[dict] = [{"role": "user", "content": user_message}]

    for _ in range(max_rounds):
        kwargs: dict[str, Any] = {
            "model": model or settings.ai_model,
            "max_tokens": max_tokens,
            "thinking": _THINKING,
            "tools": tools,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        resp = await client.messages.create(**kwargs)
        # Echo the full assistant content (thinking + tool_use blocks
        # included) back into history — required for the loop to continue.
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")

        tool_results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            try:
                result = await tool_handler(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result if isinstance(result, str) else json.dumps(result),
                })
            except Exception as e:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {e}",
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results})

    return "Tool loop hit max rounds without completing."


# ---------------------------------------------------------------------------
# Structured JSON output — the API guarantees the shape.
# ---------------------------------------------------------------------------


async def extract_structured(
    *,
    user_message: str,
    schema: dict,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 16000,
) -> dict:
    """Return a dict matching `schema`, enforced by the API.

    Schema rules for structured outputs: every object needs
    `"additionalProperties": false`, and numeric/string min/max
    constraints are unsupported.

    Example:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "age"],
            "additionalProperties": False,
        }
    """
    client = get_client()

    kwargs: dict[str, Any] = {
        "model": model or settings.ai_model,
        "max_tokens": max_tokens,
        "thinking": _THINKING,
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
        "messages": [{"role": "user", "content": user_message}],
    }
    if system_prompt:
        kwargs["system"] = system_prompt

    resp = await client.messages.create(**kwargs)
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)
