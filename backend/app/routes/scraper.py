"""Scraping engine — fetches job board URLs, extracts job postings via AI.

Two independent scrape paths:
- POST /api/scraper/run/{target_id}
    Direct HTTP fetch → HTML strip → Claude extraction.
    Works for any URL; unchanged from the original implementation.

- POST /api/scraper/run-apify/{target_id}
    Calls the Apify jobup.ch actor, which navigates to every job's leaf page
    by ID and returns structured data. Requires an Apify API token supplied
    in the request body {"apify_token": "..."}.
"""
import re
from datetime import datetime
from typing import Optional

import httpx
from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from app.claude_examples import extract_structured
from app.routes.agent_config import DEFAULT_SYSTEM_PROMPT
from app.routes.apify_scraper import (
    apify_item_to_text_block,
    run_apify_scrape,
)

router = APIRouter(prefix="/api/scraper", tags=["scraper"])

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
CATEGORIES = [
    "Engineering", "Marketing", "Sales", "HR", "Finance",
    "Design", "Operations", "Product", "Legal", "Other",
]

# ---------------------------------------------------------------------------
# Claude extraction schema  (shared by both paths)
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
# HTML → plain text  (used by the direct-fetch path)
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
# Shared: load agent config + build system prompt
# ---------------------------------------------------------------------------

async def _build_system_prompt(db, target: dict) -> tuple[str, list, str]:
    """Return (system_prompt, domain_focus, target_goal)."""
    agent_cfg = await db.agent_config.find_one({"_id": "default"}) or {}
    base_prompt: str = agent_cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    domain_focus: list = agent_cfg.get("domain_focus") or []
    target_goal: str = target.get("goal") or ""

    system_prompt = base_prompt
    if domain_focus:
        system_prompt += (
            f"\n\nDomain focus areas: {', '.join(domain_focus)}. "
            "Prioritise and flag roles that match these domains."
        )
    if target_goal:
        system_prompt += f"\n\nTarget-specific goal: {target_goal}"

    return system_prompt, domain_focus, target_goal


# ---------------------------------------------------------------------------
# Shared: persist extracted jobs + update target/session
# ---------------------------------------------------------------------------

async def _persist_jobs(
    db,
    jobs: list,
    target_id: str,
    target: dict,
    session_id,
    triggered_by: str,
) -> tuple[int, int]:
    """Insert new jobs (dedup), update target + session. Returns (found, new)."""
    url: str = target["url"]
    new_count = 0

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
    return len(jobs), new_count


async def _mark_error(db, target_id: str, session_id, exc: Exception) -> None:
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
# PATH 1 — Direct HTTP fetch  (original, unchanged logic)
# ---------------------------------------------------------------------------

async def _do_scrape(db, target_id: str, triggered_by: str = "manual") -> None:
    """Fetch target URL, extract jobs with AI, store results, log session."""
    target = await db.scrape_targets.find_one({"_id": ObjectId(target_id)})
    if not target:
        return

    url: str = target["url"]
    system_prompt, domain_focus, target_goal = await _build_system_prompt(db, target)

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
        "scrape_mode": "html",
    }
    session_res = await db.agent_sessions.insert_one(session_doc)
    session_id = session_res.inserted_id

    try:
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

        page_text = _html_to_text(raw_html)[:12_000]

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

        await _persist_jobs(
            db, result.get("jobs", []), target_id, target, session_id, triggered_by
        )

    except Exception as exc:
        await _mark_error(db, target_id, session_id, exc)


# ---------------------------------------------------------------------------
# PATH 2 — Apify actor  (jobup.ch leaf-page scraper)
# ---------------------------------------------------------------------------

async def _do_scrape_apify(
    db, target_id: str, apify_token: str, triggered_by: str = "manual"
) -> None:
    """
    Run the Apify jobup.ch actor, wait for completion, extract jobs with AI,
    store results and log session.
    """
    target = await db.scrape_targets.find_one({"_id": ObjectId(target_id)})
    if not target:
        return

    url: str = target["url"]
    system_prompt, domain_focus, target_goal = await _build_system_prompt(db, target)

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
        "scrape_mode": "apify",
    }
    session_res = await db.agent_sessions.insert_one(session_doc)
    session_id = session_res.inserted_id

    try:
        # ── 1. Run Apify actor and retrieve leaf-page items ──────────────────
        raw_items = await run_apify_scrape(url, apify_token)
        if not raw_items:
            raise RuntimeError(
                "Apify returned 0 items. "
                "Check that the jobup.ch URL is valid and publicly accessible."
            )

        # ── 2. Convert structured Apify items → readable text for Claude ─────
        page_text = "\n\n".join(
            apify_item_to_text_block(i, item)
            for i, item in enumerate(raw_items)
        )[:15_000]

        source_label = (
            f"Apify jobup.ch actor — {len(raw_items)} leaf-page items from: {url}"
        )

        # ── 3. Claude normalisation + categorisation ─────────────────────────
        result = await extract_structured(
            user_message=(
                f"Extract every distinct job posting from the structured data "
                f"below ({source_label}).\n\n"
                f"For each posting: title, company, location, short description "
                f"(≤300 chars), URL if present, salary range, posting date, "
                f"category from the enum, and up to 5 skill tags. "
                f"Empty string for missing fields.\n\n"
                f"DATA:\n{page_text}"
            ),
            schema=_JOB_EXTRACTION_SCHEMA,
            schema_name="job_listings",
            schema_description="Structured job postings extracted via Apify",
            system_prompt=system_prompt,
            max_tokens=4096,
        )

        await _persist_jobs(
            db, result.get("jobs", []), target_id, target, session_id, triggered_by
        )

    except Exception as exc:
        await _mark_error(db, target_id, session_id, exc)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

class ApifyRunRequest(BaseModel):
    apify_token: str


@router.post("/run/{target_id}")
async def trigger_scrape(
    target_id: str, request: Request, background_tasks: BackgroundTasks
):
    """Trigger the direct HTML-fetch scrape for a target."""
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


@router.post("/run-apify/{target_id}")
async def trigger_apify_scrape(
    target_id: str,
    body: ApifyRunRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Trigger the Apify jobup.ch leaf-page scraper for a target.

    Requires `{"apify_token": "<your Apify API token>"}` in the request body.
    """
    db = request.app.state.db
    try:
        oid = ObjectId(target_id)
    except Exception:
        raise HTTPException(400, detail="Invalid target ID.")
    if not body.apify_token.strip():
        raise HTTPException(400, detail="apify_token must not be empty.")

    target = await db.scrape_targets.find_one({"_id": oid})
    if not target:
        raise HTTPException(404, detail="Target not found.")
    if target.get("status") == "running":
        raise HTTPException(409, detail="Scrape already in progress for this target.")

    await db.scrape_targets.update_one(
        {"_id": oid}, {"$set": {"status": "running", "last_error": None}}
    )
    background_tasks.add_task(
        _do_scrape_apify, db, target_id, body.apify_token.strip(), "manual"
    )
    return {"message": "Apify scrape started", "target_id": target_id}


@router.post("/run-all")
async def trigger_all_scrapes(request: Request, background_tasks: BackgroundTasks):
    """Trigger the direct HTML-fetch scrape for all active targets."""
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
