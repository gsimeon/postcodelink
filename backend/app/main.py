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
    """Worker monitoring: checks persistent cross-process worker heartbeats, lifecycle states, and queue backlog."""
    from backend.app.models.notification_outbox import NotificationOutbox
    from backend.app.models.worker_heartbeat import WorkerHeartbeat
    from backend.app.services.notification_service import NotificationDeliveryStatus
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
    threshold = getattr(settings, "OUTBOX_WORKER_HEARTBEAT_THRESHOLD_SECONDS", 120)

    heartbeats = db.query(WorkerHeartbeat).all()
    active_workers = []
    stale_workers = []
    stopped_workers = []
    latest_hb = None
    latest_success_process_at = None

    for hb in heartbeats:
        hb_time = hb.last_heartbeat_at
        if hb_time.tzinfo is None:
            hb_time = hb_time.replace(tzinfo=timezone.utc)
        age = max(0, int((now - hb_time).total_seconds()))

        if latest_hb is None:
            latest_hb = hb
        else:
            latest_time = latest_hb.last_heartbeat_at
            if latest_time.tzinfo is None:
                latest_time = latest_time.replace(tzinfo=timezone.utc)
            if hb_time > latest_time:
                latest_hb = hb

        if hb.last_successful_process_at:
            proc_time = hb.last_successful_process_at
            if proc_time.tzinfo is None:
                proc_time = proc_time.replace(tzinfo=timezone.utc)
            if latest_success_process_at is None or proc_time > latest_success_process_at:
                latest_success_process_at = proc_time

        if hb.status == "stopped":
            stopped_workers.append({"worker_id": hb.worker_id, "stop_reason": hb.stop_reason})
        elif age > threshold:
            stale_workers.append({"worker_id": hb.worker_id, "seconds_since_heartbeat": age})
        else:
            active_workers.append({"worker_id": hb.worker_id, "process_id": hb.process_id, "seconds_since_heartbeat": age})

    worker_status = "operational"
    heartbeat_str = None
    seconds_since = None
    worker_pid = None
    worker_id = None

    if latest_hb:
        worker_id = latest_hb.worker_id
        worker_pid = latest_hb.process_id
        hb_time = latest_hb.last_heartbeat_at
        if hb_time.tzinfo is None:
            hb_time = hb_time.replace(tzinfo=timezone.utc)
        heartbeat_str = hb_time.isoformat()
        seconds_since = max(0, int((now - hb_time).total_seconds()))

        if seconds_since > threshold or len(stale_workers) > 0:
            worker_status = "degraded"
        else:
            worker_status = "operational"
    else:
        worker_status = "idle"

    return {
        "status": worker_status,
        "process_role": settings.PROCESS_ROLE,
        "worker_enabled": settings.OUTBOX_WORKER_ENABLED,
        "active_worker_id": worker_id,
        "active_worker_pid": worker_pid,
        "last_heartbeat": heartbeat_str,
        "seconds_since_last_heartbeat": seconds_since,
        "last_successful_process_at": latest_success_process_at.isoformat() if latest_success_process_at else None,
        "active_workers": active_workers,
        "stale_workers": stale_workers,
        "stopped_workers": stopped_workers,
        "poll_interval_seconds": settings.OUTBOX_WORKER_INTERVAL_SECONDS,
        "lease_timeout_minutes": settings.OUTBOX_LEASE_TIMEOUT_MINUTES,
        "outbox_pending_count": pending_count,
        "outbox_reconciliation_required_count": reconciliation_count,
        "outbox_backlog": pending_count + reconciliation_count,
        "reconciliation_alert": reconciliation_count > 0,
    }


@app.get("/health/rate-limiter", tags=["system"])
def health_rate_limiter():
    """Rate limiter monitoring: inspects active backend (Redis vs in-memory), fail-closed policy, and connection health."""
    from backend.app.core.rate_limiter import get_rate_limiter_status
    return get_rate_limiter_status()


