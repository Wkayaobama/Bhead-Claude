# Cheat Sheet — __app_name__

One page. Deep dives live in [`llm-modes.md`](llm-modes.md).

## Run

```bash
cp .env.example .env                  # set ANTHROPIC_API_KEY
docker compose up --build             # backend :8000 (+ frontend :5173 if present)

# bare-metal backend (no Docker)
cd backend && pip install -r requirements.txt
ANTHROPIC_API_KEY=sk-ant-... uvicorn app.main:app --reload
```

| URL | What |
|---|---|
| `http://localhost:8000/api/docs` | Interactive API docs (Swagger) |
| `http://localhost:8000/api/health` | Liveness |
| `http://localhost:5173` | Chat UI (full-stack scaffold only) |

## Environment

| Var | Default | Used by |
|---|---|---|
| `ANTHROPIC_API_KEY` | — required | both modes (SDK + CLI) |
| `AI_MODEL` | `claude-opus-4-8` | Mode 1 default model |
| `WORKFLOW_TARGET_DIR` | `.` | host repo mounted at `/repo` for headless runs |
| `CLAUDE_BIN` | `claude` | path to the Claude Code CLI |
| `WORKFLOW_WORKDIR` | `/repo` | cwd of headless runs (in-container) |
| `BACKEND_PORT` / `FRONTEND_PORT` | 8000 / 5173 | compose |

## Mode 1 — in-process API (`from app.llm import ...`)

```python
text  = await chat_once(user_message="hi", system_prompt=None, history=None,
                        model=None, max_tokens=16000)

async for chunk in stream_chat(user_message="hi", ...):   # max_tokens=64000
    ...                                                    # SSE bridge: routes/chat.py

text  = await chat_with_tools(user_message=..., tools=[...],
                              tool_handler=my_async_fn,    # (name, input) -> str|dict
                              max_rounds=5)

data  = await extract_structured(user_message=..., schema={...})
        # schema: every object needs "additionalProperties": False
```

Rules: only `llm.py` imports `anthropic` · model override is per-call ·
history is `[{"role": "user"|"assistant", "content": "..."}]`, you persist it.

## Mode 2 — headless workflows (`claude -p` against `/repo`)

```bash
# list (ids!)            create                       edit / enable
curl -s :8000/api/workflows
curl -s -X POST :8000/api/workflows -H 'Content-Type: application/json' \
  -d '{"name":"Sec review","prompt":"/security-review","interval_minutes":10080}'
curl -s -X PATCH :8000/api/workflows/$ID -H 'Content-Type: application/json' \
  -d '{"enabled":true}'

# run now (202; 409 if already running)      results (newest first)
curl -s -X POST :8000/api/workflows/$ID/run
curl -s :8000/api/workflows/$ID/runs         # or /api/workflows/runs for all

# delete
curl -s -X DELETE :8000/api/workflows/$ID
```

Workflow fields:

```jsonc
{
  "name": "Code review",
  "prompt": "/review",            // slash command OR free-form text
  "interval_minutes": 1440,       // cadence, measured from run START
  "enabled": false,               // seeds start disabled
  "model": null,                  // optional --model override
  "allowed_tools": null,          // e.g. ["Edit", "Bash(git diff:*)"]
  "extra_args": null              // e.g. ["--permission-mode", "acceptEdits"]
}
```

Run record: `status` (`running`→`completed`/`failed`) · `exit_code` ·
`stdout` (the result, ≤200 KB) · `stderr` · `duration_s`.

Prompt ideas: `/review` · `/security-review` ·
`"List every TODO/FIXME added this week with file:line"` ·
`"Summarize what changed between main and HEAD for a release note"`.

Permissions: read-only prompts work as-is; anything that edits files or
runs state-changing commands needs `allowed_tools` / `extra_args` on
that workflow. Never grant bypass flags to unattended runs.

## Files & state

| Path | What |
|---|---|
| `backend/app/llm.py` | seam #1 — only module importing `anthropic` |
| `backend/app/headless.py` | seam #2 — only spawner of `claude` |
| `backend/app/workflows.py` | registry + runner + scheduler (poll 30 s) |
| `backend/app/routes/` | HTTP layer; add features here |
| `backend/data/workflows.json` | workflow definitions (gitignored) |
| `backend/data/runs.jsonl` | run history, append-only (gitignored) |
| `docs/llm-modes.md` | the two loading modes, in depth |
| `Dockerfile` (root) | production/Cloud Run image (UI built + served by FastAPI) |
| `deploy/cloudrun.sh` + `docs/deploy-cloudrun.md` | Google Cloud Run deployment |

## Troubleshoot in one line

| Symptom | First move |
|---|---|
| 401 / AuthenticationError | `ANTHROPIC_API_KEY` in `.env`, then restart compose |
| run failed: `'claude'` not found | rebuild backend image (`docker compose up --build backend`) |
| run failed: dubious ownership | rebuild image (Dockerfile sets git `safe.directory`) |
| `exit_code: -1` timed out | raise `timeout` in `headless.py` or narrow the prompt |
| enabled but never fires | server up? logs say "workflow scheduler started"? |
| 409 on manual run | same workflow still in flight — poll `/runs` |
| agent sees wrong files | check `WORKFLOW_TARGET_DIR` resolves on the **host** |
