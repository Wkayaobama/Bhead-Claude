# HR Scout — system maps

Three views of the same system, kept next to the code so a change that moves
a boundary also moves a line here. Diagram 1 is the mental model (what the
pieces are and how they depend on each other), diagram 2 the logical flow
(who calls what, in which order), diagram 3 the data (collections, edges and
the quality matrix that sits orthogonal to them). A list of known drift —
things the maps show honestly but the code does not yet fix — closes the file.

Every fence renders with stock Mermaid (dagre layout) — GitHub's Markdown
preview shows them as-is. To re-check after an edit without pushing, run the
`render_check.mjs` script bundled with the `standalone-refactor` skill against
this file (`node render_check.mjs docs/SYSTEM_MAPS.md`); it needs
`playwright-core` and `mermaid` installed in the directory you run it from.

---

## Diagram 1 — unified mental model

What the standalone app is made of, and what was cut away from the generated
version. Read clockwise from the top: runtime → configuration → the one AI
seam → the quality engine → the two pipelines that feed it → the operator
surface, then the branch of host pieces that no longer exist.

```mermaid
mindmap
  root((HR Scout standalone))
    Runtime
      docker compose: frontend, backend, mongo
      Vite dev server proxies /api same origin
      FastAPI lifespan: Mongo client, indexes, scheduler task
    Configuration as a class
      Settings fields with defaults
      env tuple .env then ../.env, extra ignored
      compose environment allowlist mirrors Settings
      Guardrails
        no key: get_client fails loudly
        empty SECRETS_ENCRYPTION_KEY: vault 503
        empty CORS_ORIGINS: no wildcard middleware
        caps: page chars, max tokens, tick seconds
    AI seam llm.py
      direct Anthropic API, one shared AsyncAnthropic
      extract_structured via output_config format
      stream_chat for SSE
      refusal and max_tokens become errors
      server-side refusal fallback beta, switchable
      health describes model, effort, configured
    Quality engine
      extractor: one normalisation of scored fields
      registry: rules, bands, threshold as data
      engine: pure evaluate, describe, validate
      validate_registry runs at import
      payload carries bands and threshold to the UI
    Pipelines
      HTML fetch to text to extract_structured
      Apify actor items to text to extract_structured
      scheduler ticks, claims due targets, fires HTML scrape
      interview coach: document text plus job to stream_chat
    Operator surface
      Job feed, URL manager, agent config
      Sessions log per run with model used
      Monitor: KPIs, timeline, quality, audit log
      Secrets vault keyed by SECRETS_ENCRYPTION_KEY
    Removed host coupling
      LLM proxy and per-app key
      usage metering callbacks
      whitelabel identity prelude
      badge, logo, favicon, error reporter
      request analytics and error ring buffer
      preview domain allowlist
      bundled template scaffold
```

---

## Diagram 2 — logical map

Routes, the two Claude call sites, the background loop and the external
systems. Everything the browser does goes through the Vite proxy to `/api`;
every model call goes through `app/llm.py`; every persisted record lands in
the app's own MongoDB.

