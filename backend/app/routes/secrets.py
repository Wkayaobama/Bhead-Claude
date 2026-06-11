"""
Secrets vault — lightweight encrypted key-value store.

Every secret is stored as a Fernet-encrypted blob in the `secrets` collection.
The encryption key is derived deterministically from the app's UT_API_KEY so
it survives container restarts without any extra configuration.

Routes
------
POST   /api/secrets                 Store or update a secret
GET    /api/secrets                 List all secrets (names + masked values only)
GET    /api/secrets/{name}/value    Return the decrypted value (runtime fetch)
DELETE /api/secrets/{name}          Remove a secret
"""

import base64
import hashlib
from datetime import datetime
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/api/secrets", tags=["secrets"])

# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

def _fernet() -> Fernet:
    """
    Derive a stable Fernet key from the app's UT_API_KEY.
    SHA-256 gives us exactly 32 bytes; urlsafe_b64encode makes it Fernet-safe.
    """
    raw = hashlib.sha256(
        f"hr_scout_vault_v1:{settings.ut_api_key}".encode()
    ).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def _decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise HTTPException(500, detail="Failed to decrypt secret — key mismatch.")


def _mask(value: str) -> str:
    """Return a fixed-length bullet mask so callers cannot infer value length."""
    return "••••••••"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SecretUpsert(BaseModel):
    variable_name: str
    value: str


class SecretOut(BaseModel):
    variable_name: str
    masked_value: str
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
async def upsert_secret(body: SecretUpsert, request: Request):
    """Store or overwrite a secret by variable name."""
    name = body.variable_name.strip().upper().replace(" ", "_")
    if not name:
        raise HTTPException(400, detail="variable_name must not be empty.")
    if not body.value.strip():
        raise HTTPException(400, detail="value must not be empty.")

    db = request.app.state.db
    now = datetime.utcnow().isoformat() + "Z"
    encrypted = _encrypt(body.value.strip())

    existing = await db.secrets.find_one({"variable_name": name})
    if existing:
        await db.secrets.update_one(
            {"variable_name": name},
            {"$set": {"encrypted_value": encrypted, "updated_at": now}},
        )
    else:
        await db.secrets.insert_one(
            {
                "variable_name": name,
                "encrypted_value": encrypted,
                "created_at": now,
                "updated_at": now,
            }
        )

    return {"variable_name": name, "masked_value": _mask(body.value), "updated_at": now}


@router.get("")
async def list_secrets(request: Request):
    """Return all stored secrets with masked values (never raw values)."""
    db = request.app.state.db
    results = []
    async for doc in db.secrets.find({}, {"encrypted_value": 0}):
        results.append(
            SecretOut(
                variable_name=doc["variable_name"],
                masked_value=_mask(""),
                created_at=doc.get("created_at", ""),
                updated_at=doc.get("updated_at", ""),
            )
        )
    return results


@router.get("/{name}/value")
async def get_secret_value(name: str, request: Request):
    """
    Return the decrypted value for a secret.
    Used by the frontend at runtime to resolve a key by variable name.
    """
    db = request.app.state.db
    doc = await db.secrets.find_one({"variable_name": name.upper()})
    if not doc:
        raise HTTPException(404, detail=f"Secret '{name}' not found.")
    return {
        "variable_name": doc["variable_name"],
        "value": _decrypt(doc["encrypted_value"]),
    }


@router.delete("/{name}", status_code=204)
async def delete_secret(name: str, request: Request):
    """Permanently delete a secret."""
    db = request.app.state.db
    result = await db.secrets.delete_one({"variable_name": name.upper()})
    if result.deleted_count == 0:
        raise HTTPException(404, detail=f"Secret '{name}' not found.")
