"""Understand Tech API v3 client — runtime, api-key auth.

The App Builder picks UT resources at project-creation time (assistants,
workflows, knowledge bases) and bakes their IDs into the generated app
via the system prompt. This module is what that generated code calls
at runtime to actually use those resources: chat with an assistant,
execute a shared workflow, fetch assistant metadata.

Configuration (set by the orchestrator at project-creation time, do
not edit by hand):
    UT_API_KEY        per-app bearer token, scoped to this app
    UNDERSTAND_API_URL  base host (e.g. `https://developer.understand.tech`)

This module appends `/api/v3` to the base URL. All endpoints require
`Authorization: Bearer ${UT_API_KEY}` and `accept-language`.

Streaming chat is exposed as an async generator yielding parsed SSE
events. Workflows are async on the UT side: `run_workflow` enqueues a
job and returns a `WorkflowRun` handle; call `.wait()` (or poll
`.status()`) to retrieve the result.

You usually want:
    from app.ut_api_v3 import chat, stream_chat, run_workflow

The chat helpers in `claude_examples.py` cover *foundation-model*
chat (Anthropic SDK via App Builder's proxy). Use the helpers below
when the user picked a specific UT assistant / workflow for the app
to wire around — those are the user's curated resources, not raw
LLMs.

MODEL VOCABULARY — three DIFFERENT things callable through `chat()`:

1. **"Understand AI"** — UT's own secure LLM, runs inside UT servers
   (sovereign / air-gap-friendly). Model NAME string is exactly
   `"Understand AI"` (preserve the space). The `secret` parameter is
   MANDATORY:
       - encryption ENABLED  → pass user's secret (orchestrator wrote
         it to `.env` as `UT_ENCRYPTION_SECRET`; read via
         `os.environ.get("UT_ENCRYPTION_SECRET", "")`).
       - encryption DISABLED → pass `secret=""` (the empty string).
         Omitting the field 400s.

2. **A UT ASSISTANT** — user-configured assistant with an opaque id
   (e.g. `x0eKhjaJWIW5IcQHkoP5`). Prefer `chat_with_assistant(id, ...)`
   which resolves model_name + secret for you. Do NOT pass the
   assistant id as `model=` to `chat()` directly.

3. **A THIRD-PARTY MODEL FROM THE UT CATALOG** — public LLMs UT
   routes for you. Pass the EXACT display name as `model=`. No
   `secret` needed (omit the field). Known catalog at this writing:
       "GPT-4.1"            (OpenAI — flagship, supports web search)
       "Claude Sonnet 4.6"  (Anthropic — balanced reasoning)
       "Mistral Medium"     (Mistral — mid-tier)
       "Gemini 3 Flash"     (Google — fast multimodal)
       "DeepSeek V3"        (DeepSeek — open-weight)
       "xAI Grok 4.1 Fast"  (xAI — fast-tier)
   Capitalisation and spaces are part of the name — substitute
   nothing.

These three are NOT interchangeable. If a user says "Understand AI",
they almost certainly mean (1), the secure LLM — never silently
substitute an assistant id or a catalog model.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import AsyncIterator, Optional

import httpx

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _base_url() -> str:
    """Return the v3 endpoint base, e.g.
    `https://ut-api-custom-alb.staging.understand.tech/api/v3`."""
    host = os.environ.get(
        "UNDERSTAND_API_URL", "https://developer.understand.tech"
    ).rstrip("/")
    # Idempotent: if the user already wrote the v3 path into the env,
    # don't double-append.
    if host.endswith("/api/v3"):
        return host
    return f"{host}/api/v3"


def _api_key() -> str:
    key = os.environ.get("UT_API_KEY", "")
    if not key:
        raise UtApiV3Error(
            "UT_API_KEY is not set — the App Builder orchestrator mints "
            "this at project-creation time, check `.env`"
        )
    return key


def _headers(language: str = "en-US") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "accept-language": language,
    }


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class UtApiV3Error(Exception):
    """Anything wrong with a UT v3 call. Carries the upstream status
    code and (truncated) response body when available."""

    def __init__(self, message: str, *, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


class WorkflowNotShared(UtApiV3Error):
    """Raised by `run_workflow` when the workflow has no `public_token`
    (i.e. the owner hasn't enabled public sharing on it). The UT v3
    public-execution endpoint requires this token; without it the
    workflow simply can't be run by an external API caller. Surface
    this to your end user — they need to ask the workflow's owner to
    share it."""


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


async def chat(
    model: str,
    prompt: str,
    *,
    history: list[dict] | None = None,
    language: str = "en-US",
    session_id: str | None = None,
    enable_thinking: bool = False,
    enable_web_search: bool = False,
    file_ids: list[str] | None = None,
    secret: str | None = None,
) -> dict:
    """Synchronous chat with a UT assistant.

    Args:
        model:    the assistant's `model_name` (string). The App Builder
                  passes you the exact name in the system prompt — use
                  that verbatim. UT's `/chat` takes a list, but for one
                  assistant pass a single name; we wrap it for you.
        prompt:   the user's message.
        history:  optional list of prior turns. Format depends on UT's
                  `HistorySchema` — typically `[{"model": ..., "messages": [...]}]`.
                  Pass the value you received from a previous call.
        session_id: pass the `session_id` returned by a previous chat
                  to continue the same conversation server-side.
        enable_thinking:   ask the assistant to surface intermediate
                  reasoning (model-dependent).
        enable_web_search: let the assistant search the web.
        file_ids: previously-uploaded file ids (see `/chat/files/upload`).
        secret:   enterprise-encrypted assistants require this.

    Works with ANY model the UT gateway exposes — Claude, GPT, Gemini,
    Mistral, the user's curated assistants, etc. The gateway handles
    provider-specific wire formats; this function only cares about
    the UT request/response envelope.

    Returns the parsed JSON body. The customer-mode response shape is
    `ChatResponseSchemaCustomer`:
        {
          "reponses": [
              {"doc_id": ..., "model": ..., "response": "<text>",
               "source_documents": [...]},
              ...
          ],
          "session_id": "..."
        }
    Note the field name `reponses` (single 'p') — that's the actual
    spelling in UT's `ChatResponseSchemaCustomer`. Use
    `extract_chat_text(result)` below to pull the assistant text
    out portably; don't hard-code the key.
    """
    body = _build_chat_body(
        model=model,
        prompt=prompt,
        history=history,
        language=language,
        session_id=session_id,
        enable_thinking=enable_thinking,
        enable_web_search=enable_web_search,
        file_ids=file_ids,
        secret=secret,
    )
    url = f"{_base_url()}/chat"
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(url, headers=_headers(language), json=body)
    if r.status_code >= 400:
        raise UtApiV3Error(
            f"chat failed ({r.status_code})", status=r.status_code, body=r.text[:500]
        )
    return r.json()


def extract_chat_text(result: dict) -> str:
    """Pull the assistant text out of a `chat()` response.

    UT's response shape carries TWO related misspellings — both
    defended here so this helper keeps working in either world:

      Outer container key:
        - actual:   `reponses`  (single 'p')
        - if-fixed: `responses`

      Per-item text key:
        - actual:   `reponse`   (NO trailing 's')
        - if-fixed: `response`
        - alt:      `text`      (alternate field name observed)

    History: the inner-key fallback ('response' only) caused empty
    chat replies because the actual key is 'reponse'. If you find a
    new spelling, add it here — never read the keys directly from
    user code.

    When the assistant fans out to multiple models, returns the first
    response's text. Wrap chat() yourself if you want all of them.

    Also logs a warning if the bucket has items but every text field
    came back empty — that's the canary for a future shape change.
    """
    if not isinstance(result, dict):
        return ""
    bucket = result.get("reponses") or result.get("responses") or []
    if not isinstance(bucket, list) or not bucket:
        return ""
    first = bucket[0] if isinstance(bucket[0], dict) else {}
    text = (
        first.get("reponse")    # actual misspelling in current spec
        or first.get("response")  # in case the spec gets fixed
        or first.get("text")      # alternate field name observed
        or ""
    )
    if not text:
        # Don't silently return empty — log the keys we saw so the next
        # spec drift is one log read away instead of an investigation.
        log.warning(
            "ut_api_v3: extract_chat_text got empty text. "
            "First-item keys: %s. Sample (truncated): %r",
            sorted(first.keys()) if isinstance(first, dict) else type(first).__name__,
            str(first)[:300],
        )
    return str(text) if text else ""


async def chat_text_stream(
    model: str,
    prompt: str,
    *,
    history: list[dict] | None = None,
    language: str = "en-US",
    session_id: str | None = None,
    enable_thinking: bool = False,
    enable_web_search: bool = False,
    file_ids: list[str] | None = None,
    secret: str | None = None,
    word_delay_ms: int = 30,
) -> AsyncIterator[str]:
    """Recommended way to render a chat response progressively.

    Yields the assistant's text in word-sized chunks suitable for a
    typewriter-style UI (forward each chunk to your frontend over SSE
    / WebSocket / similar). Behind the scenes this calls the
    non-streaming `chat()` endpoint and chunks the response client-
    side — the user perceives streaming, you get a guaranteed
    response shape that works for every model the UT gateway
    exposes (Claude, GPT, Gemini, Mistral, the user's curated
    assistants, …) without having to parse provider-specific SSE.

    Why not parse UT's real SSE? UT's chat is multi-provider; each
    provider's wire format differs (`choices[0].delta.content` for
    OpenAI-shape, but Claude / Gemini / Mistral are not the same).
    Until UT normalizes the SSE event shape, server-side word
    chunking is the only approach that works for every model.

    Args mirror `chat()`. `word_delay_ms` controls the cadence —
    30 ms per word feels lively; 0 to disable the artificial delay.

    Yields:
        Text fragments. Concatenating every yielded value gives the
        full assistant response. The first fragment has no leading
        space; subsequent fragments start with " " so concatenation
        produces well-spaced output without manual joining.
    """
    result = await chat(
        model=model,
        prompt=prompt,
        history=history,
        language=language,
        session_id=session_id,
        enable_thinking=enable_thinking,
        enable_web_search=enable_web_search,
        file_ids=file_ids,
        secret=secret,
    )
    text = extract_chat_text(result)
    if not text:
        return
    parts = text.split(" ")
    sleep_s = max(word_delay_ms, 0) / 1000.0
    for i, part in enumerate(parts):
        if not part:
            continue
        yield part if i == 0 else " " + part
        if sleep_s:
            await asyncio.sleep(sleep_s)


async def stream_chat(
    model: str,
    prompt: str,
    *,
    history: list[dict] | None = None,
    language: str = "en-US",
    session_id: str | None = None,
    enable_thinking: bool = False,
    enable_web_search: bool = False,
    file_ids: list[str] | None = None,
    secret: str | None = None,
) -> AsyncIterator[dict]:
    """Raw SSE chat — yields whatever events UT sends, parsed as dicts.

    **Prefer `chat_text_stream(...)` for normal UI work.** This is an
    escape hatch for code that needs the raw event stream (e.g. to
    capture `conversation_id`, `doc_id`, `sources_final`, RAG context
    chunks, or model-specific delta fields).

    UT's SSE event shape is provider-dependent: an OpenAI-backed
    model sends `{"choices":[{"delta":{"content": "..."}}]}` style
    events, but Claude/Gemini/Mistral payloads may use entirely
    different keys. There is no portable "text" field across
    providers — if you yield raw events and an inner extractor only
    knows one shape, it silently produces no output. That was the
    bug that prompted this rewrite. Either restrict yourself to a
    single known provider and parse accordingly, or use
    `chat_text_stream`.

    Same args as `chat()`.
    """
    body = _build_chat_body(
        model=model,
        prompt=prompt,
        history=history,
        language=language,
        session_id=session_id,
        enable_thinking=enable_thinking,
        enable_web_search=enable_web_search,
        file_ids=file_ids,
        secret=secret,
    )
    url = f"{_base_url()}/chat/stream/sse"
    timeout = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", url, headers=_headers(language), json=body,
        ) as resp:
            if resp.status_code >= 400:
                text = (await resp.aread()).decode(errors="replace")
                raise UtApiV3Error(
                    f"stream_chat failed ({resp.status_code})",
                    status=resp.status_code,
                    body=text[:500],
                )
            # Parse SSE — UT may emit either `data: <json>` framed events
            # (standard SSE) or one JSON-per-line. Handle both.
            async for raw in resp.aiter_lines():
                if not raw:
                    continue
                line = raw.lstrip()
                if line.startswith("data:"):
                    line = line[len("data:"):].lstrip()
                if not line or line == "[DONE]":
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # Forward non-JSON lines as text wrapped in a marker
                    # the caller can still detect; don't drop them silently.
                    yield {"_raw": line}


def _build_chat_body(
    *,
    model: str,
    prompt: str,
    history: list[dict] | None,
    language: str,
    session_id: str | None,
    enable_thinking: bool,
    enable_web_search: bool,
    file_ids: list[str] | None,
    secret: str | None,
) -> dict:
    """Assemble a `ChatRequestSchema` body. `selected_models` is the
    canonical field UT uses; passing one name still wraps it in a list."""
    payload: dict = {
        "selected_models": [model],
        "prompt": prompt,
        "language_pref": language,
        "enable_thinking": bool(enable_thinking),
        "enable_web_search": bool(enable_web_search),
    }
    if history:
        payload["history"] = history
    if session_id:
        payload["session_id"] = session_id
    if file_ids:
        payload["file_ids"] = file_ids
    # The "Understand AI" model REQUIRES the `secret` field to be present
    # in the payload, even as an empty string when the user does NOT have
    # encryption activated. Older code did `if secret:` which dropped the
    # field on empty — fine for assistants that ignore it, broken for
    # Understand AI. `is not None` keeps the back-compat behaviour for
    # callers that pass `secret=None` (the default) while letting
    # callers explicitly send `secret=""` to opt into "present-but-empty".
    if secret is not None:
        payload["secret"] = secret
    return payload


# ---------------------------------------------------------------------------
# Assistant detail
# ---------------------------------------------------------------------------


async def get_assistant(model_id: str, *, secret: str | None = None) -> dict:
    """Fetch one assistant's full configuration: description, prompts,
    chat colors, avatar, first message — everything the assistant's
    owner has set up in the SaaS UI. Useful when the app wraps an
    assistant and wants to render its branding faithfully.

    `secret` is only required for enterprise-encrypted assistants —
    omit for the common case.
    """
    url = f"{_base_url()}/workspace/models/{model_id}"
    params: dict = {}
    if secret:
        params["secret"] = secret
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=_headers(), params=params)
    if r.status_code >= 400:
        raise UtApiV3Error(
            f"get_assistant({model_id}) failed ({r.status_code})",
            status=r.status_code, body=r.text[:500],
        )
    return r.json()


# ---------------------------------------------------------------------------
# High-level assistant chat — the one to use when "the user picked an
# assistant from Understand Tech and we want it to power our chatbot".
# ---------------------------------------------------------------------------

# Process-level cache so we don't refetch the assistant doc on every chat
# turn. Key: assistant_id. Value: (model_name, api_key_or_None). Small
# in-memory dict — cleared on process restart, which is fine.
_ASSISTANT_RESOLVE_CACHE: dict[str, tuple[str, str | None]] = {}


async def _resolve_assistant(assistant_id: str) -> tuple[str, str | None]:
    """Return (model_name, secret_or_None) for an assistant id, caching
    the result for the lifetime of the process.

    `chat(model=...)` expects the assistant's `model_name` (the human
    string the owner gave it in the SaaS UI), NOT the assistant id.
    Private / enterprise assistants additionally require a `secret`
    (their per-assistant api_key). Both pieces come from `get_assistant`."""
    cached = _ASSISTANT_RESOLVE_CACHE.get(assistant_id)
    if cached:
        return cached
    doc = await get_assistant(assistant_id)
    model_name = (
        doc.get("model_name")
        or doc.get("name")
        or assistant_id  # Last-resort so the caller still tries SOMETHING
    )
    api_key = doc.get("api_key") or None
    _ASSISTANT_RESOLVE_CACHE[assistant_id] = (model_name, api_key)
    return model_name, api_key


async def chat_with_assistant(
    assistant_id: str,
    prompt: str,
    *,
    history: list[dict] | None = None,
    language: str = "en-US",
    session_id: str | None = None,
    enable_thinking: bool = False,
    enable_web_search: bool = False,
    file_ids: list[str] | None = None,
) -> dict:
    """**The one-call API for "wire a UT assistant into a chatbot".**

    The App Builder gives the agent each assistant's `id` via the system
    prompt under selected_resources / available_resources. Pass that id
    in here as `assistant_id`. This helper does the rest:

      1. Fetches the assistant doc via `get_assistant(id)`.
      2. Pulls `model_name` (what `chat()` wants for `model`) and
         `api_key` (what `chat()` wants for `secret` on private
         assistants).
      3. Calls `chat(...)` with the correct values.

    Returns the same shape as `chat()`. Use `extract_chat_text(result)`
    to get the assistant's reply text portably.

    Prefer this over calling `chat()` directly when the goal is to wrap
    a user's UT assistant. Calling `chat()` directly is for cases where
    you already know the exact `model_name` string and have the secret
    in hand (rare in generated apps)."""
    model_name, secret = await _resolve_assistant(assistant_id)
    return await chat(
        model=model_name,
        prompt=prompt,
        history=history,
        language=language,
        session_id=session_id,
        enable_thinking=enable_thinking,
        enable_web_search=enable_web_search,
        file_ids=file_ids,
        secret=secret,
    )


async def chat_with_assistant_stream(
    assistant_id: str,
    prompt: str,
    *,
    history: list[dict] | None = None,
    language: str = "en-US",
    session_id: str | None = None,
    enable_thinking: bool = False,
    enable_web_search: bool = False,
    file_ids: list[str] | None = None,
    word_delay_ms: int = 30,
) -> AsyncIterator[str]:
    """Streaming counterpart to `chat_with_assistant`. Yields word-sized
    text chunks suitable for a typewriter UI over SSE / WebSocket.

    Same resolve-id-once-then-cache behaviour as `chat_with_assistant`.
    """
    model_name, secret = await _resolve_assistant(assistant_id)
    async for chunk in chat_text_stream(
        model=model_name,
        prompt=prompt,
        history=history,
        language=language,
        session_id=session_id,
        enable_thinking=enable_thinking,
        enable_web_search=enable_web_search,
        file_ids=file_ids,
        secret=secret,
        word_delay_ms=word_delay_ms,
    ):
        yield chunk


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


class WorkflowRun:
    """Handle for an async workflow execution. Returned by
    `run_workflow()`. Use `.wait()` to block until terminal status, or
    poll `.status()` yourself.

    UT marks completion via `status_job` ∈ {pending, in_progress, succeeded,
    failed, cancelled, error}. `.wait()` returns the full status payload
    on success and raises `UtApiV3Error` on the terminal failure states.
    """

    # Terminal status values as observed in UT's response. If UT
    # introduces new states they fall through `_TERMINAL_OK` /
    # `_TERMINAL_ERR` and `.wait()` keeps polling — safer than
    # bailing on an unrecognized state.
    _TERMINAL_OK = {"succeeded", "completed", "done"}
    _TERMINAL_ERR = {"failed", "error", "cancelled", "canceled"}

    def __init__(self, workflow_id: str, session_token: str, raw: dict | None = None):
        self.workflow_id = workflow_id
        self.session_token = session_token
        self.raw_execute_response = raw or {}

    async def status(self) -> dict:
        """One poll — returns UT's `JobStatusSchema` payload."""
        url = f"{_base_url()}/public/workflows/executions/status"
        # Status endpoint takes form-encoded body (not JSON).
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                url,
                headers=_headers(),
                data={
                    "workflow_id": self.workflow_id,
                    "session_token": self.session_token,
                },
            )
        if r.status_code >= 400:
            raise UtApiV3Error(
                f"workflow status failed ({r.status_code})",
                status=r.status_code, body=r.text[:500],
            )
        return r.json()

    async def wait(self, *, timeout: float = 300.0, poll_every: float = 2.0) -> dict:
        """Poll until the run reaches a terminal state. Returns the
        final status payload (which carries `result`). Raises
        `UtApiV3Error` on workflow-level failure or timeout."""
        deadline = asyncio.get_event_loop().time() + timeout
        last_payload: dict = {}
        while asyncio.get_event_loop().time() < deadline:
            payload = await self.status()
            last_payload = payload
            state = (payload.get("status_job") or "").lower()
            if state in self._TERMINAL_OK:
                return payload
            if state in self._TERMINAL_ERR:
                raise UtApiV3Error(
                    f"workflow run finished with state '{state}'",
                    body=str(payload.get("error") or payload)[:500],
                )
            await asyncio.sleep(poll_every)
        raise UtApiV3Error(
            f"workflow run timed out after {timeout:.0f}s "
            f"(last state: {last_payload.get('status_job')!r})",
            body=str(last_payload)[:500],
        )