```mermaid
flowchart LR
  subgraph Browser["Browser — React pages"]
    Feed["Job Feed"]
    Targets["URL Manager"]
    Agent["Agent Config"]
    Sessions["Sessions"]
    Docs["Documents + coach chat"]
    Monitor["Monitor dashboard"]
    Secrets["Secrets vault"]
  end

  Vite["Vite dev server<br/>proxy /api → backend:8000"]
  Browser --> Vite

  subgraph API["FastAPI — app/routes"]
    R_jobs["/api/jobs"]
    R_targets["/api/targets"]
    R_agent["/api/agent-config"]
    R_sessions["/api/sessions"]
    R_docs["/api/documents<br/>upload, list, download, chat"]
    R_scraper["/api/scraper<br/>run, run-apify, run-all"]
    R_monitor["/api/monitor<br/>overview, timeline, quality-config,<br/>hallucinations, analyze, audit"]
    R_secrets["/api/secrets"]
    R_health["/api/health"]
  end
  Vite --> API

  subgraph Core["Core modules"]
    Settings["config.Settings<br/>env tuple, allowlisted keys"]
    LLM["llm.py<br/>extract_structured · stream_chat<br/>refusal / truncation guards"]
    Quality["quality/<br/>extractor → registry → engine"]
    Sched["scheduler_loop<br/>tick, claim due targets"]
    Categories["categories.CATEGORIES"]
  end

  R_scraper -->|"page text + schema"| LLM
  R_docs -->|"job + document → SSE"| LLM
  R_monitor -->|"evaluate · describe"| Quality
  R_jobs --> Categories
  R_scraper --> Categories
  Sched -->|"_do_scrape(triggered_by=cron)"| R_scraper
  R_secrets -->|"SECRETS_ENCRYPTION_KEY"| Settings
  R_health -->|"llm.describe · quality meta · caps"| Settings
  LLM --> Settings

  subgraph External["External systems"]
    Anthropic["Anthropic API<br/>api.anthropic.com"]
    Apify["Apify actor<br/>jobup scraper"]
    Boards["Job board pages<br/>HTTP fetch"]
  end
  LLM -->|"ANTHROPIC_API_KEY"| Anthropic
  R_scraper -->|"APIFY_API_KEY or body token"| Apify
  R_scraper --> Boards

  Mongo[("MongoDB<br/>scrape_targets · job_postings · agent_sessions<br/>documents · agent_config · secrets")]
  API --> Mongo
  Sched --> Mongo
```

---

## Diagram 3 — schema map

Collections and the string-ID edges between them. The quality fields on
`job_postings` are written by `/api/monitor/analyze` from the registry; the
matrix after the diagram is the orthogonal view — which rule reads which
field — and is generated from the same registry the API serves.

```mermaid
erDiagram
  SCRAPE_TARGETS ||--o{ JOB_POSTINGS : "target_id (string)"
  SCRAPE_TARGETS ||--o{ AGENT_SESSIONS : "target_id (string)"
  JOB_POSTINGS ||--o{ DOCUMENTS : "job_id (string)"
  AGENT_CONFIG ||..o{ AGENT_SESSIONS : "prompt_used snapshot"

  SCRAPE_TARGETS {
    ObjectId _id
    string url "unique index"
    string name
    string description
    string goal "target-specific prompt suffix"
    bool active
    bool cron_enabled
    int cron_interval_minutes
    datetime cron_next_run
    string status "idle running completed error"
    string last_error
    int scrape_count
    int job_count
    datetime created_at
    datetime last_scraped_at
  }

  JOB_POSTINGS {
    ObjectId _id
    string target_id
    string target_name
    string target_url
    string title "required by schema"
    string company
    string location
    string description "max 300 chars"
    string url
    string salary_range
    string posted_at
    string category "one of CATEGORIES"
    array tags "max 5"
    datetime scraped_at
    int confidence_score "0..100 from engine"
    array quality_flags "issue labels"
    array quality_rules_fired "rule keys"
    string quality_band "clean review flagged"
    bool flagged "score below threshold"
    datetime analyzed_at
  }

  AGENT_SESSIONS {
    ObjectId _id
    string target_id
    string target_name
    string target_url
    datetime started_at
    datetime completed_at
    string status "running completed error"
    string prompt_used
    array domain_focus
    string target_goal
    int jobs_found
    int new_jobs
    string error
    string triggered_by "manual cron"
    string scrape_mode "html apify"
    string model "settings.ai_model at run time"
  }

  DOCUMENTS {
    ObjectId _id
    string job_id
    string job_title
    string job_company
    string filename
    string content_type
    binary file_data "max 10 MB"
    int size
    string notes
    datetime uploaded_at
  }

  AGENT_CONFIG {
    string _id "default singleton"
    string system_prompt
    array domain_focus
    string goal "not yet used by the prompt"
    datetime created_at
    datetime updated_at
  }

  SECRETS {
    ObjectId _id
    string variable_name "unique upper-cased"
    string encrypted_value "Fernet token"
    string created_at "ISO string"
    string updated_at "ISO string"
  }
```

