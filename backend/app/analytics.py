"""Lightweight pageview / request analytics for generated apps.

Same shape as `error_tracker`: one `install(app)` call wires a middleware
that records every request into a capped Mongo collection, plus a small
read endpoint the App Builder orchestrator proxies into its Backend
panel. The user never has to reach for this.

Privacy: client IPs are stored as `/24` netmasks (last octet zeroed) so
the "unique visitors" count is meaningful without keeping raw IPs. Set
`ANALYTICS_KEEP_FULL_IP=1` in the project's .env if you need raw IPs
for a specific deployment.

Storage: the `__analytics` collection is **capped** at ~50 MB, which is
~250k requests at the average row size. Rows roll off oldest-first; no
maintenance needed.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

COLLECTION = "__analytics"
CAPPED_BYTES = 50 * 1024 * 1024  # 50 MB
KEEP_FULL_IP = os.environ.get("ANALYTICS_KEEP_FULL_IP", "") == "1"


def _ip_prefix(ip: str) -> str:
    """Mask the last octet of an IPv4 / collapse the last hextet of an
    IPv6 so we can count uniques without storing the raw address."""
    if KEEP_FULL_IP:
        return ip
    if not ip:
        return ""
    if "." in ip:
        parts = ip.split(".")
        if len(parts) == 4:
            return ".".join(parts[:3] + ["0"])
    if ":" in ip:
        parts = ip.split(":")
        if len(parts) >= 4:
            return ":".join(parts[:-1] + ["0"])
    return ip


def _client_ip(request: Request) -> str:
    # When Traefik is in front the real client IP is in X-Forwarded-For.
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


def _is_internal_path(path: str) -> bool:
    """Don't record requests to builder-internal endpoints — they're
    not user traffic. /api/__app_errors, /api/__analytics, /docs, etc."""
    if path.startswith("/api/__"):
        return True
    if path in {"/docs", "/redoc", "/openapi.json", "/favicon.ico"}:
        return True
    return False


class _AnalyticsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        try:
            path = request.url.path
            if _is_internal_path(path):
                return response
            db = getattr(request.app.state, "db", None)
            if db is None:
                return response
            await db[COLLECTION].insert_one({
                "ts": datetime.now(timezone.utc),
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "referer": (request.headers.get("referer") or "")[:200],
                "ua": (request.headers.get("user-agent") or "")[:300],
                "ip_prefix": _ip_prefix(_client_ip(request)),
                "ms": int((time.perf_counter() - started) * 1000),
            })
        except Exception:
            # Analytics must never break a request.
            pass
        return response


async def _ensure_capped(db) -> None:
    """Create the `__analytics` collection as capped if it doesn't exist
    yet. Idempotent. If a regular collection already exists (e.g. created
    via insert before install ran) we leave it as-is."""
    names = await db.list_collection_names()
    if COLLECTION in names:
        return
    try:
        await db.create_collection(
            COLLECTION, capped=True, size=CAPPED_BYTES,
        )
    except Exception:
        # Race with another process / driver complaint — best effort.
        pass


def install(app: FastAPI) -> None:
    """Attach the request-recording middleware and a read endpoint that
    the App Builder orchestrator proxies into the Backend panel."""
    app.add_middleware(_AnalyticsMiddleware)

    @app.get("/api/__analytics/summary")
    async def analytics_summary(days: int = 7):
        """Return aggregates over the last `days` days:
            { total_pageviews, unique_visitors, top_paths, top_referers,
              by_day: [{day, pageviews, visitors}, ...] }
        """
        db = app.state.db
        await _ensure_capped(db)
        days = max(1, min(90, int(days)))
        since = datetime.now(timezone.utc) - timedelta(days=days)

        total_pageviews = await db[COLLECTION].count_documents({
            "ts": {"$gte": since},
        })
        # Unique visitors = distinct ip_prefix over the window.
        unique_visitors = len(
            await db[COLLECTION].distinct("ip_prefix", {
                "ts": {"$gte": since},
                "ip_prefix": {"$ne": ""},
            })
        )

        async def top_n(field: str, n: int = 5) -> list[dict]:
            pipeline = [
                {"$match": {"ts": {"$gte": since}, field: {"$ne": ""}}},
                {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": n},
                {"$project": {"_id": 0, "value": "$_id", "count": 1}},
            ]
            return await db[COLLECTION].aggregate(pipeline).to_list(length=n)

        top_paths = await top_n("path")
        top_referers = await top_n("referer")
        top_devices = await _device_breakdown(db, since)

        # Daily series: pageviews + unique visitors per day, oldest → newest.
        day_pipeline = [
            {"$match": {"ts": {"$gte": since}}},
            {"$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%m-%d", "date": "$ts"},
                },
                "pageviews": {"$sum": 1},
                "ips": {"$addToSet": "$ip_prefix"},
            }},
            {"$project": {
                "_id": 0,
                "day": "$_id",
                "pageviews": 1,
                "visitors": {"$size": "$ips"},
            }},
            {"$sort": {"day": 1}},
        ]
        by_day = await db[COLLECTION].aggregate(day_pipeline).to_list(length=days)

        return {
            "days": days,
            "total_pageviews": total_pageviews,
            "unique_visitors": unique_visitors,
            "top_paths": top_paths,
            "top_referers": top_referers,
            "top_devices": top_devices,
            "by_day": by_day,
        }


async def _device_breakdown(db, since: datetime) -> list[dict]:
    """Very rough device-class buckets from User-Agent: Mobile / Tablet /
    Desktop / Bot. Done with $regexMatch so we don't need to parse UAs
    in Python."""
    pipeline = [
        {"$match": {"ts": {"$gte": since}}},
        {"$addFields": {
            "device": {
                "$switch": {
                    "branches": [
                        {"case": {"$regexMatch": {
                            "input": "$ua",
                            "regex": "(bot|crawler|spider|curl|wget|python-requests)",
                            "options": "i",
                        }}, "then": "Bot"},
                        {"case": {"$regexMatch": {
                            "input": "$ua",
                            "regex": "(iPad|Tablet)",
                            "options": "i",
                        }}, "then": "Tablet"},
                        {"case": {"$regexMatch": {
                            "input": "$ua",
                            "regex": "(Mobile|Android|iPhone)",
                            "options": "i",
                        }}, "then": "Mobile"},
                    ],
                    "default": "Desktop",
                },
            },
        }},
        {"$group": {"_id": "$device", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$project": {"_id": 0, "value": "$_id", "count": 1}},
    ]
    return await db[COLLECTION].aggregate(pipeline).to_list(length=10)
