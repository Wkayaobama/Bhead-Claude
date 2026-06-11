"""
Admin utilities — safe to call from the UI before deployment.

POST /api/admin/revoke-keys
  Clears any API keys / tokens stored in the database and returns a summary
  of what was removed. The git remote credential (GitHub PAT) is handled
  at the host level and is not reachable from inside this container.

The Apify token is stored exclusively in browser localStorage by the
frontend and is intentionally NOT touched here so scraping stays functional.
"""
from datetime import datetime

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Collections that may hold temporary credentials or session tokens
_KEY_COLLECTIONS = [
    "deployment_keys",
    "temp_tokens",
    "session_tokens",
    "oauth_sessions",
]


@router.post("/revoke-keys")
async def revoke_keys(request: Request):
    """
    Clear all session-stored API keys / tokens from the database.
    Safe to call before publishing or sharing the app.

    Returns:
        revoked  – list of things that were cleared
        skipped  – list of collections that didn't exist / were already empty
        timestamp – ISO datetime of the operation
    """
    db = request.app.state.db
    revoked: list[str] = []
    skipped: list[str] = []

    for collection_name in _KEY_COLLECTIONS:
        result = await db[collection_name].delete_many({})
        if result.deleted_count > 0:
            revoked.append(f"{collection_name} ({result.deleted_count} doc{'s' if result.deleted_count != 1 else ''})")
        else:
            skipped.append(collection_name)

    # Also clear any GitHub-related entries from a generic settings collection
    gh_result = await db.app_settings.delete_many(
        {"key": {"$regex": "github", "$options": "i"}}
    )
    if gh_result.deleted_count > 0:
        revoked.append(f"app_settings/github ({gh_result.deleted_count} entries)")

    return {
        "ok": True,
        "revoked": revoked,
        "skipped": skipped,
        "message": (
            f"Revoked {len(revoked)} key set(s)."
            if revoked
            else "No session keys found — nothing to revoke."
        ),
        "note": (
            "Git remote credentials are managed at the host level. "
            "The Apify browser token was intentionally preserved."
        ),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
