"""PostcodeLink Nigeria - FastAPI Main Application."""
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.app.config import settings
from backend.app.database import engine, Base, get_db
from backend.app.seed import seed_database
from backend.app.workers.outbox_worker import run_outbox_worker_loop
from backend.app.routers import (
    auth,
    deliveries,
    postcodes,
    operators,
    customers,
    analytics,
    api_keys,
)

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager running startup database checks, development seeding, and background outbox worker."""
    if settings.ENVIRONMENT == "production":
        logger.info(
            "Production environment: Skipping automatic DDL. Schema managed strictly via Alembic migrations ('alembic upgrade head')."
        )
        if settings.SEED_DEMO_DATA or settings.SEED_DEMO_ACCOUNTS:
            raise RuntimeError(
                "Fatal Security Error: SEED_DEMO_DATA and SEED_DEMO_ACCOUNTS cannot be enabled in production environment."
            )
    else:
        logger.info("Development/Test environment: Initializing local tables if not existing...")
        Base.metadata.create_all(bind=engine)
        if settings.SEED_DEMO_DATA:
            try:
                seed_database()
            except Exception as e:
                logger.warning(f"Database seed note: {e}")

    # Start asynchronous outbox retry worker only if enabled and process role is all_in_one or worker
    worker_task = None
    stop_event = asyncio.Event()
    should_run_embedded = settings.OUTBOX_WORKER_ENABLED and settings.PROCESS_ROLE in ("all_in_one", "worker")
    if should_run_embedded:
        logger.info(f"Starting embedded background Outbox Dispatch Worker (PROCESS_ROLE={settings.PROCESS_ROLE})...")
        worker_task = asyncio.create_task(
            run_outbox_worker_loop(stop_event, poll_interval=settings.OUTBOX_WORKER_INTERVAL_SECONDS)
        )
    elif settings.OUTBOX_WORKER_ENABLED:
        logger.info(f"API process role ('{settings.PROCESS_ROLE}'): Embedded worker disabled; managed by standalone outbox worker process.")

    yield

    logger.info("Shutting down PostcodeLink API...")
    if worker_task:
        logger.info("Stopping Outbox Worker...")
        stop_event.set()
        try:
            await asyncio.wait_for(worker_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Nigeria address intelligence, digital postcode resolution, and reliable last-mile delivery tracking API.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers under /api/v1
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(deliveries.router, prefix=settings.API_V1_STR)
app.include_router(postcodes.router, prefix=settings.API_V1_STR)
app.include_router(operators.router, prefix=settings.API_V1_STR)
app.include_router(customers.router, prefix=settings.API_V1_STR)
app.include_router(analytics.router, prefix=settings.API_V1_STR)
app.include_router(api_keys.router, prefix=settings.API_V1_STR)


@app.get("/", tags=["system"])
def root():
    return {
        "service": "PostcodeLink Nigeria API",
        "status": "operational",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "docs_url": "/docs",
        "api_v1": settings.API_V1_STR,
    }


@app.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    """Healthcheck endpoint verifying database connectivity."""
    db.execute(text("SELECT 1"))
    return {
        "status": "healthy",
        "database": "connected",
        "engine": engine.name,
    }


@app.get("/health/live", tags=["system"])
def health_live():
    """Liveness probe: verifies application process is running."""
    return {
        "status": "alive",
        "service": "PostcodeLink Nigeria API",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/health/ready", tags=["system"])
def health_ready(db: Session = Depends(get_db)):
    """Readiness probe: verifies database connectivity and core tables.
    
    Returns HTTP 200 when database connectivity succeeds.
    Returns HTTP 503 Service Unavailable when database check fails, omitting internal stack traces.
    """
    try:
        db.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "database": "connected",
            "engine": engine.name,
        }
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unready",
                "database": "disconnected",
                "error": "Database service is unavailable.",
            },
        )


@app.get("/health/worker", tags=["system"])
def health_worker(db: Session = Depends(get_db)):
    """Worker monitoring: checks outbox queue depth, active leases, heartbeat, and reconciliation items."""
    from backend.app.models.notification_outbox import NotificationOutbox
    from backend.app.services.notification_service import NotificationDeliveryStatus
    from backend.app.services.delivery_service import WORKER_LAST_HEARTBEAT
    from sqlalchemy import func
    from datetime import datetime, timezone

    pending_count = db.query(func.count(NotificationOutbox.id)).filter(
        NotificationOutbox.status.in_([
            NotificationDeliveryStatus.QUEUED,
            NotificationDeliveryStatus.FAILED,
            NotificationDeliveryStatus.DISPATCHING,
        ])
    ).scalar() or 0

    reconciliation_count = db.query(func.count(NotificationOutbox.id)).filter(
        NotificationOutbox.status == NotificationDeliveryStatus.RECONCILIATION_REQUIRED
    ).scalar() or 0

    now = datetime.now(timezone.utc)
    worker_status = "operational"
    heartbeat_str = None
    if WORKER_LAST_HEARTBEAT:
        heartbeat_str = WORKER_LAST_HEARTBEAT.isoformat()
        if (now - WORKER_LAST_HEARTBEAT).total_seconds() > 600 and settings.OUTBOX_WORKER_ENABLED:
            worker_status = "degraded"
    elif settings.OUTBOX_WORKER_ENABLED and settings.PROCESS_ROLE in ["worker", "all_in_one"]:
        worker_status = "idle"

    return {
        "status": worker_status,
        "process_role": settings.PROCESS_ROLE,
        "worker_enabled": settings.OUTBOX_WORKER_ENABLED,
        "last_heartbeat": heartbeat_str,
        "poll_interval_seconds": settings.OUTBOX_WORKER_INTERVAL_SECONDS,
        "lease_timeout_minutes": settings.OUTBOX_LEASE_TIMEOUT_MINUTES,
        "outbox_pending_count": pending_count,
        "outbox_reconciliation_required_count": reconciliation_count,
        "reconciliation_alert": reconciliation_count > 0,
    }


@app.get("/health/integrations", tags=["system"])
def health_integrations():
    """Integration health: returns NIPOST and SMS provider configuration and reachability status."""
    nipost_configured = bool(settings.NIPOST_API_KEY and (settings.NIPOST_API_URL or settings.NIPOST_API_BASE_URL))
    sms_configured = False
    if settings.SMS_PROVIDER == "termii":
        sms_configured = bool(settings.TERMII_API_KEY and settings.TERMII_SENDER_ID)
    elif settings.SMS_PROVIDER == "twilio":
        sms_configured = bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_FROM_NUMBER)
    elif settings.SMS_PROVIDER == "simulated":
        sms_configured = True

    overall_status = "operational"
    if settings.ENVIRONMENT == "production":
        if not sms_configured or settings.SMS_PROVIDER == "simulated":
            overall_status = "degraded"
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": overall_status,
                    "error": "Production SMS provider is not configured or set to simulated.",
                    "nipost": {"configured": nipost_configured},
                    "sms_gateway": {"provider": settings.SMS_PROVIDER, "configured": sms_configured},
                },
            )

    return {
        "status": overall_status,
        "nipost": {
            "configured": nipost_configured,
            "base_url": settings.NIPOST_API_URL or settings.NIPOST_API_BASE_URL or "not_configured",
            "timeout_seconds": settings.NIPOST_TIMEOUT_SECONDS,
        },
        "sms_gateway": {
            "provider": settings.SMS_PROVIDER,
            "configured": sms_configured,
            "production_ready": settings.SMS_PROVIDER in ["termii", "twilio"] and sms_configured,
        },
    }
