"""Workflow registry + interval scheduler for headless runs.

A *workflow* is a named, repeatable headless prompt: "/review every
24h", "/security-review weekly", or any free-form prompt on any
cadence. The registry is file-backed (data/workflows.json for
definitions, data/runs.jsonl for completed runs) so the template stays
database-free — swap these two functions' bodies for Mongo/Postgres
when persistence outgrows a file, and nothing above this module moves.

Layers (all in this file, top to bottom):
  registry  — load/save/CRUD on workflow definitions
  runner    — start_run() spawns one run as a background task
  scheduler — scheduler_loop() polls the registry and fires due runs
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.headless import run_headless

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WORKFLOWS_FILE = DATA_DIR / "workflows.json"
RUNS_FILE = DATA_DIR / "runs.jsonl"

_POLL_SECONDS = 30

# Workflow ids with a run in flight — guards against overlap from both
# the scheduler and manual triggers.
_active: set[str] = set()

# In-flight run records (completed ones live in RUNS_FILE).
_running: dict[str, dict] = {}

# Seeded on first boot so the API is self-documenting. Disabled by
# default — enable via PATCH /api/workflows/{id} when you're ready.
_SEED = [
    {"name": "Code review", "prompt": "/review", "interval_minutes": 1440},
    {"name": "Security review", "prompt": "/security-review", "interval_minutes": 10080},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _normalize(w: dict) -> dict:
    return {
        "id": w.get("id") or uuid.uuid4().hex[:12],
        "name": w["name"],
        "prompt": w["prompt"],
        "interval_minutes": int(w.get("interval_minutes", 1440)),
        "enabled": bool(w.get("enabled", False)),
        "model": w.get("model"),
        "allowed_tools": w.get("allowed_tools"),
        "extra_args": w.get("extra_args"),
        "last_run": w.get("last_run"),
    }


def load_workflows() -> list[dict]:
    if not WORKFLOWS_FILE.exists():
        workflows = [_normalize(w) for w in _SEED]
        save_workflows(workflows)
        return workflows
    return json.loads(WORKFLOWS_FILE.read_text())


def save_workflows(workflows: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WORKFLOWS_FILE.write_text(json.dumps(workflows, indent=2))


def get_workflow(workflow_id: str) -> Optional[dict]:
    return next((w for w in load_workflows() if w["id"] == workflow_id), None)


def find_workflow(key: str) -> Optional[dict]:
    """Look up by id, falling back to exact name. Names give external
    schedulers (e.g. Cloud Scheduler) a stable address: on ephemeral
    filesystems the seeded ids change when an instance is replaced,
    but the names don't."""
    return get_workflow(key) or next(
        (w for w in load_workflows() if w["name"] == key), None
    )


def create_workflow(fields: dict) -> dict:
    workflows = load_workflows()
    workflow = _normalize(fields)
    workflows.append(workflow)
    save_workflows(workflows)
    return workflow


def update_workflow(workflow_id: str, patch: dict) -> Optional[dict]:
    workflows = load_workflows()
    for i, w in enumerate(workflows):
        if w["id"] == workflow_id:
            workflows[i] = _normalize({**w, **patch, "id": workflow_id})
            save_workflows(workflows)
            return workflows[i]
    return None


def delete_workflow(workflow_id: str) -> bool:
    workflows = load_workflows()
    remaining = [w for w in workflows if w["id"] != workflow_id]
    if len(remaining) == len(workflows):
        return False
    save_workflows(remaining)
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def list_runs(workflow_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    runs: list[dict] = []
    if RUNS_FILE.exists():
        runs = [json.loads(line) for line in RUNS_FILE.read_text().splitlines() if line]
    runs.extend(_running.values())
    if workflow_id:
        runs = [r for r in runs if r["workflow_id"] == workflow_id]
    runs.sort(key=lambda r: r["started_at"], reverse=True)
    return runs[:limit]


def start_run(workflow: dict) -> Optional[dict]:
    """Kick off one run in the background. Returns the run record
    immediately (status="running") so callers can poll, or None if a
    run for this workflow is already in flight."""
    if workflow["id"] in _active:
        return None
    _active.add(workflow["id"])

    run = {
        "id": uuid.uuid4().hex[:12],
        "workflow_id": workflow["id"],
        "workflow_name": workflow["name"],
        "prompt": workflow["prompt"],
        "status": "running",
        "started_at": _now(),
    }
    _running[run["id"]] = run

    # Measure the interval from the start of the run, not the end, so a
    # long review doesn't drift the cadence.
    update_workflow(workflow["id"], {"last_run": run["started_at"]})

    asyncio.create_task(_execute(workflow, run))
    return run


async def _execute(workflow: dict, run: dict) -> None:
    try:
        result = await run_headless(
            workflow["prompt"],
            model=workflow.get("model"),
            allowed_tools=workflow.get("allowed_tools"),
            extra_args=workflow.get("extra_args"),
        )
        run.update(result)
        run["status"] = "completed" if result["exit_code"] == 0 else "failed"
    except Exception as exc:  # e.g. CLI binary missing
        log.exception("workflow %s run failed", workflow["id"])
        run.update(status="failed", exit_code=-1, stdout="", stderr=str(exc))
    finally:
        run["finished_at"] = _now()
        _active.discard(workflow["id"])
        _running.pop(run["id"], None)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with RUNS_FILE.open("a") as f:
            f.write(json.dumps(run) + "\n")


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def _is_due(workflow: dict) -> bool:
    if not workflow["last_run"]:
        return True
    last = datetime.fromisoformat(workflow["last_run"])
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed >= workflow["interval_minutes"] * 60


async def scheduler_loop() -> None:
    """Poll the registry and fire due workflows. Started from the
    FastAPI lifespan in main.py; cancelled on shutdown."""
    log.info("workflow scheduler started (poll every %ss)", _POLL_SECONDS)
    while True:
        try:
            for workflow in load_workflows():
                if workflow["enabled"] and _is_due(workflow):
                    if start_run(workflow):
                        log.info(
                            "scheduled run started: %s (%r)",
                            workflow["name"],
                            workflow["prompt"],
                        )
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(_POLL_SECONDS)
