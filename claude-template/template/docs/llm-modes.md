# LLM Loading Modes — __app_name__

This app talks to Claude through **two deliberately separate modes**,
each with its own seam module, loading mechanism, auth path, execution
model, and failure profile. This document covers both exhaustively.

| | **Mode 1 — In-process API** | **Mode 2 — Headless agent** |
|---|---|---|
| Seam module | `backend/app/llm.py` | `backend/app/headless.py` |
| What loads | `anthropic` Python SDK, in the FastAPI process | Claude Code CLI binary, as a subprocess |
| Transport | HTTPS to `api.anthropic.com` (Messages API) | CLI print mode: `claude -p "<prompt>"` |
| Capabilities | Chat, streaming, vision, tool use, structured JSON | Full agent: reads files, greps, runs git, follows slash commands |
| Who drives the loop | Your code (or no loop at all) | The CLI's internal agent loop |
| Latency profile | Sub-second to ~minutes (one model call) | Minutes (multi-step agentic run) |
| State | Stateless per call — you pass history | Stateless per run — fresh session each time |
| Triggered by | HTTP routes (`routes/chat.py`) | Scheduler or `POST /api/workflows/{id}/run` |
| Working set | Whatever you put in `messages` | The repository mounted at `/repo` |
| Typical use | Chat UI, extraction, classification | `/review`, `/security-review`, repo audits |

**The invariant behind both:** each mode has exactly one module that
owns it. Nothing outside `llm.py` imports `anthropic`; nothing outside
`headless.py` spawns a `claude` process. Every cross-cutting change
(auth, gateway, metering, sandboxing) is therefore a one-file edit.

---

## Mode 1 — In-process API (the SDK rail)

### 1.1 How it loads

`llm.py` holds a lazily-constructed **singleton** client:

```python
_client: Optional[AsyncAnthropic] = None

def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()   # no args — env resolution
    return _client
```

Loading happens on the **first LLM call**, not at import or app
startup. Consequences:

- The app boots fine without credentials; only the first AI request
  fails. `/api/health` never depends on Anthropic.
- One client instance serves the whole process. The SDK pools HTTP
  connections internally — do **not** construct per-request clients.
- The no-args constructor resolves credentials from the environment in
  this order: `ANTHROPIC_API_KEY` → `ANTHROPIC_AUTH_TOKEN` → a local
  `ant auth login` profile. In this template you set
  `ANTHROPIC_API_KEY` in `.env`, which docker-compose injects via
  `env_file`.

The SDK's built-in resilience comes for free: automatic retries on
429/5xx/connection errors (default `max_retries=2`, exponential
backoff) and a 10-minute default request timeout.

**Lineage note.** In the parent app this template was extracted from,
`get_client()` had two *sub*-modes — a vendor-proxy mode
(`base_url=UT_LLM_BASE_URL`, bearer `UT_API_KEY`) and a standalone
mode. The template keeps only standalone, but the extension point
survives: to route through any Anthropic-compatible gateway, this one
constructor is where `base_url=` (and nothing else) would change.

### 1.2 The four request patterns

All helpers share three defaults: model from `settings.ai_model`
(env `AI_MODEL`, default `claude-opus-4-8`), adaptive thinking
(`thinking={"type": "adaptive"}` — Claude decides when and how much to
reason), and generous `max_tokens` (16 000 non-streaming, 64 000
streaming) so output never truncates mid-thought.

**`chat_once(user_message, system_prompt=, history=, model=, max_tokens=)`**
One request → one text reply. `history` is the prior turns, oldest
first: `[{"role": "user"|"assistant", "content": "..."}]`. The API is
stateless — *you* persist and resend history each turn. The helper
filters response blocks by `type == "text"` because adaptive thinking
can put `thinking` blocks ahead of the text.

**`stream_chat(...)` → async iterator of text chunks**
Same signature; yields tokens as Claude generates them, via the SDK's
`messages.stream(...)` / `text_stream` helper. Pair it with the SSE
bridge below.

**`chat_with_tools(user_message, tools, tool_handler, max_rounds=5, ...)`**
A *manual* agent loop in ~40 lines, kept manual on purpose so you can
gate, log, or require human approval per tool call:

```
loop (≤ max_rounds):
  → messages.create(tools=...)
  → append resp.content to history  ← FULL content, thinking + tool_use blocks
  → stop_reason != "tool_use"?  → return the text
  → else: run tool_handler(name, input) per tool_use block,
          append all tool_results as ONE user message, continue
```

Rules the loop encodes (break them and the API 400s):
- Echo the assistant's *entire* `content` back, never just the text.
- Every `tool_use.id` must get a matching `tool_result.tool_use_id`.
- Handler exceptions become `tool_result` blocks with
  `"is_error": true` — Claude sees the error and adapts; the loop
  doesn't crash.

