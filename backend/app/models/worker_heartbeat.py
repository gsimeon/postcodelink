"""Persistent worker heartbeat tracking model for cross-process health monitoring."""
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime
from backend.app.database import Base


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id = Column(String(64), primary_key=True)
    process_id = Column(Integer, nullable=True)
    worker_role = Column(String(32), nullable=False, default="outbox_worker")
    hostname = Column(String(64), nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    status = Column(String(32), nullable=False, default="active")  # active | idle | busy | stopped
    active_jobs_count = Column(Integer, nullable=False, default=0)
    processed_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
