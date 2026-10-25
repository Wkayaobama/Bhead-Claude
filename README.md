# HR Scout

A standalone job-intelligence app: it scrapes job boards you configure,
extracts structured postings with Claude, scores each extraction with
deterministic quality rules, and runs an interview-prep coach over the
documents you upload per job.

**Stack:** React 18 + Vite + Tailwind (frontend) · FastAPI + Motor (backend) ·
MongoDB 7 · the Anthropic API, called directly with your own key.

This repository started as a generated app tied to its builder's runtime. It
has been translated into a self-contained app: one AI seam, one configuration
class with guardrails, rules kept as data, tests, and system maps. The
"Migrating from the generated version" section lists what changed.

---

## Quick start

Prerequisites: Docker with the Compose plugin (`docker compose version`), and an
Anthropic API key from <https://platform.claude.com>.

```bash
cp .env.example .env            # then set ANTHROPIC_API_KEY
docker compose up --build
```

- Frontend: <http://localhost:5173> (`FRONTEND_PORT`)
- API: <http://localhost:8000> — docs at `/api/docs`, health at `/api/health`
  (`BACKEND_PORT`)

Both containers hot-reload on file changes. `docker compose down` stops them;
`docker compose down -v` also deletes the MongoDB volume (all data).

`/api/health` tells you whether the pieces are wired before you spend a scrape:

```json
{
  "status": "ok",
  "mongo": "ok",
  "llm": {"provider": "anthropic", "model": "claude-opus-5-5", "effort": "medium",
          "refusal_fallback": true, "configured": true},
  "quality": {"threshold": 70, "rules": 10},
  "secrets_vault": false,
  "caps": {"scrape_page_chars": 12000, "apify_text_chars": 15000,
           "extract_max_tokens": 16000, "chat_max_tokens": 4096}
}
```

### Running the backend without Docker

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # reads ../.env automatically
pytest                                 # 47 tests, no network, no Mongo
```

The frontend: `cd frontend && npm ci && npm run dev` (the dev server proxies
`/api` to `http://backend:8000`; change `vite.config.ts` to `localhost:8000`
when the API runs outside Docker). `npm run build` type-checks and bundles.

---

## Configuration

