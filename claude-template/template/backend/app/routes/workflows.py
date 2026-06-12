"""Workflow API — manage and trigger headless Claude Code runs.

  GET    /api/workflows              list definitions
  POST   /api/workflows              create one
  PATCH  /api/workflows/{id}         edit (enable, change prompt/cadence, ...)
  DELETE /api/workflows/{id}         remove
  POST   /api/workflows/{id}/run     trigger now → 202 + run record
  GET    /api/workflows/{id}/runs    run history (newest first)
  GET    /api/workflows/runs         run history across all workflows

A workflow's `prompt` is anything `claude -p` accepts: a slash command
("/review", "/security-review") or free-form text.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import workflows as wf

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowIn(BaseModel):
    name: str
    prompt: str = Field(examples=["/review", "/security-review"])
    interval_minutes: int = 1440
    enabled: bool = True
    model: Optional[str] = None
    # Capability grants for non-read-only workflows, e.g.
    # allowed_tools=["Edit", "Bash(git diff:*)"] or
    # extra_args=["--permission-mode", "acceptEdits"].
    allowed_tools: Optional[list[str]] = None
    extra_args: Optional[list[str]] = None


class WorkflowPatch(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    interval_minutes: Optional[int] = None
    enabled: Optional[bool] = None
    model: Optional[str] = None
    allowed_tools: Optional[list[str]] = None
    extra_args: Optional[list[str]] = None


@router.get("")
async def list_workflows():
    return wf.load_workflows()


@router.post("", status_code=201)
async def create_workflow(body: WorkflowIn):
    return wf.create_workflow(body.model_dump())


@router.get("/runs")
async def all_runs(limit: int = 50):
    return wf.list_runs(limit=limit)


@router.patch("/{workflow_id}")
async def patch_workflow(workflow_id: str, body: WorkflowPatch):
    updated = wf.update_workflow(
        workflow_id, body.model_dump(exclude_unset=True)
    )
    if not updated:
        raise HTTPException(404, "workflow not found")
    return updated


@router.delete("/{workflow_id}", status_code=204)
async def remove_workflow(workflow_id: str):
    if not wf.delete_workflow(workflow_id):
        raise HTTPException(404, "workflow not found")


@router.post("/{workflow_id}/run", status_code=202)
async def trigger_run(workflow_id: str):
    # Accepts the workflow id OR its exact (URL-encoded) name — names
    # are the stable handle for external schedulers like Cloud Scheduler.
    workflow = wf.find_workflow(workflow_id)
    if not workflow:
        raise HTTPException(404, "workflow not found")
    run = wf.start_run(workflow)
    if run is None:
        raise HTTPException(409, "a run for this workflow is already in progress")
    return run


@router.get("/{workflow_id}/runs")
async def workflow_runs(workflow_id: str, limit: int = 50):
    workflow = wf.find_workflow(workflow_id)
    if not workflow:
        raise HTTPException(404, "workflow not found")
    return wf.list_runs(workflow_id=workflow["id"], limit=limit)
