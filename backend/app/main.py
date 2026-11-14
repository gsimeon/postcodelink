"""PostcodeLink Nigeria - FastAPI Main Application."""
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
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
