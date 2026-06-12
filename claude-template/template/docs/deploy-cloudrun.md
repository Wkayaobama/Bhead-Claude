# Deploying __app_name__ to Google Cloud Run

The compose stack is a *dev shape*: three containers, bind mounts, a
hot-reloading Vite server. Cloud Run is a different shape — one
container per service, an injected `$PORT`, no bind mounts, an
ephemeral filesystem, and CPU that is throttled to ~0 between requests
unless you say otherwise. This guide covers how the template maps onto
that, and the two ways to keep workflows firing.

## What changes between local and Cloud Run

| Concern | Local (compose) | Cloud Run |
|---|---|---|
| Topology | 3 containers (backend, frontend, +your db) | **1 container**: root `Dockerfile` builds the Vite app and FastAPI serves it from `static/` |
| Port | fixed 8000/5173 | injected `$PORT` (the root Dockerfile CMD honors it) |
| Frontend dev server | Vite + proxy | none — production build, same origin, `/api/*` needs no proxy |
| `/repo` for headless runs | bind mount (`WORKFLOW_TARGET_DIR`) | **`WORKFLOW_REPO_URL`** — shallow clone on first run, fast-forward before every run |
| Secrets | `.env` file | Secret Manager → env var |
| `backend/data/` (workflows + run history) | persists on host | **ephemeral** — gone when the instance is replaced |
| Background CPU | always on | throttled after the response **unless `--no-cpu-throttling`** |
| In-process scheduler | always alive | only alive while an instance exists (**`--min-instances 1`**) |

## Deploy

```bash
# prerequisites: gcloud CLI authenticated, a GCP project with billing
export GCP_PROJECT=my-project
export WORKFLOW_REPO_URL=https://github.com/owner/repo.git   # if using workflows
./deploy/cloudrun.sh
```

The script is idempotent: it enables the APIs, creates the
`anthropic-api-key` secret on first run (prompts for the key), and
runs `gcloud run deploy --source .` — Cloud Build picks up the root
`Dockerfile` automatically. Re-run it to ship a new revision.

**Private target repos:** embed a read-only token in the URL —
`https://x-access-token:<token>@github.com/owner/repo.git` — and store
the *whole URL* as a secret rather than a plain env var:

```bash
printf '%s' "$WORKFLOW_REPO_URL" | gcloud secrets create workflow-repo-url --data-file=-
gcloud run services update __app_name__ --region $GCP_REGION \
  --set-secrets WORKFLOW_REPO_URL=workflow-repo-url:latest
```

## Keeping workflows firing — two options

### Option A — in-process scheduler (default, simplest)

What the deploy script configures. The template's asyncio scheduler
keeps running inside the service, exactly like local. Two flags make
it work, and both cost money — that's the trade for simplicity:

- `--min-instances 1`: Cloud Run normally scales to zero; a scheduler
  inside a dead instance fires nothing. One warm instance keeps it
  alive (~always-on billing for 1 vCPU/1 GiB).
- `--no-cpu-throttling`: a triggered run returns `202` immediately and
  the agent keeps working *after* the response. With default
  throttling, post-response CPU drops to near zero and the run stalls;
  this flag keeps CPU allocated for the instance's lifetime.

Caveat: definitions live in `backend/data/workflows.json`, which is
ephemeral. After an instance replacement, the two seeds come back
**disabled with new ids**. Re-enable via the API after deploy, or
script your definitions:

```bash
URL=$(gcloud run services describe __app_name__ --region $GCP_REGION --format 'value(status.url)')
curl -s -X POST $URL/api/workflows -H 'Content-Type: application/json' \
  -d '{"name":"Code review","prompt":"/review","interval_minutes":1440,"enabled":true}'
```

(Idempotence note: re-POSTing creates duplicates — check
`GET /api/workflows` first, or use Option B where definitions stay
disabled and cadence lives outside the instance.)

