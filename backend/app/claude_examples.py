"""Working examples for AI / chat features in this app.

This is the cookbook for LLM-powered features. Read it BEFORE wiring
up any LLM call — the patterns below are battle-tested and cover the
95% of needs a generated app has:

  - non-streaming chat
  - streaming chat (server-sent events to the browser)
  - vision (images in messages)
  - tool use (function calling)
  - structured JSON output via tool use
  - multi-turn conversations

Auth — two modes, picked automatically by `get_client()` from the env:

  1. **Studio-managed mode** (default — apps built inside Studio):
     `UT_API_KEY` + `UT_LLM_BASE_URL` are seeded in `.env`. The Anthropic
     SDK talks to Studio's Anthropic-compatible proxy, which validates
     the per-app key and forwards to Anthropic using a server-side
     master key. Cost is billed back to the project.

  2. **Standalone mode** (downloaded apps running outside Studio):
     The developer sets `ANTHROPIC_API_KEY` in `.env` and leaves
     `UT_LLM_BASE_URL` unset / empty. The SDK talks directly to
     `api.anthropic.com` and the developer pays Anthropic directly.

Mode selection: standalone is chosen iff `ANTHROPIC_API_KEY` is present
AND `UT_LLM_BASE_URL` is empty/unset. Otherwise Studio mode is chosen.
This means Studio-managed apps NEVER accidentally bypass the proxy.

ALWAYS construct the client via `get_client()` from this module.
Calling `AsyncAnthropic()` with no args may fall back to the SDK's own
env-var defaults, which won't match either mode's wiring. The helper
handles the dispatch correctly for both.

Model selection: `settings.ai_model` defaults to "claude-sonnet-4-6".
Override per-call if a specific request needs Opus for reasoning or
Haiku for high-volume simple tasks.
"""
from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator, Optional

from anthropic import AsyncAnthropic

from app.config import settings
from app.ut_usage import increment_prompt


# ---------------------------------------------------------------------------
# Whitelabel identity directive — silently prepended to every chat call's
# system prompt. Without this, end users asking the chatbot "who made you?"
# get the underlying foundation-model's default answer (e.g. "I'm Claude
# by Anthropic"), which leaks the stack. The helpers below always wrap
# the caller's `system_prompt` with `_with_identity(...)` so the directive
# wins regardless of what persona the app gives the assistant.
# ---------------------------------------------------------------------------

_IDENTITY_PRELUDE = (
    "If you are asked who you are, who made you, who created you, "
    "what model you are, what AI powers you, whether you are Claude / "
    "ChatGPT / GPT / Gemini, or any variation of these questions, "
    "answer ONLY with: \"I'm an AI assistant powered by Understand Tech.\" "
    "Do NOT mention Claude, Anthropic, OpenAI, GPT, Gemini, Meta, "
    "foundation models, model versions, or any other underlying "
    "technology. The technology that powers you is an internal "
    "implementation detail."
)


def _with_identity(system_prompt: Optional[str]) -> str:
    """Prepend the whitelabel identity directive to the caller's system
    prompt. The directive comes FIRST so it takes precedence over any
    persona the caller layered on top.
    """
    if system_prompt:
        return f"{_IDENTITY_PRELUDE}\n\n{system_prompt}"
    return _IDENTITY_PRELUDE


# ---------------------------------------------------------------------------
# Single shared client. The SDK handles connection pooling internally.
# ---------------------------------------------------------------------------

_client: Optional[AsyncAnthropic] = None


