from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

from app import analytics, error_tracker
from app.config import settings
from app.routes import jobs, scraper, targets


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncIOMotorClient(settings.mongo_url)
    app.state.mongo = client
    db = client[settings.mongo_db]
    app.state.db = db

    # Ensure indexes for fast look-ups
    await db.scrape_targets.create_index("url", unique=True)
    await db.scrape_targets.create_index("active")
    await db.job_postings.create_index("target_id")
    await db.job_postings.create_index("category")
    await db.job_postings.create_index("scraped_at")
    await db.job_postings.create_index([("title", "text"), ("company", "text")])

    try:
        yield
    finally:
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

# Builder-internal error tracking + analytics
error_tracker.install(app)
analytics.install(app)

# Feature routers
app.include_router(targets.router)
app.include_router(scraper.router)
app.include_router(jobs.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "project": settings.project_name}
