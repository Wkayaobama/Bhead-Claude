import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

from app import analytics, error_tracker
from app.config import settings
from app.routes import agent_config, documents, jobs, monitor, scraper, sessions, targets


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

error_tracker.install(app)
analytics.install(app)

# Feature routers
app.include_router(targets.router)
app.include_router(scraper.router)
app.include_router(jobs.router)
app.include_router(agent_config.router)
app.include_router(sessions.router)
app.include_router(documents.router)
app.include_router(monitor.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "project": settings.project_name}
