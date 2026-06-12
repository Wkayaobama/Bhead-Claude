import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import chat, workflows as workflow_routes
from app.workflows import scheduler_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Headless-workflow scheduler (see app/workflows.py). Runs for the
    # life of the server; fires due workflows in the background.
    scheduler_task = asyncio.create_task(scheduler_loop())
    try:
        yield
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.project_name,
    lifespan=lifespan,
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(workflow_routes.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "project": settings.project_name}
