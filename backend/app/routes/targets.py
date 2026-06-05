"""CRUD routes for scrape targets (job board URLs to monitor)."""
from datetime import datetime
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/targets", tags=["targets"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ScrapeTargetCreate(BaseModel):
    url: str
    name: str
    description: Optional[str] = ""
    active: bool = True


class ScrapeTargetUpdate(BaseModel):
    url: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    if doc.get("created_at"):
        doc["created_at"] = doc["created_at"].isoformat()
    if doc.get("last_scraped_at"):
        doc["last_scraped_at"] = doc["last_scraped_at"].isoformat()
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


@router.post("", status_code=201)
async def create_target(body: ScrapeTargetCreate, request: Request):
    db = request.app.state.db
    # Prevent duplicate URLs
    existing = await db.scrape_targets.find_one({"url": body.url})
    if existing:
        raise HTTPException(409, detail="A target with this URL already exists.")
    doc = {
        **body.model_dump(),
        "created_at": datetime.utcnow(),
        "last_scraped_at": None,
        "scrape_count": 0,
        "job_count": 0,
        "status": "idle",
        "last_error": None,
    }
    result = await db.scrape_targets.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    doc["created_at"] = doc["created_at"].isoformat()
    return doc


@router.put("/{target_id}")
async def update_target(target_id: str, body: ScrapeTargetUpdate, request: Request):
    db = request.app.state.db
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(400, detail="No fields to update.")
    try:
        oid = ObjectId(target_id)
    except Exception:
        raise HTTPException(400, detail="Invalid target ID.")
    result = await db.scrape_targets.find_one_and_update(
        {"_id": oid},
        {"$set": update_data},
        return_document=True,
    )
    if not result:
        raise HTTPException(404, detail="Target not found.")
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
    # Also remove its job postings
    await db.job_postings.delete_many({"target_id": target_id})
