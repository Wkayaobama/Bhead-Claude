"""Agent configuration — system prompt, domain focus, and overall goal.

One singleton document (_id="default") is stored in the agent_config
collection. The scraper reads it at run-time so prompt changes take
effect immediately on the next scan.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/agent-config", tags=["agent-config"])

# ---------------------------------------------------------------------------
# Default system prompt shipped out-of-the-box
# ---------------------------------------------------------------------------
DEFAULT_SYSTEM_PROMPT = (
    "You are an expert HR recruitment intelligence agent.\n"
    "Your task is to scan job board pages and extract every distinct job posting "
    "with high accuracy. Be thorough and structured.\n"
    "For each role, identify: title, company, location, a concise description, "
    "required skills, salary range (if present), and posting date.\n"
    "Assign the most precise department category that fits the role.\n"
    "Quality over quantity — only extract genuine job postings, not ads or banners."
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AgentConfigUpdate(BaseModel):
    system_prompt: Optional[str] = None
    domain_focus: Optional[List[str]] = None
    goal: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(config: dict) -> dict:
    config.pop("_id", None)
    if config.get("updated_at"):
        config["updated_at"] = config["updated_at"].isoformat()
    if config.get("created_at"):
        config["created_at"] = config["created_at"].isoformat()
    return config


def _default_config() -> dict:
    return {
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "domain_focus": [],
        "goal": "",
        "updated_at": None,
        "created_at": None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
async def get_config(request: Request):
    db = request.app.state.db
    config = await db.agent_config.find_one({"_id": "default"})
    if not config:
        return _default_config()
    return _clean(config)


@router.put("")
async def update_config(body: AgentConfigUpdate, request: Request):
    db = request.app.state.db
    now = datetime.utcnow()
    update: dict = {"updated_at": now}

    if body.system_prompt is not None:
        update["system_prompt"] = body.system_prompt.strip()
    if body.domain_focus is not None:
        # Normalise: strip blanks, deduplicate, drop empties
        update["domain_focus"] = list(
            dict.fromkeys(t.strip() for t in body.domain_focus if t.strip())
        )
    if body.goal is not None:
        update["goal"] = body.goal.strip()

    await db.agent_config.update_one(
        {"_id": "default"},
        {"$set": update, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return await get_config(request)


@router.post("/reset")
async def reset_config(request: Request):
    """Restore factory defaults."""
    db = request.app.state.db
    await db.agent_config.delete_one({"_id": "default"})
    return _default_config()