### Option B — Cloud Scheduler triggers (serverless-native)

Move the cadence *out* of the instance: leave every workflow
`enabled: false` (the in-process scheduler then never fires; it's
inert, not harmful) and let Cloud Scheduler POST the manual-trigger
endpoint on a real cron expression:

```bash
gcloud scheduler jobs create http nightly-review \
  --schedule "0 3 * * *" --time-zone "Europe/Zurich" \
  --uri "$URL/api/workflows/Code%20review/run" \
  --http-method POST \
  --attempt-deadline 30s
```

Note the address: **the workflow's name, URL-encoded** — the trigger
endpoint accepts id *or* exact name precisely because ids are minted
fresh on each new instance while names are stable.

Trade-offs vs Option A:
- `--min-instances 0` becomes possible — Cloud Scheduler's request
  wakes an instance. **Keep `--no-cpu-throttling`** so the run
  survives past the 202; also note that with min-instances 0 the
  instance may be reclaimed some minutes after going idle, so very
  long runs are safer with at least 1 warm instance.
- Real cron semantics ("03:00 Zurich time") instead of "every N
  minutes since last start".
- Run *history* is still ephemeral — read results promptly via
  `GET /api/workflows/<name>/runs`, or push them somewhere durable
  (see Persistence below).

## Locking it down (do this before real use)

The deploy script uses `--allow-unauthenticated` so your first
smoke-test is frictionless. The workflow API runs an agent against
your code — don't leave it open:

```bash
# require IAM auth on the service
gcloud run services update __app_name__ --region $GCP_REGION --no-allow-unauthenticated

# let Cloud Scheduler call it with an OIDC identity
gcloud iam service-accounts create scheduler-invoker
gcloud run services add-iam-policy-binding __app_name__ --region $GCP_REGION \
  --member "serviceAccount:scheduler-invoker@$GCP_PROJECT.iam.gserviceaccount.com" \
  --role roles/run.invoker
gcloud scheduler jobs update http nightly-review \
  --oidc-service-account-email "scheduler-invoker@$GCP_PROJECT.iam.gserviceaccount.com"
```

If humans need the chat UI too, put Identity-Aware Proxy or your own
auth middleware in front instead of going back to unauthenticated.

## Persistence (when ephemeral stops being acceptable)

Everything stateful sits behind two functions in `app/workflows.py` —
`load_workflows()` / `save_workflows()` — plus the `runs.jsonl` append
in `_execute()`. Swap those for Firestore (zero-ops, fits the
key-value shape) or Cloud SQL, and definitions + history survive
instance churn. Nothing above that module changes.

## Troubleshooting on Cloud Run

| Symptom | Cause / fix |
|---|---|
| Run stays `running` forever, no CPU activity | CPU throttling — redeploy with `--no-cpu-throttling` |
| Scheduled workflow never fires (Option A) | instance scaled to zero — `--min-instances 1` |
| Run fails: `clone of WORKFLOW_REPO_URL failed` | URL wrong, repo private without token, or egress blocked — check the run's `stderr` |
| 404 from Cloud Scheduler job | name in the URI not URL-encoded, or workflows file recreated — names are stable, use them |
| Container fails to start: port | something overrode `$PORT` handling — the root Dockerfile CMD must keep `--port ${PORT:-8080}` |
| Frontend 404s on `/` | image built from `--no-frontend` scaffold (API-only is expected), or `static/` missing from the image |
| Out-of-memory kills during runs | bump `--memory` (the CLI + a big repo wants 1–2 GiB) |

## Cost notes

Option A ≈ one always-on vCPU+1 GiB (min-instances 1, CPU always
allocated) plus Anthropic usage per run. Option B with min-instances 0
bills only while an instance is up (request time + the post-202 run
window + idle grace). Anthropic-side cost is driven by your workflow
cadence and repo size — start cadences slow, watch run `duration_s`
and the Anthropic console, then tighten.