### Quality matrix — rules × scored fields

Generated from `app/quality/registry.py` (the same data `/api/monitor/quality-config`
returns). A `●` means the rule reads that field; the penalty is subtracted
from 100 when the rule fires; a final score below **70** is flagged.
Bands: clean 90–100 · review 70–89 · flagged 0–69.

| rule | penalty | title | description | company | salary_range | predicate |
|---|---:|:-:|:-:|:-:|:-:|---|
| `title_too_short` | 40 | ● | | | | len < 3 |
| `title_too_long` | 15 | ● | | | | len > 200 |
| `url_in_title` | 20 | ● | | | | regex `https?://` |
| `title_repeated_words` | 10 | ● | | | | > 4 words and unique ratio < 0.65 |
| `html_artifacts` | 20 | ● | ● | ● | | regex tag or entity, first field named |
| `template_tokens` | 30 | ● | ● | | | regex `{{ }}` `[[ ]]` `<% %>` |
| `control_chars` | 25 | ● | ● | | | regex control bytes |
| `company_missing` | 10 | | | ● | | empty |
| `description_too_brief` | 10 | | ● | | | non-empty and len < 15 |
| `salary_no_digits` | 5 | | | | ● | non-empty and no digit |

---

## Known drift

Behaviour the maps describe as it is, not as it should be. None of these were
introduced by the standalone translation; they are the generated app's open
items, listed so the next pass starts from facts.

- **No authentication anywhere.** Every route is open to whoever reaches
  port 8000: scrape triggers spend Anthropic and Apify budget, deletes are
  unconfirmed, and `GET /api/secrets/{name}/value` returns plaintext. Put the
  API behind a reverse proxy with auth before exposing it beyond localhost.
- **Targets can stick in `running`.** A crash or `--reload` mid-scrape leaves
  the target and its session `running`; the scheduler skips it and manual
  triggers return 409. No route resets `status`.
- **Scheduler claims are not atomic.** `scheduler_loop` finds due targets,
  then updates each; with more than one backend process the same target can
  be scraped twice. Tasks are fire-and-forget (`asyncio.create_task` without a
  reference).
- **Naive UTC datetimes.** `datetime.utcnow()` values are serialised without an
  offset, so browsers read them as local time and relative times drift by the
  viewer's UTC offset. (`utcnow` is also deprecated on Python 3.12.)
- **Deletes do not cascade.** Deleting a target removes its postings only;
  documents (with file bytes) and sessions stay behind.
- **SSE parser in `DocumentsPage` splits on `\n` per chunk** without buffering a
  frame split across reads, so a token can be dropped under slow networks.
- **`cron_interval_minutes` is not validated**; 0 or a negative value fires on
  every tick.
- **Raw filename in `Content-Disposition`** on document download; a non-latin-1
  name produces a 500.
- **Apify token travels as a URL query parameter** (the actor API's shape); it
  will appear in any proxy log.
- **MongoDB runs without auth** and relies on compose not publishing its port.
- **`agent_config.goal` never reaches the prompt**; only `domain_focus` and the
  per-target `goal` do.
- **Dev-mode containers only.** `uvicorn --reload` and `npm run dev`; there is
  no production image or static build served by the backend.
- **Unused surface:** the text index on `job_postings`, `DELETE /api/jobs/{id}`,
  the sessions filter parameters, and `POST /api/admin/revoke-keys` (clears
  collections nothing writes to).
- **`LICENSE` is still the generator's placeholder.** Choosing a license is the
  owner's decision; the file was left untouched.