def get_client() -> AsyncAnthropic:
    """Construct (once) the AI client. Supports two modes — picked
    automatically from the env:

    1. **Studio-managed mode** (the default in apps built inside Studio):
       Reads `UT_API_KEY` + `UT_LLM_BASE_URL` and routes calls through
       Studio's Anthropic-compatible proxy. The proxy validates the
       per-app key, forwards to Anthropic using a server-side master
       key, and bills usage back to the project. Use this when running
       inside Studio.

    2. **Standalone mode** (when the app has been downloaded and is
       running outside Studio with the developer's own Anthropic key):
       Reads `ANTHROPIC_API_KEY` and talks directly to `api.anthropic.com`.
       No gateway, no UT involvement on the Claude rail. Use this when
       self-hosting.

    Mode selection rule: standalone mode is picked iff `ANTHROPIC_API_KEY`
    is set AND `UT_LLM_BASE_URL` is empty/unset. Otherwise Studio-managed
    mode is picked. This means a workspace seeded by Studio (which always
    sets `UT_LLM_BASE_URL`) keeps using the proxy even if someone
    accidentally also adds an `ANTHROPIC_API_KEY` — the proxy wins.

    Raises `RuntimeError` only if NEITHER mode's credentials are
    available, with a message explaining both options."""
    global _client
    if _client is None:
        # Pydantic-settings reads .env at import time; if the file wasn't
        # present then (uvicorn reload races, container restart) fall back
        # to os.environ, which reflects the live process environment.

        # Standalone mode detection: `ANTHROPIC_API_KEY` present AND
        # `UT_LLM_BASE_URL` empty/unset. `.strip()` handles the case
        # where someone sets `UT_LLM_BASE_URL=` (empty) or `=" "`
        # (whitespace) in their .env.
        ut_llm_base = (
            settings.ut_llm_base_url
            or os.environ.get("UT_LLM_BASE_URL", "")
        ).strip()
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if anthropic_key and not ut_llm_base:
            # Standalone: direct talk to api.anthropic.com. The SDK's
            # default base_url is the public Anthropic endpoint, so we
            # don't pass `base_url` at all.
            _client = AsyncAnthropic(api_key=anthropic_key)
            return _client

        # Studio-managed mode: route through the orchestrator's proxy.
        # Default `base_url` falls back to the host-bridge endpoint
        # Studio uses both in dev and prod.
        ut_key = (settings.ut_api_key or os.environ.get("UT_API_KEY", "")).strip()
        if not ut_key:
            raise RuntimeError(
                "No AI credentials configured. Either:\n"
                "  - Studio mode: set UT_API_KEY (and UT_LLM_BASE_URL — Studio "
                "    seeds both automatically at project-creation time), OR\n"
                "  - Standalone mode (downloaded app): set ANTHROPIC_API_KEY "
                "    and leave UT_LLM_BASE_URL empty/unset to talk directly "
                "    to api.anthropic.com."
            )
        base_url = ut_llm_base or "http://host.docker.internal:8001/api/llm/anthropic"
        # Explicit api_key + base_url — we do NOT rely on the SDK's
        # default env vars (ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL),
        # because those names would imply the user holds a raw
        # Anthropic key, which they don't in Studio mode.
        _client = AsyncAnthropic(api_key=ut_key, base_url=base_url)
    return _client


# ---------------------------------------------------------------------------
# Non-streaming chat — simplest possible call
# ---------------------------------------------------------------------------


async def chat_once(
    *,
    user_message: str,
    system_prompt: Optional[str] = None,
    history: Optional[list[dict]] = None,
    model: Optional[str] = None,
    max_tokens: int = 1024,
) -> str:
    """Send a single user message + optional history, get back the assistant's
    reply as plain text.

    `history` is the list of prior turns: [{"role": "user"|"assistant",
    "content": "..."}]. Pass it to keep context across turns.
    """
    client = get_client()
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})

    kwargs: dict[str, Any] = {
        "model": model or settings.ai_model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    kwargs["system"] = _with_identity(system_prompt)

    resp = await client.messages.create(**kwargs)
    await increment_prompt()
    # The SDK returns a list of content blocks; for plain text replies
    # there's just one TextBlock. Concatenate to be safe.
    return "".join(
        block.text for block in resp.content if block.type == "text"
    )


# ---------------------------------------------------------------------------
# Streaming chat — for live "tokens appear as they're generated" UX
# ---------------------------------------------------------------------------
#
# Usage from a FastAPI route:
#
#   from fastapi.responses import StreamingResponse
#
#   @router.post("/api/chat")
#   async def chat(req: ChatRequest):
#       async def gen():
#           async for chunk in stream_chat(
#               user_message=req.message,
#               history=req.history,
#               system_prompt="You are a helpful assistant.",
#           ):
#               # Forward each token as one SSE event to the browser
#               yield f'data: {json.dumps({"text": chunk})}\n\n'
#           yield 'data: {"done": true}\n\n'
#       return StreamingResponse(gen(), media_type="text/event-stream")


async def stream_chat(
    *,
    user_message: str,
    system_prompt: Optional[str] = None,
    history: Optional[list[dict]] = None,
    model: Optional[str] = None,
    max_tokens: int = 1024,
) -> AsyncIterator[str]:
    """Yield text chunks as Claude generates them.

    Each yielded value is a piece of the response (a few words to a
    sentence). Concatenate them on the frontend to render the full reply.
    """
    client = get_client()
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})

    kwargs: dict[str, Any] = {
        "model": model or settings.ai_model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    kwargs["system"] = _with_identity(system_prompt)

    async with client.messages.stream(**kwargs) as stream:
        async for text in stream.text_stream:
            yield text
    await increment_prompt()


# ---------------------------------------------------------------------------
# Vision — sending images to Claude
# ---------------------------------------------------------------------------
#
# Claude accepts images as content blocks in user messages. Two ways to
# pass an image:
#   - base64-encoded bytes (good for files uploaded via the app)
#   - a URL (good for images already hosted somewhere)


async def chat_with_image(
    *,
    user_message: str,
    image_base64: Optional[str] = None,
    image_url: Optional[str] = None,
    image_media_type: str = "image/jpeg",
    model: Optional[str] = None,
    max_tokens: int = 1024,
) -> str:
    """Send a message with an attached image. Returns the assistant's text."""
    client = get_client()

    if image_base64:
        image_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image_media_type,
                "data": image_base64,
            },
        }
    elif image_url:
        image_block = {
            "type": "image",
            "source": {"type": "url", "url": image_url},
        }
    else:
        raise ValueError("Provide either image_base64 or image_url")

    resp = await client.messages.create(
        model=model or settings.ai_model,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": [image_block, {"type": "text", "text": user_message}],
            }
        ],
    )
    await increment_prompt()
    return "".join(b.text for b in resp.content if b.type == "text")


