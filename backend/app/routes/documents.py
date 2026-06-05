"""File upload, document library, and AI-powered interview-prep chat."""
import io
import json
from datetime import datetime
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.claude_examples import stream_chat

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# Text extraction (PDF + plain text; no extra deps for plain text)
# ---------------------------------------------------------------------------

def _extract_text(data: bytes, content_type: str, filename: str) -> str:
    ct = (content_type or "").lower()
    fn = (filename or "").lower()

    # Plain-text family
    if "text/" in ct or fn.endswith((".txt", ".md", ".csv", ".json", ".rst")):
        try:
            return data.decode("utf-8", errors="replace")[:20_000]
        except Exception:
            return ""

    # PDF
    if "pdf" in ct or fn.endswith(".pdf"):
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(io.BytesIO(data))
            parts = [p.extract_text() or "" for p in reader.pages]
            return "\n".join(parts)[:20_000]
        except Exception:
            return "[PDF text extraction unavailable — pypdf not installed or parsing failed]"

    return "[Binary file — no text extraction available for this format]"


# ---------------------------------------------------------------------------
# Serialisation helper (never exposes raw file bytes)
# ---------------------------------------------------------------------------

def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    doc.pop("file_data", None)
    if doc.get("uploaded_at"):
        doc["uploaded_at"] = doc["uploaded_at"].isoformat()
    return doc


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@router.post("/upload/{job_id}", status_code=201)
async def upload_document(
    job_id: str,
    request: Request,
    file: UploadFile = File(...),
    notes: str = Form(default=""),
):
    db = request.app.state.db
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(400, detail="Invalid job ID.")

    job = await db.job_postings.find_one({"_id": oid})
    if not job:
        raise HTTPException(404, detail="Job posting not found.")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail="File exceeds 10 MB limit.")
    if len(data) == 0:
        raise HTTPException(400, detail="Uploaded file is empty.")

    doc = {
        "job_id": job_id,
        "job_title": job.get("title", ""),
        "job_company": job.get("company", ""),
        "filename": file.filename or "unnamed",
        "content_type": file.content_type or "application/octet-stream",
        "file_data": data,
        "size": len(data),
        "notes": notes.strip(),
        "uploaded_at": datetime.utcnow(),
    }
    result = await db.documents.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    doc.pop("file_data", None)
    doc["uploaded_at"] = doc["uploaded_at"].isoformat()
    return doc


# ---------------------------------------------------------------------------
# Stats + listing
# ---------------------------------------------------------------------------

@router.get("/stats")
async def document_stats(request: Request):
    db = request.app.state.db
    total = await db.documents.count_documents({})
    pipeline = [{"$group": {"_id": None, "total_size": {"$sum": "$size"}}}]
    agg = await db.documents.aggregate(pipeline).to_list(1)
    total_size = agg[0]["total_size"] if agg else 0
    return {"total": total, "total_size": total_size}


@router.get("/counts")
async def document_counts(request: Request):
    """Return {job_id: count} map — used by the job feed to badge each card."""
    db = request.app.state.db
    pipeline = [{"$group": {"_id": "$job_id", "count": {"$sum": 1}}}]
    result: dict = {}
    async for row in db.documents.aggregate(pipeline):
        if row["_id"]:
            result[row["_id"]] = row["count"]
    return result


@router.get("")
async def list_documents(request: Request, job_id: Optional[str] = None):
    db = request.app.state.db
    query: dict = {}
    if job_id:
        query["job_id"] = job_id
    docs = []
    async for doc in db.documents.find(query, {"file_data": 0}).sort("uploaded_at", -1):
        docs.append(_serialize(doc))
    return docs


# ---------------------------------------------------------------------------
# Download + delete
# ---------------------------------------------------------------------------

@router.get("/{doc_id}/download")
async def download_document(doc_id: str, request: Request):
    db = request.app.state.db
    try:
        oid = ObjectId(doc_id)
    except Exception:
        raise HTTPException(400, detail="Invalid document ID.")
    doc = await db.documents.find_one({"_id": oid})
    if not doc:
        raise HTTPException(404, detail="Document not found.")
    return Response(
        content=bytes(doc["file_data"]),
        media_type=doc.get("content_type", "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="{doc["filename"]}"',
            "Content-Length": str(doc["size"]),
        },
    )


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: str, request: Request):
    db = request.app.state.db
    try:
        oid = ObjectId(doc_id)
    except Exception:
        raise HTTPException(400, detail="Invalid document ID.")
    result = await db.documents.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(404, detail="Document not found.")


# ---------------------------------------------------------------------------
# Interview-prep streaming chat (step 11)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    doc_id: str
    job_id: str
    message: str
    history: List[dict] = []


@router.post("/chat")
async def interview_prep_chat(req: ChatRequest, request: Request):
    db = request.app.state.db

    # Resolve document
    try:
        doc = await db.documents.find_one({"_id": ObjectId(req.doc_id)})
    except Exception:
        raise HTTPException(400, detail="Invalid document ID.")
    if not doc:
        raise HTTPException(404, detail="Document not found.")

    # Resolve job posting
    try:
        job = await db.job_postings.find_one({"_id": ObjectId(req.job_id)})
    except Exception:
        job = None

    # Extract readable text from the uploaded file
    doc_text = _extract_text(
        bytes(doc["file_data"]),
        doc.get("content_type", ""),
        doc.get("filename", ""),
    )

    # Build job context block
    if job:
        job_block = (
            f"TITLE: {job.get('title', '')}\n"
            f"COMPANY: {job.get('company', '')}\n"
            f"LOCATION: {job.get('location', '')}\n"
            f"CATEGORY: {job.get('category', '')}\n"
            f"DESCRIPTION: {job.get('description', '')}\n"
            f"REQUIRED SKILLS: {', '.join(job.get('tags', []))}\n"
            f"SALARY: {job.get('salary_range', 'Not specified')}"
        )
    else:
        job_block = "No job details available."

    system_prompt = (
        "You are an expert HR interview coach and career strategist.\n\n"
        f"=== TARGET JOB POSTING ===\n{job_block}\n\n"
        f"=== CANDIDATE DOCUMENT: {doc['filename']} ===\n{doc_text}\n\n"
        "Your responsibilities:\n"
        "- Analyse the candidate document against the job requirements\n"
        "- Suggest which specific experiences to highlight for this role\n"
        "- Generate likely interview questions with model answers tailored to the candidate\n"
        "- Flag any skill gaps and how to address or frame them positively\n"
        "- Advise on salary negotiation based on the role and market norms\n"
        "- Be specific, actionable, and encouraging. Reference actual details from both documents."
    )

    async def gen():
        try:
            async for chunk in stream_chat(
                user_message=req.message,
                history=req.history,
                system_prompt=system_prompt,
                max_tokens=1500,
            ):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield 'data: {"done": true}\n\n'
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