All settings live in [`backend/app/config.py`](backend/app/config.py) as one
`Settings` class with typed defaults. Values come from the environment, then
from the first `.env` found at `backend/.env` or the repo root. Unknown keys in
a shared `.env` are ignored. `docker-compose.yml` passes an **explicit
allowlist** of variables into the backend container — a new setting needs a
field in `Settings`, a line in that allowlist, and a row in `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required for scraping and the coach. Missing → the backend starts, `health.llm.configured` is `false`, and the first AI call fails with a clear message. |
| `AI_MODEL` | `claude-opus-5-5` | Model for extraction and chat. `claude-sonnet-5-5` is the lower-cost option for high-volume scraping. |
| `AI_EFFORT` | `medium` | Reasoning depth on Claude 4.6+ models (`low`…`max`). Empty omits the parameter. |
| `AI_REFUSAL_FALLBACK` | `true` | When the model declines a request, the API re-runs it on Anthropic's recommended fallback model in the same call (beta header `server-side-fallback-2026-07-01`). `false` surfaces refusals as errors. |
| `EXTRACT_MAX_TOKENS` / `CHAT_MAX_TOKENS` | `16000` / `4096` | Output ceilings. Hitting one is reported as an error, never persisted as a partial result. |
| `SCRAPE_PAGE_CHARS` / `APIFY_TEXT_CHARS` | `12000` / `15000` | Characters of page text sent to the model per scrape. |
| `APIFY_API_KEY` | — | Optional server-side Apify token; a token typed into the UI wins. |
| `SECRETS_ENCRYPTION_KEY` | — | Passphrase for the Secrets tab's encryption key. Empty disables the vault (503) instead of encrypting with a guessable constant. |
| `CORS_ORIGINS` | — | Comma-separated browser origins allowed cross-origin. Empty installs no CORS middleware: the Vite dev server (and any production proxy) forwards `/api` same-origin. |
| `MONGO_DB`, `PROJECT_NAME`, `SCHEDULER_TICK_SECONDS` | `app`, `HR Scout`, `60` | Database name, display name, cron tick. |

---

## How it fits together

[`docs/SYSTEM_MAPS.md`](docs/SYSTEM_MAPS.md) holds three Mermaid maps — the
mental model, the logical flow and the schema — plus a list of known drift.
The short version:

- **One AI seam.** [`backend/app/llm.py`](backend/app/llm.py) is the only
  module that imports the Anthropic SDK. It exposes `extract_structured`
  (JSON guaranteed by `output_config.format`), `stream_chat` (for the coach's
  SSE) and `chat_once`. It turns `stop_reason == "refusal"` and
  `"max_tokens"` into exceptions so callers never store a declined or truncated
  answer as a result.
- **Rules as data, pure engine.** [`backend/app/quality/`](backend/app/quality)
  scores extractions: `extractor.py` normalises the four scored fields,
  `registry.py` lists rules, bands and the flag threshold as plain
  dataclasses, `engine.py` interprets them with no I/O. The registry is
  validated at import and served at `GET /api/monitor/quality-config`, which
  the Monitor page renders — the UI never restates a threshold.
- **Two scrape paths, one extractor call.** Direct HTML fetch or the Apify
  jobup actor both end in `extract_structured` with the same schema; the
  scheduler fires the HTML path for cron-enabled targets. Sessions record the
  model used for each run.
- **Shared vocabulary.** [`backend/app/categories.py`](backend/app/categories.py)
  is the single category list used by the extraction schema and the feed.

### Project structure

```
backend/
  app/
    main.py          FastAPI app, lifespan (Mongo, indexes, scheduler), /api/health
    config.py        Settings — every tunable, with defaults
    llm.py           the Anthropic seam
    categories.py    job categories
    quality/         extractor · registry · engine
    scheduler.py     asyncio cron loop
    routes/          targets, scraper, apify_scraper, jobs, sessions, documents,
                     monitor, agent_config, secrets, admin
  tests/             engine parity, seam behaviour, route checks (fake Mongo)
  requirements.txt   pinned; requirements-dev.txt adds pytest
frontend/
  src/pages/         JobFeed, Targets, AgentConfig, Sessions, Documents, Monitoring, Secrets
  src/components/ui  vendored shadcn-style primitives
  vite.config.ts     dev server + /api proxy
docker-compose.yml   frontend + backend + mongo
docs/SYSTEM_MAPS.md  the three maps and known drift
```

---

## Migrating from the generated version

If you ran the previous, builder-hosted version of this app:

- **AI calls** now go straight to `api.anthropic.com` with `ANTHROPIC_API_KEY`.
  The proxy URL, per-app key, usage-metering callbacks and the whitelabel
  identity instruction are gone. The default model moved to `claude-opus-5-5`;
  set `AI_MODEL` to keep another.
- **Secrets vault:** the encryption key used to be derived from the host's
  per-app key. Set `SECRETS_ENCRYPTION_KEY` to that old value to keep existing
  secrets readable; otherwise re-enter them.
- **Removed:** the host badge, logo and favicon; the browser error reporter
  (which forwarded every failed `fetch` to the backend); the request analytics
  middleware and error ring buffer with their `/api/__*` endpoints; the CORS
  wildcard; the bundled `claude-template/` scaffold.
- **Fixed on the way:** the production build (`npm run build`) now passes;
  job search escapes regex characters (searching `C++` no longer errors);
  `APIFY_API_KEY` is actually used as the server-side token.
- **Data:** no migration needed; `MONGO_DB` still defaults to `app`.

---

## License

`LICENSE` is still a placeholder. Pick the license that fits how you want
others to use your code and replace the file's contents with its full text —
<https://choosealicense.com> walks through the common options.