@app.get("/health/integrations", tags=["system"])
def health_integrations():
    """Integration health: performs bounded connectivity and authentication checks across external gateways."""
    import httpx
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    nipost_configured = bool(settings.NIPOST_API_KEY and (settings.NIPOST_API_URL or settings.NIPOST_API_BASE_URL))
    nipost_reachable = False
    nipost_authenticated = False
    nipost_last_check = None
    nipost_error_category = None

    if nipost_configured:
        base_url = settings.NIPOST_API_BASE_URL or settings.NIPOST_API_URL
        try:
            resp = httpx.get(
                f"{base_url.rstrip('/')}/health",
                headers={"Authorization": f"Bearer {settings.NIPOST_API_KEY}"},
                timeout=1.5,
            )
            nipost_reachable = True
            if resp.status_code in [200, 204]:
                nipost_authenticated = True
                nipost_last_check = now.isoformat()
            elif resp.status_code in [401, 403]:
                nipost_authenticated = False
                nipost_error_category = "authentication_failed"
            else:
                nipost_authenticated = True
                nipost_last_check = now.isoformat()
        except (httpx.ConnectError, httpx.TimeoutException):
            nipost_reachable = False
            nipost_authenticated = False
            nipost_error_category = "network_unreachable_or_timeout"
        except Exception:
            nipost_reachable = False
            nipost_authenticated = False
            nipost_error_category = "probe_exception"
    else:
        nipost_error_category = "unconfigured"

    # SMS Gateway Probe
    sms_configured = False
    sms_reachable = False
    sms_authenticated = False
    sms_last_check = None
    sms_error_category = None

    if settings.SMS_PROVIDER == "simulated":
        sms_configured = True
        sms_reachable = True
        sms_authenticated = True
        sms_last_check = now.isoformat()
    elif settings.SMS_PROVIDER == "termii":
        sms_configured = bool(settings.TERMII_API_KEY and settings.TERMII_SENDER_ID)
        if sms_configured:
            try:
                resp = httpx.get(
                    "https://api.ng.termii.com/api/get-balance",
                    params={"api_key": settings.TERMII_API_KEY},
                    timeout=1.5,
                )
                sms_reachable = True
                if resp.status_code == 200:
                    sms_authenticated = True
                    sms_last_check = now.isoformat()
                elif resp.status_code in [401, 403]:
                    sms_authenticated = False
                    sms_error_category = "authentication_failed"
                else:
                    sms_authenticated = True
                    sms_last_check = now.isoformat()
            except (httpx.ConnectError, httpx.TimeoutException):
                sms_reachable = False
                sms_authenticated = False
                sms_error_category = "network_unreachable_or_timeout"
            except Exception:
                sms_reachable = False
                sms_authenticated = False
                sms_error_category = "probe_exception"
        else:
            sms_error_category = "unconfigured"
    elif settings.SMS_PROVIDER == "twilio":
        sms_configured = bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_FROM_NUMBER)
        if sms_configured:
            try:
                resp = httpx.get(
                    f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}.json",
                    auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                    timeout=1.5,
                )
                sms_reachable = True
                if resp.status_code == 200:
                    sms_authenticated = True
                    sms_last_check = now.isoformat()
                elif resp.status_code in [401, 403]:
                    sms_authenticated = False
                    sms_error_category = "authentication_failed"
                else:
                    sms_authenticated = True
                    sms_last_check = now.isoformat()
            except (httpx.ConnectError, httpx.TimeoutException):
                sms_reachable = False
                sms_authenticated = False
                sms_error_category = "network_unreachable_or_timeout"
            except Exception:
                sms_reachable = False
                sms_authenticated = False
                sms_error_category = "probe_exception"
        else:
            sms_error_category = "unconfigured"

    from backend.app.core.rate_limiter import get_rate_limiter_status
    rate_limiter_info = get_rate_limiter_status()

    overall_status = "operational"
    if settings.ENVIRONMENT == "production":
        if not sms_configured or settings.SMS_PROVIDER == "simulated" or not sms_authenticated:
            overall_status = "degraded"
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": overall_status,
                    "error": "Production SMS gateway is not operational or failed authentication.",
                    "nipost": {
                        "configured": nipost_configured,
                        "reachable": nipost_reachable,
                        "authenticated": nipost_authenticated,
                        "last_successful_check": nipost_last_check,
                        "last_error_category": nipost_error_category,
                    },
                    "sms_gateway": {
                        "provider": settings.SMS_PROVIDER,
                        "configured": sms_configured,
                        "reachable": sms_reachable,
                        "authenticated": sms_authenticated,
                        "last_successful_check": sms_last_check,
                        "last_error_category": sms_error_category,
                    },
                    "rate_limiter": rate_limiter_info,
                },
            )

    return {
        "status": overall_status,
        "nipost": {
            "configured": nipost_configured,
            "reachable": nipost_reachable,
            "authenticated": nipost_authenticated,
            "last_successful_check": nipost_last_check,
            "last_error_category": nipost_error_category,
        },
        "sms_gateway": {
            "provider": settings.SMS_PROVIDER,
            "configured": sms_configured,
            "reachable": sms_reachable,
            "authenticated": sms_authenticated,
            "last_successful_check": sms_last_check,
            "last_error_category": sms_error_category,
        },
        "rate_limiter": rate_limiter_info,
    }
