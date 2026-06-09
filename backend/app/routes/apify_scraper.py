"""
Apify-based scraper for jobup.ch job postings.

Flow:
  1. POST  /v2/acts/lexis-solutions~jobup-scraper/runs  →  runId + datasetId
  2. Poll  /v2/actor-runs/{runId}  until SUCCEEDED / FAILED
  3. GET   /v2/datasets/{datasetId}/items                →  list[dict]
  4. Convert each raw Apify item into a plain-text block
     that the existing Claude extraction step can understand.
"""

import asyncio
from typing import Any

import httpx

APIFY_BASE = "https://api.apify.com/v2"
ACTOR_ID = "lexis-solutions~jobup-scraper"

POLL_INTERVAL = 6       # seconds between status checks
MAX_WAIT_SECS = 600     # give the actor up to 10 minutes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str(item: dict, *keys: str, default: str = "") -> str:
    """Return the first non-empty string found for any of `keys` in `item`."""
    for k in keys:
        v = item.get(k)
        if v is None:
            continue
        # Flatten nested dicts (e.g. location: {name: "Bern"})
        if isinstance(v, dict):
            v = v.get("name") or v.get("title") or v.get("value") or next(
                (str(x) for x in v.values() if x), ""
            )
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v if x)
        v = str(v).strip()
        if v:
            return v
    return default


def apify_item_to_text_block(idx: int, item: dict[str, Any]) -> str:
    """
    Convert one raw Apify jobup item into a human-readable block so that
    the existing Claude extraction schema can parse it cleanly.

    Tries a broad set of field-name variants to be resilient against actor
    output changes.
    """
    title = _str(item, "title", "jobTitle", "position", "name")
    company = _str(item, "company", "companyName", "employer", "organisation", "companyTitle")
    location = _str(
        item,
        "location", "city", "place", "canton", "region",
        "workLocation", "jobLocation",
    )
    description = _str(
        item,
        "description", "jobDescription", "summary", "content",
        "text", "bodyText", "details",
    )[:500]
    url = _str(item, "url", "jobUrl", "detailUrl", "link", "applyUrl")
    salary = _str(
        item,
        "salary", "salaryRange", "compensation", "wage",
        "salaryInfo", "salaryText", "pay",
    )
    posted = _str(
        item,
        "publishedAt", "postedAt", "publicationDate", "date",
        "publishDate", "created_at", "datePosted",
    )
    contract = _str(item, "contractType", "employmentType", "jobType", "workModel")
    workload = _str(item, "workload", "workPercent", "hoursPerWeek", "workload_text")
    skills = _str(item, "skills", "requirements", "tags", "keywords")

    lines = [
        f"--- JOB #{idx + 1} ---",
        f"Title: {title}" if title else "",
        f"Company: {company}" if company else "",
        f"Location: {location}" if location else "",
        f"Contract: {contract}" if contract else "",
        f"Workload: {workload}" if workload else "",
        f"Salary: {salary}" if salary else "",
        f"Posted: {posted}" if posted else "",
        f"URL: {url}" if url else "",
        f"Skills/Keywords: {skills}" if skills else "",
        f"Description: {description}" if description else "",
    ]
    return "\n".join(ln for ln in lines if ln)


# ---------------------------------------------------------------------------
# Core async runner
# ---------------------------------------------------------------------------

async def run_apify_scrape(
    target_url: str,
    apify_token: str,
) -> list[dict[str, Any]]:
    """
    Trigger the Apify jobup-scraper actor, wait for completion,
    and return the dataset items.

    Raises RuntimeError on actor failure or timeout.
    """

    # ── 1. Start the actor run ──────────────────────────────────────────────
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{APIFY_BASE}/acts/{ACTOR_ID}/runs",
            params={"token": apify_token},
            json={"startUrls": [{"url": target_url}]},
        )
        resp.raise_for_status()
        run_data = resp.json()["data"]
        run_id: str = run_data["id"]
        dataset_id: str = run_data["defaultDatasetId"]

    # ── 2. Poll for completion ──────────────────────────────────────────────
    elapsed = 0
    final_status = "UNKNOWN"
    while elapsed < MAX_WAIT_SECS:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        async with httpx.AsyncClient(timeout=30) as client:
            status_resp = await client.get(
                f"{APIFY_BASE}/actor-runs/{run_id}",
                params={"token": apify_token},
            )
            status_resp.raise_for_status()
            final_status = status_resp.json()["data"]["status"]

        if final_status == "SUCCEEDED":
            break
        if final_status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(
                f"Apify actor run {run_id} ended with status: {final_status}"
            )
    else:
        raise RuntimeError(
            f"Timed out after {MAX_WAIT_SECS}s waiting for Apify run {run_id} "
            f"(last status: {final_status})"
        )

    # ── 3. Fetch dataset items ──────────────────────────────────────────────
    async with httpx.AsyncClient(timeout=60) as client:
        items_resp = await client.get(
            f"{APIFY_BASE}/datasets/{dataset_id}/items",
            params={"token": apify_token, "format": "json", "clean": "true"},
        )
        items_resp.raise_for_status()
        items = items_resp.json()

    if not isinstance(items, list):
        raise RuntimeError(
            f"Unexpected Apify dataset response type: {type(items).__name__}"
        )

    return items
