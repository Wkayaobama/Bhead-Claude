"""Routes for browsing and managing scraped job postings."""
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

CATEGORIES = [
    "Engineering",
    "Marketing",
    "Sales",
    "HR",
    "Finance",
    "Design",
    "Operations",
    "Product",
    "Legal",
    "Other",
]


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    if doc.get("scraped_at"):
        doc["scraped_at"] = doc["scraped_at"].isoformat()
    return doc


@router.get("")
async def list_jobs(
    request: Request,
    category: Optional[str] = Query(None),
    target_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    db = request.app.state.db
    query: dict = {}
    if category and category != "All":
        query["category"] = category
    if target_id:
        query["target_id"] = target_id
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"company": {"$regex": search, "$options": "i"}},
            {"location": {"$regex": search, "$options": "i"}},
        ]

    total = await db.job_postings.count_documents(query)
    jobs = []
    async for doc in (
        db.job_postings.find(query).sort("scraped_at", -1).skip(skip).limit(limit)
    ):
        jobs.append(_serialize(doc))

    return {"jobs": jobs, "total": total, "skip": skip, "limit": limit}


@router.get("/stats")
async def get_stats(request: Request):
    db = request.app.state.db
    total_jobs = await db.job_postings.count_documents({})
    total_targets = await db.scrape_targets.count_documents({})
    active_targets = await db.scrape_targets.count_documents({"active": True})

    # Category breakdown
    pipeline = [
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    categories = []
    async for doc in db.job_postings.aggregate(pipeline):
        if doc["_id"]:
            categories.append({"category": doc["_id"], "count": doc["count"]})

    return {
        "total_jobs": total_jobs,
        "total_targets": total_targets,
        "active_targets": active_targets,
        "categories": categories,
        "available_categories": CATEGORIES,
    }


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str, request: Request):
    db = request.app.state.db
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(400, detail="Invalid job ID.")
    await db.job_postings.delete_one({"_id": oid})