**`extract_structured(user_message, schema, ...) → dict`**
Guaranteed-shape JSON via the API's structured outputs
(`output_config={"format": {"type": "json_schema", "schema": ...}}`).
The API enforces the schema server-side — no markdown stripping, no
regex, no retry-on-bad-JSON. Schema constraints: every object level
needs `"additionalProperties": false`; numeric/string min/max bounds
are unsupported (validate those yourself after parsing).

### 1.3 The SSE bridge (how streaming reaches the browser)

The HTTP contract between `routes/chat.py` and the frontend — the
*only* thing the frontend knows about AI:

```
POST /api/chat/stream          {"message": "...", "history": [...]}
←  data: {"text": "chunk"}     0..n events
←  data: {"done": true}        terminal (success)
←  data: {"error": "..."}      terminal (failure — sent mid-stream too,
                               since HTTP 200 already went out)
```

Implementation details that matter:
- `media_type="text/event-stream"` + `X-Accel-Buffering: no` (stops
  nginx-style proxies from buffering the stream into one lump).
- Exceptions inside the generator can't change the status code
  anymore — that's why errors travel *in-band* as an `error` event.
  The frontend (`App.tsx`) renders them into the open bubble.
- The frontend parses frames by splitting on `\n\n`, keeping the last
  partial frame in a buffer — standard SSE-over-fetch.

### 1.4 Failure modes

| Failure | Surfaces as | Handling |
|---|---|---|
| Missing/bad key | `AuthenticationError` (401) on first call | Fail fast; fix `.env`. Don't retry. |
| Rate limit | `RateLimitError` (429) | SDK already retried twice; surface to user after that. |
| Overload/5xx | `InternalServerError` / `OverloadedError` | SDK retries; then treat as bad gateway. |
| `stop_reason == "max_tokens"` | Truncated reply | Raise `max_tokens` or stream. |
| `stop_reason == "refusal"` | Empty/partial content | Don't read `content[0]` blindly; surface the refusal. |
| Mid-stream exception | `data: {"error": ...}` SSE event | Frontend renders in-band. |

### 1.5 Extension points (all inside `llm.py`)

