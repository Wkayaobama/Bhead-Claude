"""In-memory error ring buffer + middleware + routes.

The App Builder polls /api/__app_errors to surface runtime issues as a
"Send to agent" popup over the preview iframe. Don't expose this to your
end-users — it's a developer/builder loop hook.
"""
import time
import traceback
import uuid
from collections import deque
from typing import Any

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

MAX_ERRORS = 100

# (id, ts, source, message, stack, route, status_code)
_errors: deque[dict[str, Any]] = deque(maxlen=MAX_ERRORS)


def _record(
    *,
    source: str,
    message: str,
    stack: str | None = None,
    route: str | None = None,
    status_code: int | None = None,
) -> dict[str, Any]:
    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "source": source,  # "frontend" | "backend" | "fetch"
        "message": message[:1000],
        "stack": (stack or "")[:4000],
        "route": route,
        "status_code": status_code,
    }
    _errors.appendleft(entry)
    return entry


class ExceptionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            if response.status_code >= 500:
                _record(
                    source="backend",
                    message=f"{response.status_code} on {request.url.path}",
                    route=request.url.path,
                    status_code=response.status_code,
                )
            return response
        except Exception as e:
            _record(
                source="backend",
                message=f"{type(e).__name__}: {e}",
                stack=traceback.format_exc(),
                route=request.url.path,
                status_code=500,
            )
            return JSONResponse(
                status_code=500,
                content={"detail": f"{type(e).__name__}: {e}"},
            )


router = APIRouter(prefix="/api/__app_errors", tags=["builder-internal"])


class FrontendError(BaseModel):
    message: str
    stack: str | None = None
    url: str | None = None
    source: str = Field(default="frontend")


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def report_frontend_error(body: FrontendError):
    _record(
        source=body.source if body.source in ("frontend", "fetch") else "frontend",
        message=body.message,
        stack=body.stack,
        route=body.url,
    )


@router.get("")
async def list_errors(since: float | None = None, limit: int = 20):
    items = [e for e in _errors if since is None or e["ts"] > since]
    return {"errors": items[:limit], "now": time.time()}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_errors():
    _errors.clear()


def install(app: FastAPI) -> None:
    app.add_middleware(ExceptionMiddleware)
    app.include_router(router)
