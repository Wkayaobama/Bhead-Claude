"""Background asyncio cron scheduler.

Runs inside the FastAPI lifespan. Every TICK_SECONDS it queries for
active targets with cron enabled whose next-run time has passed, then
fires a scrape task for each one.
"""
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

TICK_SECONDS = 60  # wake up every minute to check due targets


async def scheduler_loop(db) -> None:
    """Long-running coroutine — cancel to stop."""
    # Import here to avoid a circular import at module load time
    from app.routes.scraper import _do_scrape

    logger.info("Cron scheduler started (tick=%ss)", TICK_SECONDS)

    while True:
        try:
            now = datetime.utcnow()

            # Find targets that are due for a cron scrape
            cursor = db.scrape_targets.find(
                {
                    "active": True,
                    "cron_enabled": True,
                    "status": {"$ne": "running"},
                    "$or": [
                        {"cron_next_run": {"$lte": now}},
                        {"cron_next_run": None},
                        {"cron_next_run": {"$exists": False}},
                    ],
                }
            )

            async for target in cursor:
                tid = str(target["_id"])
                interval = int(target.get("cron_interval_minutes", 1440))
                next_run = now + timedelta(minutes=interval)

                logger.info("Cron: firing scrape for target %s", tid)

                # Reserve the slot before spawning the task
                await db.scrape_targets.update_one(
                    {"_id": target["_id"]},
                    {
                        "$set": {
                            "status": "running",
                            "cron_next_run": next_run,
                            "last_error": None,
                        }
                    },
                )

                asyncio.create_task(_do_scrape(db, tid, triggered_by="cron"))

        except asyncio.CancelledError:
            logger.info("Cron scheduler stopped")
            break
        except Exception as exc:  # pragma: no cover
            logger.error("Scheduler tick error: %s", exc)

        try:
            await asyncio.sleep(TICK_SECONDS)
        except asyncio.CancelledError:
            logger.info("Cron scheduler stopped")
            break
