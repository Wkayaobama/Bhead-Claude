import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

from app import llm
from app.config import settings
from app.quality import describe as describe_quality
from app.routes import admin, agent_config, documents, jobs, monitor, scraper, secrets, sessions, targets


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncIOMotorClient(settings.mongo_url)
    app.state.mongo = client
    db = client[settings.mongo_db]
    app.state.db = db

    # Indexes
    await db.scrape_targets.create_index("url", unique=True)
    await db.scrape_targets.create_index("active")
    await db.scrape_targets.create_index("cron_enabled")
    await db.scrape_targets.create_index("cron_next_run")
    await db.job_postings.create_index("target_id")
    await db.job_postings.create_index("category")
    await db.job_postings.create_index("scraped_at")
    await db.job_postings.create_index([("title", "text"), ("company", "text")])
    await db.agent_sessions.create_index("target_id")
    await db.agent_sessions.create_index("started_at")
    await db.agent_sessions.create_index("status")
    await db.documents.create_index("job_id")
    await db.documents.create_index("uploaded_at")
    await db.secrets.create_index("variable_name", unique=True)

    # Start cron scheduler
    from app.scheduler import scheduler_loop
    scheduler_task = asyncio.create_task(scheduler_loop(db))
    app.state.scheduler_task = scheduler_task

    try:
        yield
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        client.close()


app = FastAPI(
    title=settings.project_name,
    lifespan=lifespan,
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# The browser reaches /api through the Vite dev server (and, in production,
# the same reverse proxy that serves the bundle), so cross-origin calls only
# happen when CORS_ORIGINS names them explicitly.
if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Feature routers
app.include_router(admin.router)
app.include_router(secrets.router)
app.include_router(targets.router)
app.include_router(scraper.router)
app.include_router(jobs.router)
app.include_router(agent_config.router)
app.include_router(sessions.router)
app.include_router(documents.router)
app.include_router(monitor.router)


@app.get("/api/health")
async def health(request: Request):
    """Liveness plus the configuration facts an operator checks first."""
    mongo_client = getattr(request.app.state, "mongo", None)
    if mongo_client is None:
        mongo = "not connected"
    else:
        try:
            # Bounded: a down database must answer "unreachable" within a
            # probe's deadline, not after the driver's 30 s server selection.
            await asyncio.wait_for(mongo_client.admin.command("ping"), timeout=2)
            mongo = "ok"
        except Exception:
            mongo = "unreachable"
    quality = describe_quality()
    return {
        "status": "ok" if mongo == "ok" else "degraded",
        "project": settings.project_name,
        "mongo": mongo,
        "llm": llm.describe(),
        "quality": {
            "threshold": quality["threshold"],
            "rules": len(quality["rules"]),
            "bands": [b["key"] for b in quality["bands"]],
        },
        "secrets_vault": bool(settings.secrets_encryption_key),
        "caps": {
            "scrape_page_chars": settings.scrape_page_chars,
            "apify_text_chars": settings.apify_text_chars,
            "extract_max_tokens": settings.extract_max_tokens,
            "chat_max_tokens": settings.chat_max_tokens,
        },
    }