# ---------------------------------------------------------------------------
# Tool use — let Claude call functions you define
# ---------------------------------------------------------------------------
#
# Define your tools as JSON schemas. When Claude decides to call one, the
# SDK returns `tool_use` blocks. You execute the tool, then send the
# result back as a `tool_result` block in the next message.
#
# Common pattern: a single round of tool use is enough for most apps
# (e.g., Claude calls `search_database`, you run it, you send results
# back, Claude composes the final reply).


async def chat_with_tools(
    *,
    user_message: str,
    tools: list[dict],
    tool_handler,  # async callable: name, input -> result
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 1024,
    max_rounds: int = 5,
) -> str:
    """Run a tool-using loop. Returns the final text reply.

    `tools` is a list of tool schemas like:
        [{
          "name": "search_products",
          "description": "Search the product catalog",
          "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
          }
        }]

    `tool_handler` is an async function `(name: str, input: dict) -> str|dict`
    that you implement to actually run each tool and return its result.
    """
    client = get_client()
    messages: list[dict] = [{"role": "user", "content": user_message}]

    for _ in range(max_rounds):
        kwargs: dict[str, Any] = {
            "model": model or settings.ai_model,
            "max_tokens": max_tokens,
            "tools": tools,
            "messages": messages,
        }
        kwargs["system"] = _with_identity(system_prompt)

        resp = await client.messages.create(**kwargs)
        await increment_prompt()

        # Append the assistant's full response to history.
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            # Done — Claude is replying with text, not calling tools.
            return "".join(b.text for b in resp.content if b.type == "text")

        # Resolve every tool_use block in the response.
        tool_results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            try:
                result = await tool_handler(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": (
                        result if isinstance(result, str)
                        else json.dumps(result)
                    ),
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
# Structured JSON output — guarantee a specific shape
# ---------------------------------------------------------------------------
#
# The cleanest way to get reliable JSON out of Claude is to use a tool
# definition as a schema. Claude will fill in the tool's input_schema
# fields and you get a parsed Python dict — no markdown stripping, no
# regex, no try/except json.loads.


async def extract_structured(
    *,
    user_message: str,
    schema: dict,
    schema_name: str = "extracted_data",
    schema_description: str = "Extracted structured data",
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 1024,
) -> dict:
    """Get a JSON dict matching `schema` from Claude.

    Example:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "interests": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["name", "age", "interests"]
        }
        result = await extract_structured(
            user_message="John is 32 and likes hiking and chess",
            schema=schema,
        )
        # result == {"name": "John", "age": 32, "interests": ["hiking", "chess"]}
    """
    client = get_client()
    tool = {
        "name": schema_name,
        "description": schema_description,
        "input_schema": schema,
    }

    kwargs: dict[str, Any] = {
        "model": model or settings.ai_model,
        "max_tokens": max_tokens,
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": schema_name},
        "messages": [{"role": "user", "content": user_message}],
    }
    kwargs["system"] = _with_identity(system_prompt)

    resp = await client.messages.create(**kwargs)
    await increment_prompt()

    for block in resp.content:
        if block.type == "tool_use" and block.name == schema_name:
            return block.input  # already a dict

    raise RuntimeError("Claude did not return structured output")


# ---------------------------------------------------------------------------
# Multi-turn conversations — the typical pattern
# ---------------------------------------------------------------------------
#
# Persist messages in your own store (Mongo) per conversation_id. Load
# the full thread, append the new user message, send to Claude, save
# Claude's reply.
#
#   thread = await db.conversations.find_one({"_id": conv_id})
#   history = thread["messages"]                              # list of {role, content}
#   reply = await chat_once(
#       user_message=user_input,
#       system_prompt=thread.get("system_prompt"),
#       history=history,
#   )
#   await db.conversations.update_one(
#       {"_id": conv_id},
#       {"$push": {"messages": {"$each": [
#           {"role": "user", "content": user_input},
#           {"role": "assistant", "content": reply},
#       ]}}},
#   )


# ---------------------------------------------------------------------------
# Error handling cheat-sheet
# ---------------------------------------------------------------------------
#
#   from anthropic import APIError, RateLimitError, AuthenticationError
#
#   - AuthenticationError (401) → bad/missing ANTHROPIC_API_KEY. Fail fast,
#     surface to the user — don't retry.
#   - RateLimitError (429) → backoff + retry once (e.g. 5s). The SDK has
#     automatic retries on by default; you usually don't need to handle
#     this manually unless you want custom UX.
#   - APIError (5xx) → upstream issue. Treat as bad-gateway and retry.
#   - APIConnectionError → network. Retry.
#
# The SDK's defaults (retries=2, timeout=600s) are sane for most apps.
