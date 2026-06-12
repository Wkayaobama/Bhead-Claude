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
browser ──/api/*──▶ Vite proxy ──▶ FastAPI routes ──▶ app/llm.py ──▶ Claude
                    (the seam)     (routes/chat.py)   (the ONLY file
                                                       that imports
                                                       `anthropic`)
```

Two invariants keep this template easy to grow and easy to gut:

1. **The frontend only speaks HTTP to `/api/*`.** It holds no AI
   credentials and no model names. Replace it with anything (CLI,
   mobile app, another web stack) without touching the backend.
2. **All Claude traffic flows through `backend/app/llm.py`.** Routes
   import its helpers (`chat_once`, `stream_chat`, `chat_with_tools`,
   `extract_structured`); nothing else imports the `anthropic`
   package. Model swaps, gateways, caching, and usage metering are
   one-file edits.

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
