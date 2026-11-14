"""Durable asynchronous notification worker for resilient SMS/WhatsApp outbox dispatch."""
import asyncio
import logging
from datetime import datetime, timezone
from backend.app.database import SessionLocal
from backend.app.config import settings
from backend.app.services.delivery_service import process_notification_outbox
from backend.app.routers.auth import cleanup_expired_login_attempts

logger = logging.getLogger("outbox_worker")


async def run_outbox_worker_loop(
    stop_event: asyncio.Event,
    poll_interval: int = 5,
    worker_id: str = "main-async-worker",
):
    """Continuous background loop processing queued and retrying outbox notifications."""
    logger.info(f"Starting Notification Outbox Worker loop (poll_interval={poll_interval}s, worker_id={worker_id})...")
    ticks = 0

    while not stop_event.is_set():
        try:
            # Process batch of queued/failed items
            def _worker_job():
                db = SessionLocal()
                try:
                    processed = process_notification_outbox(db, max_items=25, worker_id=worker_id)
                    # Run retention cleanup once every ~100 ticks (~500s)
                    if ticks % 100 == 0:
                        cleanup_expired_login_attempts(db, retention_days=30)
                    return processed
                finally:
                    db.close()

            count = await asyncio.to_thread(_worker_job)
            if count > 0:
                logger.info(f"[Outbox Worker] Dispatched/retried {count} notifications.")
        except Exception as exc:
            logger.error(f"[Outbox Worker] Error during worker tick: {exc}")

        ticks += 1
        # Responsive sleep
        for _ in range(poll_interval):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)

    logger.info("Notification Outbox Worker loop stopped cleanly.")