async def run_workflow(public_token: str, prompts: dict) -> WorkflowRun:
    """Enqueue a publicly-shared workflow execution.

    Args:
        public_token: the workflow's `public_token`. Workflows without
            one cannot be executed via the public API — surface that
            to the end user; you'll need the workflow owner to share
            it from the SaaS UI first.
        prompts:      object mapping the trigger node's `params_output`
            names to their string values. For the "Document Manual
            Trigger" node whose output was `Prompt`, pass
            `{"Prompt": "Explain PQC"}`.

    Returns a `WorkflowRun` handle. Call `.wait()` to block until the
    run finishes; the returned payload has `result`.
    """
    if not public_token:
        raise WorkflowNotShared(
            "workflow has no public_token — its owner must enable "
            "public sharing in the SaaS UI before it can be executed "
            "via the API"
        )
    url = f"{_base_url()}/workflows/public/{public_token}/execute"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, headers=_headers(), json={"prompts": prompts})
    if r.status_code >= 400:
        raise UtApiV3Error(
            f"workflow execute failed ({r.status_code})",
            status=r.status_code, body=r.text[:500],
        )
    data = _safe_json(r)
    workflow_id, session_token = _extract_run_handle(data, r.headers)
    if not (workflow_id and session_token):
        raise UtApiV3Error(
            "workflow execute returned 200 but no workflow_id / "
            "session_token to poll status with. Inspect the response "
            "below and update _extract_run_handle.",
            body=json.dumps(data)[:500] if data else (r.text or "")[:500],
        )
    return WorkflowRun(workflow_id=workflow_id, session_token=session_token, raw=data or {})


def _safe_json(resp: httpx.Response) -> Optional[dict]:
    """Parse JSON body, returning None on non-JSON content."""
    if "application/json" not in (resp.headers.get("content-type") or "").lower():
        return None
    try:
        return resp.json()
    except Exception:
        return None


def _extract_run_handle(data: dict | None, headers) -> tuple[str | None, str | None]:
    """The execute endpoint's response schema is undocumented. We try
    the obvious places — body keys, response headers — and accept
    whichever shows up first. Update here when the shape stabilizes."""
    workflow_id: str | None = None
    session_token: str | None = None
    if isinstance(data, dict):
        workflow_id = (
            data.get("workflow_id")
            or data.get("workflowId")
            or (data.get("data") or {}).get("workflow_id")
            if isinstance(data.get("data"), dict) else None
        )
        session_token = (
            data.get("session_token")
            or data.get("sessionToken")
            or data.get("token")
            or data.get("job_id")  # last resort — some APIs reuse job_id as the poll token
            or (data.get("data") or {}).get("session_token")
            if isinstance(data.get("data"), dict) else None
        )
    if not workflow_id:
        workflow_id = headers.get("x-workflow-id")
    if not session_token:
        session_token = headers.get("x-session-token")
    return workflow_id, session_token
