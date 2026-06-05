"""Report private-chat prompt usage. Two helpers live here, ONE for each
chat rail in this app — call the right one or you'll either double-bill
the user or miss usage entirely.

  - `increment_prompt()` — for Claude calls routed through the Studio
    Anthropic proxy. Reports usage to BOTH:
        1. Understand Tech (via `/api/v3/user/usage/increment-private`)
           because UT doesn't see these calls otherwise (they go through
           Studio's proxy, not UT's chat endpoint), so this is how UT's
           prompt quota gets bumped.
        2. The Studio orchestrator (via `/api/__usage/record`) so the
           per-project "total: N prompts" tile reflects this call.
    Used by `claude_examples.py` after every successful Claude call.

  - `report_to_studio_counter()` — for UT API v3 calls (assistants,
    Understand AI, catalog models). UT's `/api/v3/chat` endpoint counts
    usage server-side automatically, so we MUST NOT call increment-
    private here — that would double-bill. We only report to Studio's
    per-project counter so the UI tile stays accurate.
    Used by `ut_ai_examples.py` and any other UT-v3-based helpers.

THE BOUNDARY MATTERS. If you wire a new chat helper:
    - Goes via Anthropic SDK → Studio proxy (UT_LLM_BASE_URL)?
        → call `await increment_prompt()`
    - Goes via UT API v3 (developer.understand.tech)?
        → call `await report_to_studio_counter()`

Auth: `UT_API_KEY` is a v3 API key minted by the Studio orchestrator
at project-creation time and written into `.env`. The same key
authenticates both helpers.

Fail-open: a billing hiccup or network blip must never break a
user-facing chat call. UT-leg retries on transient 5xx in the
background; Studio-counter leg fails silently to debug log.
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

log = logging.getLogger(__name__)


# How many times to retry a transient UT billing failure (5xx or network
# blip) before logging a single final warning. Total worst-case wall
# time = sum of timeouts + backoffs. Kept small so background tasks
# don't pile up if UT is having a sustained outage.
_RETRY_ATTEMPTS = 3
# Per-attempt timeout. Down from 5s — UT either responds fast or it's
# not responding at all; a 5s timeout just delays the retry decision.
_PER_ATTEMPT_TIMEOUT = 3.0
# Exponential backoff between attempts: 0.5s, 1.5s.
_BACKOFFS = (0.5, 1.5)


def _short(text: str, n: int = 120) -> str:
    """Compact a multi-line response body into a one-line log fragment
    (e.g. nginx HTML 503 pages span multiple lines and bloat the log).
    Replaces newlines + collapses whitespace."""
    if not text:
        return ""
    return " ".join(text.split())[:n]


def _api_base() -> str:
    return os.environ.get(
        "UNDERSTAND_API_URL", "https://developer.understand.tech"
    ).rstrip("/")


def _api_key() -> str:
    return os.environ.get("UT_API_KEY", "")


def _appbuilder_usage_url() -> str | None:
    """Return the orchestrator's usage-callback URL, derived from
    `UT_LLM_BASE_URL` (the Anthropic proxy URL the orchestrator
    already configured on this app). Returns None if we can't
    confidently derive it — billing then falls back to UT-only.

    UT_LLM_BASE_URL looks like `http://host.docker.internal:8001/api/llm/anthropic`
    in both dev and prod (the orchestrator publishes 8001 on the host
    in dev, and runs directly on the EC2 host in prod). Stripping the
    `/api/llm/anthropic` suffix gives the orchestrator's base URL;
    `/api/__usage/record` is the endpoint.
    """
    base = os.environ.get("UT_LLM_BASE_URL", "").rstrip("/")
    if not base:
        return None
    # Strip the known Anthropic-proxy suffix if present. If the env
    # var was overridden to something else, leave it as the base.
    SUFFIX = "/api/llm/anthropic"
    if base.endswith(SUFFIX):
        base = base[: -len(SUFFIX)]
    return f"{base}/api/__usage/record"


class _Transient(Exception):
    """Raised by `_attempt_increment_ut` when the response indicates the
    failure is transient (5xx) and should be retried. 4xx errors (apart
    from 429) are NOT transient and don't retry."""


