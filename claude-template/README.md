# claude-template — barebone Claude-mediated app scaffold

This directory is the result of decomposing the parent repository (an
Understand Studio–generated app) down to its load-bearing skeleton. It
contains:

- `template/` — the barebone app: FastAPI backend + optional Vite/React
  frontend, with **one module** (`backend/app/llm.py`) as the only seam
  to Claude.
- `scaffold.py` — a single-file [Click](https://click.palletsprojects.com/)
  CLI (in the spirit of Simon Willison's `click-app` cookiecutter) that
  stamps out a new project from the template.

## Quick start

```bash
pip install click
python scaffold.py new my-app            # full stack
python scaffold.py new my-api --no-frontend   # backend only

cd my-app
cp .env.example .env                     # paste your ANTHROPIC_API_KEY
docker compose up --build
# frontend: http://localhost:5173   backend: http://localhost:8000/api/docs
```

---

## Why this shape — the decomposition, in short

### Frontend / backend decoupling (already clean in the parent)

The parent app's two halves touch at exactly **one seam**: the frontend
calls relative `/api/*` paths, and Vite's dev server proxies them to
`http://backend:8000` (`vite.config.ts → server.proxy`). The frontend
holds **zero** AI credentials, zero SDK code, and zero knowledge of
which model answers — it only consumes JSON and Server-Sent Events.
That seam is preserved verbatim here, because it is the right design:
you can replace either half without touching the other.

### How the LLM was wired in the parent

Every Claude call funneled through `backend/app/claude_examples.py`:

```
route (scraper.py, documents.py)
   └─ helper (chat_once / stream_chat / extract_structured / chat_with_tools)
        └─ get_client()  ← singleton AsyncAnthropic
             ├─ Studio mode:    api_key=UT_API_KEY, base_url=UT_LLM_BASE_URL (vendor proxy)
             └─ Standalone mode: api_key=ANTHROPIC_API_KEY → api.anthropic.com
```

The key insight: **the vendor never forked the protocol — it only moved
the endpoint.** The proxy is Anthropic-API-compatible, so "Studio mode"
is just the official SDK pointed at a different `base_url` with a
different bearer token. That is why the dependency is trivially
removable.

### The dependencies, and how each was overcome

| Parent dependency | What it did | How the template overcomes it |
|---|---|---|
| `UT_LLM_BASE_URL` + `UT_API_KEY` (proxy auth) | Routed SDK traffic through the vendor's metered gateway | Deleted. `AsyncAnthropic()` is constructed with no args — the SDK reads `ANTHROPIC_API_KEY` from the environment and talks to `api.anthropic.com` directly |
| `ut_usage.increment_prompt()` (billing callback) | Fire-and-forget POST to two vendor endpoints after every call | Deleted. With a direct key, Anthropic's own console is your usage meter; `response.usage` is logged if you want local metering |
| `_IDENTITY_PRELUDE` (whitelabel directive) | Silently prepended to every system prompt to hide "Claude" from end users | Deleted. Your app, your identity policy — add your own system prompt instead |
| `ut_api_v3.py` (vendor assistant/catalog API) | Parallel chat rail to the vendor's own LLM products | Deleted entirely — it was never on the Claude path |
| Mongo, scheduler, scrapers, secrets vault, analytics | App-specific features of the parent | Removed — they were consumers of the LLM seam, not part of it. Add back what your app needs |

What survives is the part worth keeping: the helper signatures
(`chat_once`, `stream_chat`, `chat_with_tools`, `extract_structured`),
the singleton-client pattern, and the SSE bridge from streaming Claude
output to the browser — updated to current API practice (adaptive
thinking, `output_config.format` for structured output, generous
`max_tokens`).

### The one rule of the template

**All Claude traffic goes through `backend/app/llm.py`.** Routes import
helpers from it and nothing else imports the `anthropic` package. Keep
that invariant and you can swap models, add caching, insert a gateway,
or meter usage by editing exactly one file — which is precisely the
property that made the parent app easy to dissect.

### Second rail: headless workflows (added, not substituted)

The template also carries a second, parallel LLM rail with the same
seam discipline: `backend/app/headless.py` is the only place a
`claude` subprocess is spawned (Claude Code CLI in print mode —
`claude -p "/review" --output-format text`), and
`backend/app/workflows.py` adds a file-backed registry + interval
scheduler so prompts and cadences vary at runtime via
`/api/workflows`. See the template README's "Headless workflows"
section.

Full documentation of both loading modes — in-process SDK vs headless
CLI: auth, execution models, permission policy, scheduler semantics,
failure tables, decision guide — lives in
[`template/docs/llm-modes.md`](template/docs/llm-modes.md) and ships
with every scaffolded project.
