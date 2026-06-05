# Your App

> Generated with **Understand Studio** — an AI app builder by [Understand Tech](https://understand.tech).

A full-stack web app: **React + Vite** (frontend), **FastAPI** (backend), **MongoDB** (database). AI features are wired through Understand Tech's API or directly through Anthropic, depending on how you run it.

This README explains how to run the app locally, what's in the repo, and how to switch between the two AI modes after download.

---

## Quick start

### Prerequisites

You need **Docker** with the Compose plugin. The easiest path on each OS:

| OS | What to install |
|---|---|
| **macOS** | [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/) |
| **Windows** | [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/) (WSL2 backend recommended) |
| **Linux** | [Docker Engine](https://docs.docker.com/engine/install/) + the [Compose plugin](https://docs.docker.com/compose/install/linux/) |

Verify with `docker --version` and `docker compose version` — both should print versions, no errors.

### Run the app

#### macOS / Linux

```bash
# 1. Make sure Docker is running (Docker Desktop, or `sudo systemctl start docker` on Linux).
# 2. From the repo root:
docker compose up --build
```

#### Windows (PowerShell or Command Prompt)

```powershell
# 1. Start Docker Desktop.
# 2. From the repo root:
docker compose up --build
```

> If `.env` is missing on first run, copy it from `.env.example` (if present) and fill in the values described in **Environment** below.

The app starts on:

- **Frontend:** [http://localhost:5173](http://localhost:5173) (configurable via `FRONTEND_PORT`)
- **Backend:** [http://localhost:8000](http://localhost:8000) (configurable via `BACKEND_PORT`)

The frontend hot-reloads on file changes. The backend reloads on Python file changes.

### Stopping the app

```bash
docker compose down
```

To also delete the MongoDB volume (loses all stored data — **be careful**):

```bash
docker compose down -v
```

---

## Environment

Configuration lives in `.env` at the repo root.

> ⚠️ **Heads up if you just downloaded this app:** the `.env` was seeded for use *inside Studio*. To run it on your own machine you'll need to edit one or two variables — see ["Running the downloaded app"](#running-the-downloaded-app) below. Otherwise Claude features will fail with `Connection refused` on the first AI call.

### What's in `.env`

Studio seeded these variables at project creation:

| Variable | Purpose | Needed after download? |
|---|---|---|
| `UT_API_KEY` | Per-app Understand Tech v3 API key. Auths UT assistants, "Understand AI" secure LLM, and catalog models (GPT-4.1, Claude Sonnet 4.6, Mistral Medium, Gemini 3 Flash, DeepSeek V3, xAI Grok 4.1 Fast). | Keep if you want UT features |
| `UNDERSTAND_API_URL` | UT v3 endpoint. Defaults to `https://developer.understand.tech`. | Keep if you keep `UT_API_KEY` |
| `UT_LLM_BASE_URL` | Studio's local proxy for Claude calls (`http://host.docker.internal:8001/...`). Only resolves while Studio is running on the same host. | **Remove** — see below |
| `UT_ENCRYPTION_SECRET` | Air-gap projects only. | Keep if present |

### While iterating inside Studio

You don't need to do anything. The seeded `.env` works as-is. Claude calls route through Studio's proxy; UT v3 calls go directly to UT.

### Running the downloaded app

`UT_LLM_BASE_URL=http://host.docker.internal:8001/...` points at Studio's orchestrator. **That orchestrator is not in your downloaded ZIP.** On any other machine, the URL has nothing on the other end and the Anthropic SDK will fail to connect.

The fix is always the same: **remove `UT_LLM_BASE_URL` from `.env`.** That's the one critical step. The code auto-detects standalone mode the moment that variable is empty.

Then pick the scenario that matches what you want to do:

#### Option A — UT customer running their own copy (most common)

You keep your UT account, you also bring your own Anthropic key:

```bash
# .env
UT_API_KEY=<your existing UT v3 API key>
UNDERSTAND_API_URL=https://developer.understand.tech
ANTHROPIC_API_KEY=sk-ant-...

# Remove or comment out:
# UT_LLM_BASE_URL=...
```

Result: Claude features hit `api.anthropic.com` with your Anthropic key. UT features (assistants, "Understand AI", catalog models) hit UT directly with your UT key.

#### Option B — Pure Anthropic (no UT)

You're not a UT customer, you just want the scaffold:

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...

# Remove or comment out:
# UT_API_KEY=...
# UT_LLM_BASE_URL=...
# UNDERSTAND_API_URL=...
```

Result: Claude features work. UT features error out (no UT key) — that's fine if your app doesn't use them.

#### Option C — UT-only (no direct Anthropic)

You have a UT account and you only use UT features:

```bash
# .env
UT_API_KEY=<your existing UT v3 API key>
UNDERSTAND_API_URL=https://developer.understand.tech

# Remove or comment out:
# UT_LLM_BASE_URL=...
# (no ANTHROPIC_API_KEY needed)
```

Result: UT features work. Any call to `claude_examples.*` errors with `No AI credentials configured` — by design. If your app doesn't import from `claude_examples`, you'll never see that error.

> **Mode selection is automatic.** The code picks standalone whenever `ANTHROPIC_API_KEY` is set AND `UT_LLM_BASE_URL` is empty/unset; otherwise it tries Studio mode. No flag to flip.

---

## Project structure

```
.
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI entrypoint — routes + lifespan-managed Mongo
│   │   ├── config.py           # Settings (pydantic-settings reads .env)
│   │   ├── claude_examples.py  # AI cookbook: chat, stream, vision, tools (Anthropic SDK)
│   │   ├── ut_ai_examples.py   # AI cookbook for the "Understand AI" secure LLM
│   │   ├── ut_api_v3.py        # UT API v3 client: assistants, workflows, catalog models
│   │   ├── ut_usage.py         # Usage reporting helpers (Claude calls only)
│   │   ├── error_tracker.py    # In-memory error ring buffer + middleware
│   │   └── analytics.py        # Telemetry
│   ├── Dockerfile
│   └── requirements.txt        # fastapi, uvicorn, motor, pydantic-settings, anthropic, httpx
├── frontend/
│   ├── src/
│   │   ├── main.tsx            # React entrypoint
│   │   ├── App.tsx             # Root component — your UI starts here
│   │   ├── index.css           # Tailwind directives + HSL design tokens (light + dark)
│   │   ├── components/ui/      # Pre-vendored shadcn primitives (button, card, input, ...)
│   │   └── lib/utils.ts        # cn() helper (clsx + tailwind-merge)
│   ├── package.json            # React 18 + TypeScript + Vite + Tailwind + Lucide
│   ├── tailwind.config.ts
│   ├── vite.config.ts          # Proxies /api/* → http://backend:8000
│   └── Dockerfile
├── docker-compose.yml          # backend + frontend + mongo, joined on the project network
├── .env                        # Configuration (see Environment)
├── LICENSE                     # You pick — see below
└── README.md                   # This file
```

---

## Tech stack

- **Frontend** — React 18, TypeScript, Vite, Tailwind CSS, shadcn-style UI primitives, Lucide icons, Inter Variable font
- **Backend** — FastAPI, Pydantic v2, Motor (async MongoDB driver), httpx, Anthropic SDK
- **Database** — MongoDB 7
- **AI** — Anthropic Claude (in either AI mode) plus the Understand Tech API v3 surface (Mode 1 only) for UT assistants, "Understand AI" secure LLM, and the UT model catalog

---

## Customizing

Edit any file freely. The frontend hot-reloads; the backend auto-reloads on Python file changes. Backend dependency changes (new entries in `requirements.txt`) require:

```bash
docker compose up --build backend
```

Frontend dependency changes (new entries in `package.json`):

```bash
docker compose up --build frontend
```

For AI features, **read the cookbook files first**:

- [`backend/app/claude_examples.py`](backend/app/claude_examples.py) — working snippets for chat, streaming, vision, and tool use through the Anthropic SDK.
- [`backend/app/ut_api_v3.py`](backend/app/ut_api_v3.py) — UT API v3 client (assistants, catalog models).
- [`backend/app/ut_ai_examples.py`](backend/app/ut_ai_examples.py) — chat helpers for the "Understand AI" secure LLM.

---

## Generated by Understand Studio

This app was scaffolded by **[Understand Studio](https://understand.tech)** — an AI app builder by **[Understand Tech](https://understand.tech)**.

Once you've downloaded this code, **you own it completely**. Understand Tech retains no rights to your generated output, your data, or your customers'.

If you keep building inside Studio you also get:

- AI-driven iteration ("add an admin page", "wire chat to this assistant", …)
- Live preview at a sharable URL
- GitHub auto-sync
- Release locking (signed tarball + SBOM + vuln scan)

---

## License

This repo ships with a **placeholder `LICENSE` file**. Pick the license that fits how you want others to use your code, then replace `LICENSE` with the chosen license's full text.

Common choices:

- **[MIT](https://opensource.org/licenses/MIT)** — most permissive; anyone can use, modify, distribute (with attribution). Simple, common for app code.
- **[Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)** — permissive like MIT plus an explicit patent grant. Enterprise-friendly.
- **[GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.en.html)** — copyleft; derivatives must also be open-source under GPL.
- **Proprietary** — write your own terms; the code stays yours.

Not sure? [choosealicense.com](https://choosealicense.com/) walks you through it in 90 seconds.
