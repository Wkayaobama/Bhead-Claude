"""Scraping engine — fetches job board URLs, extracts job postings via AI."""
import re
from datetime import datetime
from typing import Optional

import httpx
from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.claude_examples import extract_structured

router = APIRouter(prefix="/api/scraper", tags=["scraper"])

# ---------------------------------------------------------------------------
# Categories available for AI classification
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# JSON schema Claude uses to return structured job listings
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
                    "title": {"type": "string", "description": "Job title"},
                    "company": {
                        "type": "string",
                        "description": "Hiring company name",
                    },
                    "location": {
                        "type": "string",
                        "description": "Job location (city, remote, etc.)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief job description or summary (max 300 chars)",
                    },
                    "url": {
                        "type": "string",
                        "description": "Direct link to the job posting if available",
                    },
                    "salary_range": {
                        "type": "string",
                        "description": "Salary or compensation range if mentioned",
                    },
                    "posted_at": {
                        "type": "string",
                        "description": "When the job was posted (as text, e.g. '2 days ago')",
                    },
                    "category": {
                        "type": "string",
                        "enum": CATEGORIES,
                        "description": "Best-fit department category for this role",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key skills or technologies (max 5 tags)",
                    },
                },
                "required": ["title", "category"],
            },
        }
    },
    "required": ["jobs"],
}


# ---------------------------------------------------------------------------
# HTML → plain text helper (no extra deps)
# ---------------------------------------------------------------------------

def _html_to_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace to plain text."""
    # Drop script / style blocks entirely
    html = re.sub(
        r"<(script|style|noscript|head)[^>]*>.*?</(script|style|noscript|head)>",
        " ",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Replace block-level tags with newlines for readability
    html = re.sub(
        r"<(br|p|div|li|tr|h[1-6]|section|article)[^>]*>",
        "\n",
        html,
        flags=re.IGNORECASE,
    )
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode common HTML entities
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    # Collapse whitespace / blank lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core scraping logic (runs as background task)
# ---------------------------------------------------------------------------

async def _do_scrape(db, target_id: str) -> None:
    """Fetch the target URL, extract jobs with AI, store new postings."""
    target = await db.scrape_targets.find_one({"_id": ObjectId(target_id)})
    if not target:
        return

    url: str = target["url"]

    try:
        # ---- 1. Fetch the page ----
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

        # ---- 2. Convert to readable text ----
        page_text = _html_to_text(raw_html)
        # Keep first 12 000 chars to stay well within context limits
        page_text = page_text[:12_000]

        # ---- 3. AI extraction + categorisation ----
        result = await extract_structured(
            user_message=(
                f"Extract every distinct job posting from the following text scraped "
                f"from: {url}\n\n"
                f"For each posting provide: title, company, location, a short description "
                f"(under 300 chars), the direct posting URL if visible, salary range if "
                f"mentioned, when posted, the best category from the enum, and up to 5 "
                f"skill/tech tags. If a field is missing, use an empty string.\n\n"
                f"PAGE TEXT:\n{page_text}"
            ),
            schema=_JOB_EXTRACTION_SCHEMA,
            schema_name="job_listings",
            schema_description="Structured job postings extracted from a job board page",
            system_prompt=(
                "You are an expert HR data extractor. Parse job board pages and return "
                "clean structured data. Be thorough — extract every distinct role you can "
                "identify. Assign the most specific category that fits the role."
            ),
            max_tokens=4096,
        )

        jobs = result.get("jobs", [])
        new_count = 0

        # ---- 4. Persist new postings (deduplicate by title+company+target) ----
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

        # ---- 5. Update target stats ----
        job_count = await db.job_postings.count_documents({"target_id": target_id})
        await db.scrape_targets.update_one(
            {"_id": ObjectId(target_id)},
            {
                "$set": {
                    "last_scraped_at": datetime.utcnow(),
                    "status": "completed",
                    "last_error": None,
                    "job_count": job_count,
                },
                "$inc": {"scrape_count": 1},
            },
        )

    except Exception as exc:
        await db.scrape_targets.update_one(
            {"_id": ObjectId(target_id)},
            {
                "$set": {
                    "status": "error",
                    "last_error": str(exc),
                    "last_scraped_at": datetime.utcnow(),
                }
            },
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
    background_tasks.add_task(_do_scrape, db, target_id)
    return {"message": "Scrape started", "target_id": target_id}


@router.post("/run-all")
async def trigger_all_scrapes(request: Request, background_tasks: BackgroundTasks):
    db = request.app.state.db
    count = 0
    async for target in db.scrape_targets.find({"active": True, "status": {"$ne": "running"}}):
        tid = str(target["_id"])
        await db.scrape_targets.update_one(
            {"_id": target["_id"]}, {"$set": {"status": "running", "last_error": None}}
        )
        background_tasks.add_task(_do_scrape, db, tid)
        count += 1
    return {"message": f"Started scraping {count} active targets.", "count": count}
