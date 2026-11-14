"""Notification Outbox model for durable, asynchronous delivery notifications."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.services.notification_service import NotificationDeliveryStatus


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    delivery_id = Column(String(32), ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(32), nullable=False, default="SMS")
    recipient_phone = Column(String(32), nullable=False)
    provider = Column(String(32), nullable=False, default="simulated")
    status = Column(
        SAEnum(NotificationDeliveryStatus, name="notificationdeliverystatus"),
        nullable=False,
        default=NotificationDeliveryStatus.QUEUED,
        index=True,
    )
    notification_type = Column(String(32), nullable=False, default="otp_delivery_pin")
    idempotency_key = Column(String(64), unique=True, nullable=True, index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    next_attempt_at = Column(DateTime, nullable=True, index=True)
    locked_at = Column(DateTime, nullable=True)
    locked_by = Column(String(64), nullable=True)
    failure_classification = Column(String(32), nullable=True)
    error_details = Column(String(500), nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    sent_at = Column(DateTime, nullable=True)

    # Relationships
    delivery = relationship("Delivery", back_populates="outbox_notifications")
