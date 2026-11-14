"""Customer / Recipient directory model with tenant scoping."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from backend.app.database import Base


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("merchant_id", "phone", name="uq_merchant_customer_phone"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    merchant_id = Column(String(36), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    phone = Column(String(32), index=True, nullable=False)
    email = Column(String(255), nullable=True)
    default_address = Column(String(500), nullable=False)
    area = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    postcode = Column(String(10), nullable=True)
    total_orders = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship
    merchant = relationship("Profile")
