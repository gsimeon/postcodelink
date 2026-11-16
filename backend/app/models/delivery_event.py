"""Immutable Delivery Event audit log model."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SAEnum, event
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.models.enums import DeliveryStatus


class DeliveryEvent(Base):
    __tablename__ = "delivery_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    delivery_id = Column(String(32), ForeignKey("deliveries.id", ondelete="RESTRICT"), nullable=False, index=True)
    status = Column(SAEnum(DeliveryStatus), nullable=False)
    actor_name = Column(String(255), nullable=False)
    actor_role = Column(String(50), nullable=False)
    note = Column(String(500), nullable=True)
    occurred_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship
    delivery = relationship("Delivery", back_populates="events")


@event.listens_for(DeliveryEvent, "before_update")
def _prevent_delivery_event_update(mapper, connection, target):
    """Enforce append-only immutability on DeliveryEvent records."""
    raise ValueError("DeliveryEvent records are immutable audit logs and cannot be updated.")


@event.listens_for(DeliveryEvent, "before_delete")
def _prevent_delivery_event_delete(mapper, connection, target):
    """Enforce append-only immutability on DeliveryEvent records."""
    raise ValueError("DeliveryEvent records are immutable audit logs and cannot be deleted.")
