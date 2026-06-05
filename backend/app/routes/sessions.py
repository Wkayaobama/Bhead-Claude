"""Agent session log — one document per scrape run.

Each document records what happened: prompt used, jobs found, errors,
and which trigger fired the run (manual vs cron).
"""
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    for field in ("started_at", "completed_at"):
        if doc.get(field):
            doc[field] = doc[field].isoformat()
    return doc


@router.get("")
async def list_sessions(
    request: Request,
    target_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    triggered_by: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    db = request.app.state.db
    query: dict = {}
    if target_id:
        query["target_id"] = target_id
    if status:
        query["status"] = status
    if triggered_by:
        query["triggered_by"] = triggered_by

    total = await db.agent_sessions.count_documents(query)
    sessions = []
    async for doc in (
        db.agent_sessions.find(query).sort("started_at", -1).skip(skip).limit(limit)
    ):
        sessions.append(_serialize(doc))

    return {"sessions": sessions, "total": total}


@router.get("/stats")
async def session_stats(request: Request):
    db = request.app.state.db
    total = await db.agent_sessions.count_documents({})
    completed = await db.agent_sessions.count_documents({"status": "completed"})
    errors = await db.agent_sessions.count_documents({"status": "error"})
    cron_runs = await db.agent_sessions.count_documents({"triggered_by": "cron"})
    manual_runs = await db.agent_sessions.count_documents({"triggered_by": "manual"})

    # Total new jobs discovered across all sessions
    pipeline = [{"$group": {"_id": None, "total_new": {"$sum": "$new_jobs"}}}]
    agg = await db.agent_sessions.aggregate(pipeline).to_list(1)
    total_new_jobs = agg[0]["total_new"] if agg else 0

    return {
        "total": total,
        "completed": completed,
        "errors": errors,
        "cron_runs": cron_runs,
        "manual_runs": manual_runs,
        "total_new_jobs": total_new_jobs,
        "success_rate": round(completed / total * 100, 1) if total else 0,
    }


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request):
    db = request.app.state.db
    try:
        oid = ObjectId(session_id)
    except Exception:
        raise HTTPException(400, detail="Invalid session ID.")
    await db.agent_sessions.delete_one({"_id": oid})


@router.delete("", status_code=204)
async def clear_sessions(request: Request):
    """Delete all session logs."""
    db = request.app.state.db
    await db.agent_sessions.delete_many({})