- **Gateway/proxy** → add `base_url=` in `get_client()`.
- **Usage metering** → log `resp.usage` after each `create()` (the
  parent app's `increment_prompt()` hook sat exactly here).
- **Prompt caching** → add `cache_control` to a stable system prompt.
- **New patterns** (vision, PDFs, batches) → new helper functions
  here, never inline SDK calls in routes.

---

## Mode 2 — Headless agent (the CLI rail)

### 2.1 How it loads

Three layers load at different times:

1. **Image build** — the backend `Dockerfile` installs git and the
   Claude Code CLI (`curl -fsSL https://claude.ai/install.sh | bash`),
   puts `/root/.local/bin` on `PATH`, and marks all directories
   git-safe (the mounted repo belongs to the host user, not container
   root — without `safe.directory`, every git command the agent runs
   would fail with "dubious ownership").
2. **Container start** — docker-compose bind-mounts
   `${WORKFLOW_TARGET_DIR:-.}` at `/repo`. That directory is the
   agent's entire world: every run executes with `cwd=/repo`.
3. **Server start** — the FastAPI lifespan launches
   `workflows.scheduler_loop()` as a background asyncio task and
   cancels it on shutdown. No run happens at boot; the scheduler only
   *polls*.

**Auth:** the CLI reads the same `ANTHROPIC_API_KEY` from the process
environment (`run_headless` passes `env={**os.environ}`). One secret
serves both modes.

### 2.2 Execution model

Every run is one subprocess, built by `run_headless()`:

```
claude -p "<prompt>" --output-format text
       [--model <model>] [--allowedTools a,b,c] [<extra_args>...]
```

- **Print mode (`-p`)** is non-interactive: the CLI runs its full
  agent loop (read files, grep, git, reason, possibly many model
  calls) and prints the final result to stdout, then exits. Exit code
  0 = success.
- **The prompt is anything the interactive CLI accepts** — a slash
  command (`/review`, `/security-review`) or free-form text ("list
  every TODO added this week with file:line"). This is what makes the
  orchestration generic: varying the workload = varying a string.
- **`--output-format`**: `text` (default here — final answer only,
  human-readable, ideal for storing/posting), `json` (single JSON
  envelope with result + metadata — switch to this when a machine
  consumes the run), `stream-json` (newline-delimited events while the
  agent works — for live progress UIs; would pair with an SSE bridge
  like Mode 1's).
- **Fresh session per run.** No memory carries over between runs. If a
  workflow needs continuity, give it a file to read/write inside
  `/repo` and say so in the prompt.
- **Bounded:** output capture is capped at 200 KB per stream, and a
  run is killed after `timeout` seconds (default 1800). A timeout is
  recorded as `exit_code: -1`, not an exception.

### 2.3 Permission model — the part to actually read

Print mode cannot ask "allow this?" — so anything that would prompt is
**denied by default**. That makes the default posture read-leaning:

- `/review`, `/security-review`, audits, summaries → work as-is.
- Workflows that must **edit files** or run **state-changing
  commands** need explicit grants, per workflow, stored on the
  workflow record:
  - `allowed_tools`: an allowlist passed as `--allowedTools`, e.g.
    `["Edit", "Bash(git diff:*)"]` — the `Tool(filter)` syntax scopes
    bash to specific command prefixes.
  - `extra_args`: raw flag passthrough, e.g.
    `["--permission-mode", "acceptEdits"]` to auto-accept file edits,
    or `["--max-turns", "30"]` to bound the loop.
- Nothing in this template ever passes a permission-bypass flag, and
  you shouldn't either for scheduled unattended runs — grant the
  narrowest capability that lets the workflow succeed.

Defense in depth comes from the mount: the agent can only see `/repo`
(plus the container itself). Point `WORKFLOW_TARGET_DIR` at the one
repo the workflow should touch, nothing wider.

### 2.4 The orchestration layer (`workflows.py`)

Three stacked pieces, all file-backed so the template stays
database-free:

**Registry** — `backend/data/workflows.json`, one record per workflow:

```json
{
  "id": "a1b2c3d4e5f6",
  "name": "Code review",
  "prompt": "/review",
  "interval_minutes": 1440,
  "enabled": false,
  "model": null,
  "allowed_tools": null,
  "extra_args": null,
  "last_run": "2026-06-12T08:00:00+00:00"
}
```

First boot seeds two **disabled** examples (`/review` daily,
`/security-review` weekly) so the API is self-documenting without
burning tokens until you opt in.

**Runner** — `start_run(workflow)`:
- Refuses overlap: a per-process `_active` set guarantees a workflow
  never runs concurrently with itself (scheduler tick *and* manual
  trigger both go through this gate; manual gets a 409).
- Returns the run record immediately with `status: "running"` and
  executes in a background task — HTTP callers poll for the result.
- Stamps `last_run` at the **start** of the run, so a 20-minute review
  doesn't drift a daily cadence.
- On completion appends the full record to `backend/data/runs.jsonl`:

```json
{"id": "...", "workflow_id": "...", "workflow_name": "Code review",
 "prompt": "/review", "status": "completed", "exit_code": 0,
 "stdout": "<the review>", "stderr": "", "duration_s": 312.4,
 "started_at": "...", "finished_at": "..."}
```

`status` is `completed` (exit 0), or `failed` (non-zero exit, timeout,
or spawn error — e.g. CLI binary missing — with the reason in
`stderr`). A failed run never takes the server down.

**Scheduler** — `scheduler_loop()` wakes every 30 s and fires any
workflow where `enabled` and `now - last_run ≥ interval_minutes`
(never-run workflows are immediately due the moment they're enabled).
Semantics to know:
- It's an *interval* scheduler, not cron — "every 24 h from the last
  start", not "at 03:00". For wall-clock cadences, swap `_is_due()`
  for a cron expression check; nothing else changes.
- Ticks are independent and exception-guarded: one bad workflow logs
  and doesn't stop the others.
- State lives in the JSON file, so an app restart preserves cadence
  (a workflow due during downtime simply fires on the first tick).

### 2.5 HTTP API

| Method & path | Purpose | Returns |
|---|---|---|
| `GET /api/workflows` | List definitions | 200 list |
| `POST /api/workflows` | Create (name, prompt, interval_minutes, enabled, model?, allowed_tools?, extra_args?) | 201 record |
| `PATCH /api/workflows/{id}` | Edit any field — enable, change prompt/cadence | 200 record |
| `DELETE /api/workflows/{id}` | Remove definition (history stays) | 204 |
| `POST /api/workflows/{id}/run` | Trigger now, run in background | **202** run record / **409** if already running |
| `GET /api/workflows/{id}/runs` | History for one workflow, newest first | 200 list |
| `GET /api/workflows/runs` | History across all workflows | 200 list |

Worked session:

```bash
# 1. discover the seeded workflows and their ids
curl -s localhost:8000/api/workflows | python -m json.tool

# 2. enable the daily /review
curl -s -X PATCH localhost:8000/api/workflows/<id> \
  -H 'Content-Type: application/json' -d '{"enabled": true}'

# 3. don't wait a day — trigger it now
curl -s -X POST localhost:8000/api/workflows/<id>/run

# 4. poll until status flips from "running"
curl -s localhost:8000/api/workflows/<id>/runs | python -m json.tool

# 5. register a varying free-form prompt
curl -s -X POST localhost:8000/api/workflows \
  -H 'Content-Type: application/json' -d '{
    "name": "TODO sweep",
    "prompt": "List every TODO/FIXME added in the last week with file:line and a one-line triage suggestion.",
    "interval_minutes": 10080
  }'
```

### 2.6 Failure modes & troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Run `failed`, stderr `No such file or directory: 'claude'` | CLI not installed / not on PATH | Rebuild the backend image; or set `CLAUDE_BIN` to the binary's full path |
| Run `failed`, auth error in stderr | `ANTHROPIC_API_KEY` missing in container env | Check `.env` + `env_file` in compose |
| stderr mentions "dubious ownership" | git safe.directory not applied | Rebuild image (Dockerfile sets `safe.directory '*'`) |
| `exit_code: -1`, stderr "timed out" | Run exceeded `timeout` (default 1800 s) | Raise the timeout in `run_headless`, or narrow the prompt |
| Output looks truncated | 200 KB capture cap | Raise `_MAX_CAPTURE` in `headless.py`, or have the workflow write its report to a file in `/repo` |
| 409 on manual trigger | Same workflow already in flight | Wait, or check `GET /{id}/runs` for the running record |
| Workflow enabled but never fires | Server not running (scheduler lives in the FastAPI lifespan), or `last_run` more recent than the interval | Check server logs for "workflow scheduler started" |
| Agent "can't find" expected files | Wrong mount | Verify `WORKFLOW_TARGET_DIR` in `.env` and that it resolves on the *host* |

---

## Choosing a mode

| You want to… | Use |
|---|---|
| Answer a user's message in the UI | **Mode 1** `chat_once` / `stream_chat` |
| Pull typed fields out of text | **Mode 1** `extract_structured` |
| Let the model call *your* functions (DB lookup, API call) | **Mode 1** `chat_with_tools` |
| Review/audit a whole repository | **Mode 2** |
| Run a slash-command skill (`/review`, `/security-review`) | **Mode 2** (slash commands are a CLI concept) |
| Anything periodic/unattended against code | **Mode 2** via a workflow |
| Long multi-step task with file access, triggered by a user action | **Mode 2** — call `wf.start_run()` (or `run_headless` directly) from your route |

Rule of thumb: **Mode 1 when your code knows the steps; Mode 2 when
the model must discover them by exploring a filesystem.**

The modes compose. Two patterns that fall out naturally:

- **Headless produces → API refines.** A workflow writes a long
  `/review` transcript; a route then calls
  `extract_structured(stdout, schema)` to turn it into typed findings
  for a dashboard.
- **Chat triggers agent.** A Mode 1 tool (via `chat_with_tools`) whose
  handler calls `start_run()` — the chat assistant can launch a repo
  review and report the run id.

---

## Configuration reference

| Env var | Default | Consumed by | Notes |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | — (required) | **Both modes** | SDK reads it natively; `headless.py` forwards the env to the CLI |
| `AI_MODEL` | `claude-opus-4-8` | Mode 1 (`settings.ai_model`) | Per-call override on every helper; per-workflow `model` field for Mode 2 |
| `CLAUDE_BIN` | `claude` | Mode 2 | Path to the Claude Code CLI |
| `WORKFLOW_WORKDIR` | `/repo` | Mode 2 | cwd for headless runs (inside the container) |
| `WORKFLOW_TARGET_DIR` | `.` | docker-compose | Host path mounted at `/repo` |
| `BACKEND_PORT` / `FRONTEND_PORT` | 8000 / 5173 | compose | — |

State files (gitignored, host-persisted through the `./backend:/code`
bind mount):

| File | Contents |
|---|---|
| `backend/data/workflows.json` | Workflow definitions + `last_run` stamps |
| `backend/data/runs.jsonl` | Append-only run history (one JSON object per line) |

## Security notes

- **One secret, two consumers.** `ANTHROPIC_API_KEY` is the only
  credential; it never reaches the frontend, which only ever sees
  `/api/*` JSON/SSE.
- **Mode 2 is the powerful one — scope it.** The agent inherits the
  container's view: the mounted `/repo` and the container filesystem.
  Mount only the repo you mean to expose; grant write capability
  per-workflow, never globally; keep permission-bypass flags out of
  `extra_args` for unattended runs.
- **The workflow API is unauthenticated** (like everything in this
  barebone). Before exposing the backend beyond localhost, put auth in
  front of `/api/workflows` first — it's the endpoint that runs an
  agent against your code.
- **Run records contain repo content** (review excerpts, file paths).
  `backend/data/` is gitignored for that reason; treat it like a log
  directory.
