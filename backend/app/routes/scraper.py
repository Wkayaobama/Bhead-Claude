"""Scraping engine — fetches job board URLs, extracts job postings via AI.

Changes from Phase 1:
- Reads agent_config for system prompt + domain focus
- Incorporates per-target goal into the prompt
- Logs every run as an agent_session document
- Accepts triggered_by="manual"|"cron" for session attribution
"""
import re
from datetime import datetime
from typing import Optional

import httpx
from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.claude_examples import extract_structured
from app.routes.agent_config import DEFAULT_SYSTEM_PROMPT

router = APIRouter(prefix="/api/scraper", tags=["scraper"])

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
CATEGORIES = [
    "Engineering", "Marketing", "Sales", "HR", "Finance",
    "Design", "Operations", "Product", "Legal", "Other",
]

# ---------------------------------------------------------------------------
# Claude extraction schema
# ---------------------------------------------------------------------------
_JOB_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "description": "List of job postings extracted from the page",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "location": {"type": "string"},
                    "description": {
                        "type": "string",
                        "description": "Brief job description (max 300 chars)",
                    },
                    "url": {"type": "string"},
                    "salary_range": {"type": "string"},
                    "posted_at": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": CATEGORIES,
                        "description": "Best-fit department category",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key skills or technologies (max 5)",
                    },
                },
                "required": ["title", "category"],
            },
        }
    },
    "required": ["jobs"],
}


# ---------------------------------------------------------------------------
# HTML → plain text
# ---------------------------------------------------------------------------

def _html_to_text(html: str) -> str:
    html = re.sub(
        r"<(script|style|noscript|head)[^>]*>.*?</(script|style|noscript|head)>",
        " ", html, flags=re.DOTALL | re.IGNORECASE,
    )
    html = re.sub(
        r"<(br|p|div|li|tr|h[1-6]|section|article)[^>]*>",
        "\n", html, flags=re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", html)
    text = (
        text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        .replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    )
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core scraping task
# ---------------------------------------------------------------------------

async def _do_scrape(db, target_id: str, triggered_by: str = "manual") -> None:
    """Fetch target URL, extract jobs with AI, store results, log session."""
    target = await db.scrape_targets.find_one({"_id": ObjectId(target_id)})
    if not target:
        return

    url: str = target["url"]

    # ── 1. Load agent config ────────────────────────────────────────────────
    agent_cfg = await db.agent_config.find_one({"_id": "default"}) or {}
    base_prompt: str = agent_cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    domain_focus: list = agent_cfg.get("domain_focus") or []
    target_goal: str = target.get("goal") or ""

    # Build contextual system prompt
    system_prompt = base_prompt
    if domain_focus:
        system_prompt += (
            f"\n\nDomain focus areas: {', '.join(domain_focus)}. "
            "Prioritise and flag roles that match these domains."
        )
    if target_goal:
        system_prompt += f"\n\nTarget-specific goal: {target_goal}"

    # ── 2. Open session log ─────────────────────────────────────────────────
    session_doc = {
        "target_id": target_id,
        "target_name": target.get("name", ""),
        "target_url": url,
        "started_at": datetime.utcnow(),
        "completed_at": None,
        "status": "running",
        "prompt_used": system_prompt,
        "domain_focus": domain_focus,
        "target_goal": target_goal,
        "jobs_found": 0,
        "new_jobs": 0,
        "error": None,
        "triggered_by": triggered_by,
    }
    session_res = await db.agent_sessions.insert_one(session_doc)
    session_id = session_res.inserted_id

    try:
        # ── 3. Fetch the page ───────────────────────────────────────────────
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw_html = resp.text

        # ── 4. Extract text ─────────────────────────────────────────────────
        page_text = _html_to_text(raw_html)[:12_000]

        # ── 5. AI extraction ────────────────────────────────────────────────
        result = await extract_structured(
            user_message=(
                f"Extract every distinct job posting from the text below "
                f"(scraped from: {url}).\n\n"
                f"For each posting: title, company, location, short description "
                f"(≤300 chars), URL if visible, salary range, posting date, "
                f"category from the enum, and up to 5 skill tags. "
                f"Empty string for missing fields.\n\n"
                f"PAGE TEXT:\n{page_text}"
            ),
            schema=_JOB_EXTRACTION_SCHEMA,
            schema_name="job_listings",
            schema_description="Structured job postings from a job board",
            system_prompt=system_prompt,
            max_tokens=4096,
        )

        jobs = result.get("jobs", [])
        new_count = 0

        # ── 6. Persist (deduplicate) ────────────────────────────────────────
        for job in jobs:
            title = job.get("title", "").strip()
            company = job.get("company", "").strip()
            if not title:
                continue
            exists = await db.job_postings.find_one(
                {
                    "target_id": target_id,
                    "title": {"$regex": f"^{re.escape(title)}$", "$options": "i"},
                    "company": {"$regex": f"^{re.escape(company)}$", "$options": "i"},
                }
            )
            if not exists:
                await db.job_postings.insert_one(
                    {
                        **job,
                        "target_id": target_id,
                        "target_name": target.get("name", ""),
                        "target_url": url,
                        "scraped_at": datetime.utcnow(),
                    }
                )
                new_count += 1

        # ── 7. Update target + session ──────────────────────────────────────
        job_count = await db.job_postings.count_documents({"target_id": target_id})
        now = datetime.utcnow()

        await db.scrape_targets.update_one(
            {"_id": ObjectId(target_id)},
            {
                "$set": {
                    "last_scraped_at": now,
                    "status": "completed",
                    "last_error": None,
                    "job_count": job_count,
                },
                "$inc": {"scrape_count": 1},
            },
        )
        await db.agent_sessions.update_one(
            {"_id": session_id},
            {
                "$set": {
                    "completed_at": now,
                    "status": "completed",
                    "jobs_found": len(jobs),
                    "new_jobs": new_count,
                }
            },
        )

    except Exception as exc:
        now = datetime.utcnow()
        err_str = str(exc)
        await db.scrape_targets.update_one(
            {"_id": ObjectId(target_id)},
            {"$set": {"status": "error", "last_error": err_str, "last_scraped_at": now}},
        )
        await db.agent_sessions.update_one(
            {"_id": session_id},
            {"$set": {"completed_at": now, "status": "error", "error": err_str}},
        )


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@router.post("/run/{target_id}")
async def trigger_scrape(
    target_id: str, request: Request, background_tasks: BackgroundTasks
):
    db = request.app.state.db
    try:
        oid = ObjectId(target_id)
    except Exception:
        raise HTTPException(400, detail="Invalid target ID.")
    target = await db.scrape_targets.find_one({"_id": oid})
    if not target:
        raise HTTPException(404, detail="Target not found.")
    if target.get("status") == "running":
        raise HTTPException(409, detail="Scrape already in progress for this target.")

    await db.scrape_targets.update_one(
        {"_id": oid}, {"$set": {"status": "running", "last_error": None}}
    )
    background_tasks.add_task(_do_scrape, db, target_id, "manual")
    return {"message": "Scrape started", "target_id": target_id}


@router.post("/run-all")
async def trigger_all_scrapes(request: Request, background_tasks: BackgroundTasks):
    db = request.app.state.db
    count = 0
    async for target in db.scrape_targets.find(
        {"active": True, "status": {"$ne": "running"}}
    ):
        tid = str(target["_id"])
        await db.scrape_targets.update_one(
            {"_id": target["_id"]}, {"$set": {"status": "running", "last_error": None}}
        )
        background_tasks.add_task(_do_scrape, db, tid, "manual")
        count += 1
    return {"message": f"Started scraping {count} active targets.", "count": count}
