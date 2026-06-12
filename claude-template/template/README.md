# __app_name__

Barebone Claude-mediated app: **FastAPI** backend, optional **React +
Vite** frontend, official **Anthropic SDK**. No database, no vendor
gateway, no telemetry — add what your app needs.

## Run

```bash
cp .env.example .env     # paste your ANTHROPIC_API_KEY
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend docs: http://localhost:8000/api/docs

Or backend-only, without Docker:

```bash
cd backend
pip install -r requirements.txt
ANTHROPIC_API_KEY=sk-ant-... uvicorn app.main:app --reload
```

## Architecture

```
browser ──/api/*──▶ Vite proxy ──▶ FastAPI routes ──▶ app/llm.py ──▶ Claude API
                    (the seam)     (routes/chat.py)   (seam #1: the ONLY file
                                                       that imports `anthropic`)

scheduler ─▶ app/workflows.py ─▶ app/headless.py ──▶ `claude -p ...` ─▶ /repo
(lifespan)   (registry + runs)   (seam #2: the ONLY     (Claude Code CLI,
             routes/workflows.py  spawner of `claude`)   agentic, tool access)
```

> **Quick reference:** [`docs/cheatsheet.md`](docs/cheatsheet.md) — every
> helper, endpoint, env var, and file location on one page.
> **Cloud deploy:** [`docs/deploy-cloudrun.md`](docs/deploy-cloudrun.md) +
> `./deploy/cloudrun.sh` — single-container Google Cloud Run deployment
> (built frontend served by FastAPI, clone-on-demand workflow repo,
> two scheduling strategies).
> **Deep dive:** [`docs/llm-modes.md`](docs/llm-modes.md) documents both
> LLM loading modes exhaustively — auth resolution, request anatomy,
> the SSE contract, the CLI permission model, scheduler semantics,
> failure modes, and when to use which.

Three invariants keep this template easy to grow and easy to gut:

1. **The frontend only speaks HTTP to `/api/*`.** It holds no AI
   credentials and no model names. Replace it with anything (CLI,
   mobile app, another web stack) without touching the backend.
2. **All Claude API traffic flows through `backend/app/llm.py`.**
   Routes import its helpers (`chat_once`, `stream_chat`,
   `chat_with_tools`, `extract_structured`); nothing else imports the
   `anthropic` package. Model swaps, gateways, caching, and usage
   metering are one-file edits.
3. **All headless agent runs flow through `backend/app/headless.py`.**
   It is the only place a `claude` subprocess is spawned. CLI flags,
   sandboxing, and capability policy live in one file.

## Headless workflows

Periodic agentic jobs against a repository — `claude -p "/review"`,
`claude -p "/security-review"`, or any free-form prompt — managed at
runtime through the API. Two example workflows are seeded **disabled**
on first boot.

```bash
# See what's registered (note the seeded ids)
curl -s localhost:8000/api/workflows | python -m json.tool

# Enable the seeded daily /review
curl -s -X PATCH localhost:8000/api/workflows/<id> \
  -H 'Content-Type: application/json' -d '{"enabled": true}'

# Register a custom prompt on a custom cadence
curl -s -X POST localhost:8000/api/workflows \
  -H 'Content-Type: application/json' -d '{
    "name": "TODO sweep",
    "prompt": "List every TODO/FIXME added in the last week with file:line and a one-line triage suggestion.",
    "interval_minutes": 10080
  }'

# Trigger immediately (runs in the background, returns 202 + run id)
curl -s -X POST localhost:8000/api/workflows/<id>/run

# Read the results
curl -s localhost:8000/api/workflows/<id>/runs | python -m json.tool
```

How it hangs together:

- **Target repo** — runs execute in `/repo`, which docker-compose
  binds to `WORKFLOW_TARGET_DIR` from `.env` (default: this project).
- **Auth** — the CLI uses the same `ANTHROPIC_API_KEY` as the SDK.
- **Permissions** — print mode is non-interactive, so read-only
  prompts (/review, /security-review) work as-is; workflows that must
  write need explicit grants (`allowed_tools` / `extra_args` on the
  workflow). Nothing bypasses permissions by default.
- **State** — definitions in `backend/data/workflows.json`, run
  history in `backend/data/runs.jsonl` (gitignored). Swap the
  load/save pair in `app/workflows.py` for a database when needed.
- **No overlap** — a workflow never runs concurrently with itself;
  manual triggers return 409 while a run is in flight.

## Extending

- **New AI feature** → add a route in `backend/app/routes/`, call a
  helper from `app/llm.py`. Need a new pattern (vision, batches)? Add
  it to `llm.py`, nowhere else.
- **Persistence** → add Mongo/Postgres to `docker-compose.yml` and wire
  it in a FastAPI lifespan handler in `main.py`.
- **System prompt / persona** → `SYSTEM_PROMPT` in `routes/chat.py`.
- **Model choice** → `AI_MODEL` in `.env` (default `claude-opus-4-8`;
  use `claude-sonnet-4-6` for speed/cost, `claude-haiku-4-5` for
  high-volume simple tasks).