async def _attempt_increment_ut(key: str, count: int) -> None:
    """One POST to UT's increment-private endpoint. Returns silently on
    200 / 429 (quota — handled by caller flagging chat as uncharged).
    Raises `_Transient` on 5xx / network errors so the retry loop above
    can decide whether to back off. Raises nothing else — 4xx is logged
    and swallowed since it's a real misconfiguration and retry won't
    help."""
    # IMPORTANT: customer-mode (api-key Bearer) routes live under
    # `/api/v3/...` on UT. The non-versioned `/api/user/usage/...`
    # path is firebase-auth (cookie session) — used by the SaaS web app
    # and the orchestrator's own UT integration, NOT by generated apps.
    # Wrong path = 404 silently in the chat logs.
    url = f"{_api_base()}/api/v3/user/usage/increment-private"
    async with httpx.AsyncClient(timeout=_PER_ATTEMPT_TIMEOUT) as client:
        r = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Accept-Language": "en-US",
            },
            params={"count": count},
        )
    if r.status_code == 429:
        log.warning("UT usage quota exceeded — chat will continue uncharged")
        return
    if r.status_code < 400:
        return
    body = _short(r.text)
    if 500 <= r.status_code < 600:
        # Transient — let the retry loop decide whether to back off.
        raise _Transient(f"{r.status_code} {body}")
    # 4xx that isn't 429: misconfig (wrong URL, expired key, …).
    # Retrying won't help; log once and give up.
    log.warning("UT increment-private failed (%d): %s", r.status_code, body)


async def _retry_increment_ut(key: str, count: int) -> None:
    """Background task: try `_attempt_increment_ut` up to `_RETRY_ATTEMPTS`
    times, backing off between attempts. Logs a single warning if all
    attempts fail. Never raises — the chat call has already returned
    to the user by the time this runs."""
    last_err = ""
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            await _attempt_increment_ut(key, count)
            return
        except _Transient as e:
            last_err = str(e)
        except httpx.RequestError as e:
            last_err = f"network: {type(e).__name__}: {e}"
        except Exception as e:
            # Unexpected — log and stop retrying.
            log.warning("UT increment-private unexpected error: %s", e)
            return
        if attempt < _RETRY_ATTEMPTS - 1:
            await asyncio.sleep(_BACKOFFS[attempt])
    log.warning(
        "UT increment-private failed after %d attempts: %s",
        _RETRY_ATTEMPTS,
        _short(last_err),
    )


async def _post_studio_counter(key: str, count: int) -> None:
    """Inline POST to Studio's `/api/__usage/record` endpoint. Bumps the
    per-project "total: N prompts" UI tile. Fail-open — debug-logs and
    swallows any error so chat is never broken by a counter blip.

    Stays inline (no background task) because the orchestrator runs on
    the same host (host.docker.internal in dev, in-cluster in prod);
    latency is negligible and retrying adds no value."""
    callback = _appbuilder_usage_url()
    if not callback:
        return
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(
                callback,
                headers={"Authorization": f"Bearer {key}"},
                params={"count": count},
            )
    except Exception as e:
        # Fail-open. The Studio counter will under-report, but the user's
        # chat experience is preserved.
        log.debug("studio counter callback failed: %s", e)


async def report_to_studio_counter(count: int = 1) -> None:
    """Bump the Studio per-project counter ONLY. Use after UT API v3
    chat calls — UT counts those server-side at `/api/v3/chat` so calling
    `/api/v3/user/usage/increment-private` would double-bill. Studio's
    counter is a separate UI bookkeeping concern.

    Always returns — never raises."""
    if count < 1:
        return
    key = _api_key()
    if not key:
        return
    await _post_studio_counter(key, count)


async def increment_prompt(count: int = 1) -> None:
    """Report a CLAUDE call (routed through Studio's Anthropic proxy)
    to BOTH UT (for the prompt quota) and Studio (for the per-project
    UI tile).

    Do NOT call this after a UT API v3 chat — UT auto-counts those at
    `/api/v3/chat`, and calling increment-private would double-bill.
    Use `report_to_studio_counter()` instead for that path.

    Always returns — never raises. The UT call runs IN THE BACKGROUND
    with retry-on-5xx, so a slow / blipping UT doesn't add latency to
    the user's chat. The Studio counter call stays inline (same host,
    sub-100ms)."""
    if count < 1:
        return
    key = _api_key()
    if not key:
        return

    # ---- UT API quota — background, retry on transient errors --------
    # Fire-and-forget so a slow UT doesn't block the chat. Tasks live
    # on the running event loop; if the container is shut down mid-flight
    # we may under-bill by at most 1-2 prompts, which is acceptable.
    asyncio.create_task(_retry_increment_ut(key, count))

    # ---- Studio per-project counter ----------------------------------
    await _post_studio_counter(key, count)
