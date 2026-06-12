#!/usr/bin/env bash
# Deploy __app_name__ to Google Cloud Run from source.
# Full guide (prerequisites, scheduling options, hardening):
#   docs/deploy-cloudrun.md
#
# Required env:  GCP_PROJECT
# Optional env:  GCP_REGION (default europe-west1), SERVICE_NAME,
#                MIN_INSTANCES (default 1), AI_MODEL,
#                WORKFLOW_REPO_URL (repo headless runs clone — required
#                on Cloud Run if you use workflows)
set -euo pipefail

PROJECT="${GCP_PROJECT:?set GCP_PROJECT to your GCP project id}"
REGION="${GCP_REGION:-europe-west1}"
SERVICE="${SERVICE_NAME:-__app_name__}"

# --- One-time setup (idempotent) -------------------------------------
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com --project "$PROJECT"

if ! gcloud secrets describe anthropic-api-key --project "$PROJECT" >/dev/null 2>&1; then
  echo "Creating secret 'anthropic-api-key' — paste the key, then Enter + Ctrl-D:"
  gcloud secrets create anthropic-api-key --project "$PROJECT" \
    --replication-policy automatic --data-file=-
fi

# --- Deploy -----------------------------------------------------------
# Flag rationale (details in docs/deploy-cloudrun.md):
#   --no-cpu-throttling  headless runs continue AFTER the 202 response;
#                        throttled CPU would freeze them mid-run
#   --min-instances 1    keeps the in-process scheduler alive; set 0 if
#                        you switch to Cloud Scheduler triggering
#   --timeout 3600       manual /run calls return in ms, but give slow
#                        chat/SSE requests headroom
gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 3600 \
  --no-cpu-throttling \
  --min-instances "${MIN_INSTANCES:-1}" \
  --max-instances 2 \
  --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest" \
  --set-env-vars "AI_MODEL=${AI_MODEL:-claude-opus-4-8},WORKFLOW_REPO_URL=${WORKFLOW_REPO_URL:-}"

echo
echo "Deployed. Service URL:"
gcloud run services describe "$SERVICE" --project "$PROJECT" \
  --region "$REGION" --format 'value(status.url)'
