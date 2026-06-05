"""CRUD routes for scrape targets (job board URLs to monitor)."""
from datetime import datetime, timedelta
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/targets", tags=["targets"])

CRON_INTERVALS = {
    30: "Every 30 minutes",
    60: "Every hour",
    360: "Every 6 hours",
    720: "Every 12 hours",
    1440: "Daily",
    2880: "Every 2 days",
    10080: "Weekly",
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ScrapeTargetCreate(BaseModel):
    url: str
    name: str
    description: Optional[str] = ""
    active: bool = True
    goal: Optional[str] = ""
    cron_enabled: bool = False
    cron_interval_minutes: int = 1440


class ScrapeTargetUpdate(BaseModel):
    url: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None
    goal: Optional[str] = None
    cron_enabled: Optional[bool] = None
    cron_interval_minutes: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    for field in ("created_at", "last_scraped_at", "cron_next_run"):
        if doc.get(field):
            doc[field] = doc[field].isoformat()
    return doc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
async def list_targets(request: Request):
    db = request.app.state.db
    targets = []
    async for doc in db.scrape_targets.find().sort("created_at", -1):
        targets.append(_serialize(doc))
    return targets


@router.get("/cron-intervals")
async def get_cron_intervals():
    return [{"minutes": k, "label": v} for k, v in CRON_INTERVALS.items()]


@router.post("", status_code=201)
async def create_target(body: ScrapeTargetCreate, request: Request):
    db = request.app.state.db
    existing = await db.scrape_targets.find_one({"url": body.url})
    if existing:
        raise HTTPException(409, detail="A target with this URL already exists.")

    now = datetime.utcnow()
    cron_next_run = (
        now + timedelta(minutes=body.cron_interval_minutes)
        if body.cron_enabled
        else None
    )

    doc = {
        **body.model_dump(),
        "created_at": now,
        "last_scraped_at": None,
        "scrape_count": 0,
        "job_count": 0,
        "status": "idle",
        "last_error": None,
        "cron_next_run": cron_next_run,
    }
    result = await db.scrape_targets.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    doc["created_at"] = doc["created_at"].isoformat()
    if doc.get("cron_next_run"):
        doc["cron_next_run"] = doc["cron_next_run"].isoformat()
    return doc


@router.put("/{target_id}")
async def update_target(target_id: str, body: ScrapeTargetUpdate, request: Request):
    db = request.app.state.db
    # Use exclude_unset so False / 0 / "" are included when explicitly sent
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(400, detail="No fields to update.")
    try:
        oid = ObjectId(target_id)
    except Exception:
        raise HTTPException(400, detail="Invalid target ID.")

    # Recalculate next cron run if schedule changed
    current = await db.scrape_targets.find_one({"_id": oid})
    if not current:
        raise HTTPException(404, detail="Target not found.")

    cron_enabled = update_data.get("cron_enabled", current.get("cron_enabled", False))
    interval = update_data.get(
        "cron_interval_minutes", current.get("cron_interval_minutes", 1440)
    )
    if "cron_enabled" in update_data or "cron_interval_minutes" in update_data:
        update_data["cron_next_run"] = (
            datetime.utcnow() + timedelta(minutes=interval) if cron_enabled else None
        )

    result = await db.scrape_targets.find_one_and_update(
        {"_id": oid},
        {"$set": update_data},
        return_document=True,
    )
    return _serialize(result)


@router.delete("/{target_id}", status_code=204)
async def delete_target(target_id: str, request: Request):
    db = request.app.state.db
    try:
        oid = ObjectId(target_id)
    except Exception:
        raise HTTPException(400, detail="Invalid target ID.")
    result = await db.scrape_targets.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(404, detail="Target not found.")
    await db.job_postings.delete_many({"target_id": target_id})
