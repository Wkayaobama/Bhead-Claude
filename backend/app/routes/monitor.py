"""Monitoring, performance analytics, hallucination detection, and audit log.

Provides:
  GET  /api/monitor/overview       — KPI summary cards
  GET  /api/monitor/timeline       — jobs scraped per day (last 7 days)
  GET  /api/monitor/target-perf    — per-target performance metrics
  GET  /api/monitor/categories     — category distribution
  GET  /api/monitor/hallucinations — jobs flagged by quality analysis
  POST /api/monitor/analyze        — run/re-run quality checks on all jobs
  GET  /api/monitor/audit          — unified event log (sessions + errors + flags)
"""
import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


# ---------------------------------------------------------------------------
# Quality / hallucination heuristics
# ---------------------------------------------------------------------------

_HTML_RE = re.compile(r"<[a-zA-Z][^>]*>|&[a-zA-Z]{2,6};", re.IGNORECASE)
_TEMPLATE_RE = re.compile(r"\{\{.*?\}\}|\[\[.*?\]\]|<%.*?%>", re.DOTALL)
_URL_RE = re.compile(r"https?://\S+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _analyze_quality(job: dict) -> tuple[int, list[str]]:
    """Return (confidence_score 0–100, list_of_issue_strings).

    Rules are deterministic — no AI calls — so this runs cheap at scale.
    """
    score = 100
    issues: list[str] = []

    title = (job.get("title") or "").strip()
    desc = (job.get("description") or "").strip()
    company = (job.get("company") or "").strip()

    # ── Title checks ────────────────────────────────────────────────────────
    if len(title) < 3:
        issues.append("Title missing or too short")
        score -= 40
    elif len(title) > 200:
        issues.append("Title suspiciously long (>200 chars)")
        score -= 15

    if _URL_RE.search(title):
        issues.append("URL found inside job title")
        score -= 20

    # Repeated-word ratio in title
    words = title.lower().split()
    if len(words) > 4 and len(set(words)) / len(words) < 0.65:
        issues.append("Title contains heavily repeated words")
        score -= 10

    # ── HTML/template artifacts ──────────────────────────────────────────────
    for field_name, field_val in [("title", title), ("description", desc), ("company", company)]:
        if _HTML_RE.search(field_val):
            issues.append(f"HTML artefacts in {field_name}")
            score -= 20
            break

    for field_val in [title, desc]:
        if _TEMPLATE_RE.search(field_val):
            issues.append("Template/placeholder tokens detected")
            score -= 30
            break

    if _CONTROL_RE.search(title + desc):
        issues.append("Control/binary characters detected")
        score -= 25

    # ── Field-presence checks ────────────────────────────────────────────────
    if not company:
        issues.append("Company name absent")
        score -= 10

    if desc and len(desc) < 15:
        issues.append("Description too brief (<15 chars)")
        score -= 10

    # ── Salary sanity ────────────────────────────────────────────────────────
    salary = (job.get("salary_range") or "").strip()
    if salary and not re.search(r"\d", salary):
        issues.append("Salary range contains no numbers")
        score -= 5

    return max(0, score), issues


# ---------------------------------------------------------------------------
# Overview KPIs  (step 12)
# ---------------------------------------------------------------------------

@router.get("/overview")
async def get_overview(request: Request):
    db = request.app.state.db

    total_jobs = await db.job_postings.count_documents({})
    total_targets = await db.scrape_targets.count_documents({})
    active_targets = await db.scrape_targets.count_documents({"active": True})
    total_sessions = await db.agent_sessions.count_documents({})
    completed = await db.agent_sessions.count_documents({"status": "completed"})
    errors = await db.agent_sessions.count_documents({"status": "error"})
    total_docs = await db.documents.count_documents({})
    flagged_jobs = await db.job_postings.count_documents({"flagged": True})

    # Latest session timestamp
    last_session = None
    async for doc in db.agent_sessions.find().sort("started_at", -1).limit(1):
        if doc.get("started_at"):
            last_session = doc["started_at"].isoformat()

    # Total new jobs ever discovered
    agg = await db.agent_sessions.aggregate(
        [{"$group": {"_id": None, "total": {"$sum": "$new_jobs"}}}]
    ).to_list(1)
    total_new = agg[0]["total"] if agg else 0

    # Jobs analysed
    analysed = await db.job_postings.count_documents({"confidence_score": {"$exists": True}})

    return {
        "total_jobs": total_jobs,
        "total_targets": total_targets,
        "active_targets": active_targets,
        "total_sessions": total_sessions,
        "completed_sessions": completed,
        "error_sessions": errors,
        "success_rate": round(completed / total_sessions * 100, 1) if total_sessions else 0,
        "total_new_jobs_discovered": total_new,
        "flagged_jobs": flagged_jobs,
        "analysed_jobs": analysed,
        "total_documents": total_docs,
        "last_scan": last_session,
    }


# ---------------------------------------------------------------------------
# Timeline — jobs scraped per day (step 12)
# ---------------------------------------------------------------------------

@router.get("/timeline")
async def get_timeline(request: Request, days: int = Query(7, ge=1, le=30)):
    db = request.app.state.db
    since = datetime.utcnow() - timedelta(days=days)

    pipeline = [
        {"$match": {"scraped_at": {"$gte": since}}},
        {
            "$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%m-%d", "date": "$scraped_at"}
                },
                "count": {"$sum": 1},
                "new_jobs": {
                    "$sum": {
                        "$cond": [
                            {"$ifNull": ["$confidence_score", False]},
                            0,
                            1,
                        ]
                    }
                },
            }
        },
        {"$sort": {"_id": 1}},
    ]

    raw: dict[str, int] = {}
    async for row in db.job_postings.aggregate(pipeline):
        raw[row["_id"]] = row["count"]

    # Ensure every day in the range has an entry (even if 0)
    result = []
    for i in range(days):
        d = (since + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        result.append({
            "date": d,
            "label": datetime.strptime(d, "%Y-%m-%d").strftime("%a"),
            "count": raw.get(d, 0),
        })
    return result


# ---------------------------------------------------------------------------
# Category distribution (step 12)
# ---------------------------------------------------------------------------

@router.get("/categories")
async def get_categories(request: Request):
    db = request.app.state.db
    pipeline = [
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    result = []
    async for row in db.job_postings.aggregate(pipeline):
        result.append({"category": row["_id"] or "Other", "count": row["count"]})
    return result


# ---------------------------------------------------------------------------
# Per-target performance (step 12)
# ---------------------------------------------------------------------------

@router.get("/target-perf")
async def get_target_perf(request: Request):
    db = request.app.state.db
    pipeline = [
        {
            "$group": {
                "_id": "$target_id",
                "target_name": {"$first": "$target_name"},
                "target_url": {"$first": "$target_url"},
                "total_sessions": {"$sum": 1},
                "completed": {
                    "$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}
                },
                "errored": {
                    "$sum": {"$cond": [{"$eq": ["$status", "error"]}, 1, 0]}
                },
                "jobs_found": {"$sum": "$jobs_found"},
                "new_jobs": {"$sum": "$new_jobs"},
                "last_run": {"$max": "$started_at"},
            }
        },
        {"$sort": {"new_jobs": -1}},
        {"$limit": 15},
    ]
    result = []
    async for row in db.agent_sessions.aggregate(pipeline):
        success_rate = (
            round(row["completed"] / row["total_sessions"] * 100, 0)
            if row["total_sessions"]
            else 0
        )
        last_run = row["last_run"].isoformat() if row.get("last_run") else None
        result.append(
            {
                "target_id": row["_id"],
                "target_name": row.get("target_name") or row["_id"],
                "target_url": row.get("target_url", ""),
                "total_sessions": row["total_sessions"],
                "completed": row["completed"],
                "errored": row["errored"],
                "jobs_found": row["jobs_found"],
                "new_jobs": row["new_jobs"],
                "success_rate": success_rate,
                "last_run": last_run,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Hallucination detection (step 13)
# ---------------------------------------------------------------------------

@router.get("/hallucinations")
async def get_hallucinations(
    request: Request,
    max_score: int = Query(69, ge=0, le=100),
    limit: int = Query(50, ge=1, le=200),
):
    """Return jobs whose stored confidence_score is below max_score (default 69)."""
    db = request.app.state.db
    query = {"flagged": True}
    if max_score < 100:
        query = {
            "$or": [
                {"flagged": True},
                {"confidence_score": {"$lte": max_score}},
            ]
        }
    total = await db.job_postings.count_documents(query)
    jobs = []
    async for doc in (
        db.job_postings.find(query, {"file_data": 0})
        .sort("confidence_score", 1)
        .limit(limit)
    ):
        doc["id"] = str(doc.pop("_id"))
        if doc.get("scraped_at"):
            doc["scraped_at"] = doc["scraped_at"].isoformat()
        jobs.append(doc)
    return {"jobs": jobs, "total": total}


@router.post("/analyze")
async def run_analysis(request: Request):
    """Run deterministic quality checks on every job posting and persist results."""
    db = request.app.state.db
    total = 0
    flagged = 0
    async for job in db.job_postings.find({}):
        score, issues = _analyze_quality(job)
        is_flagged = score < 70
        await db.job_postings.update_one(
            {"_id": job["_id"]},
            {
                "$set": {
                    "confidence_score": score,
                    "quality_flags": issues,
                    "flagged": is_flagged,
                    "analyzed_at": datetime.utcnow(),
                }
            },
        )
        total += 1
        if is_flagged:
            flagged += 1
    return {
        "analyzed": total,
        "flagged": flagged,
        "clean": total - flagged,
        "flag_rate": round(flagged / total * 100, 1) if total else 0,
    }


# ---------------------------------------------------------------------------
# Audit log — unified event stream (step 14)
# ---------------------------------------------------------------------------

@router.get("/audit")
async def get_audit(
    request: Request,
    severity: Optional[str] = Query(None),
    limit: int = Query(80, ge=1, le=200),
):
    """Return a unified chronological event log from sessions + flagged jobs."""
    db = request.app.state.db
    events: list[dict] = []

    # ── Events from agent sessions ──────────────────────────────────────────
    async for s in db.agent_sessions.find().sort("started_at", -1).limit(limit):
        sid = str(s["_id"])
        ts_start = s["started_at"].isoformat() if s.get("started_at") else ""
        ts_end = s["completed_at"].isoformat() if s.get("completed_at") else None
        tby = s.get("triggered_by", "manual")
        tname = s.get("target_name", "unknown")

        events.append(
            {
                "id": f"{sid}_start",
                "timestamp": ts_start,
                "type": "scrape_start",
                "severity": "info",
                "target": tname,
                "message": f"Scan started for '{tname}' [{tby}]",
                "details": {
                    "triggered_by": tby,
                    "target_url": s.get("target_url", ""),
                    "domain_focus": s.get("domain_focus", []),
                },
            }
        )

        if ts_end:
            if s.get("status") == "completed":
                found = s.get("jobs_found", 0)
                new_j = s.get("new_jobs", 0)
                events.append(
                    {
                        "id": f"{sid}_ok",
                        "timestamp": ts_end,
                        "type": "scrape_complete",
                        "severity": "info",
                        "target": tname,
                        "message": (
                            f"Scan complete — {found} job{'s' if found != 1 else ''} found, "
                            f"{new_j} new"
                        ),
                        "details": {"jobs_found": found, "new_jobs": new_j},
                    }
                )
            elif s.get("status") == "error":
                events.append(
                    {
                        "id": f"{sid}_err",
                        "timestamp": ts_end,
                        "type": "scrape_error",
                        "severity": "error",
                        "target": tname,
                        "message": f"Scan failed: {s.get('error', 'Unknown error')}",
                        "details": {"error": s.get("error", "")},
                    }
                )

    # ── Events from flagged jobs (hallucination warnings) ───────────────────
    async for job in (
        db.job_postings.find({"flagged": True}, {"file_data": 0})
        .sort("analyzed_at", -1)
        .limit(50)
    ):
        ts = (
            job["analyzed_at"].isoformat()
            if job.get("analyzed_at")
            else (job["scraped_at"].isoformat() if job.get("scraped_at") else "")
        )
        events.append(
            {
                "id": f"flag_{job['_id']}",
                "timestamp": ts,
                "type": "hallucination",
                "severity": "warning",
                "target": job.get("target_name", "unknown"),
                "message": (
                    f"Low-confidence extraction: '{job.get('title', 'N/A')}' "
                    f"(score {job.get('confidence_score', '?')})"
                ),
                "details": {
                    "job_id": str(job["_id"]),
                    "confidence_score": job.get("confidence_score"),
                    "issues": job.get("quality_flags", []),
                    "company": job.get("company", ""),
                },
            }
        )

    # ── Sort, filter, cap ────────────────────────────────────────────────────
    events.sort(key=lambda e: e["timestamp"], reverse=True)
    if severity:
        events = [e for e in events if e["severity"] == severity]
    return events[:limit]
