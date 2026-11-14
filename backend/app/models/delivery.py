"""Delivery order model with cryptographic tracking token and concurrency locking."""
import secrets
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, Float, Integer, DateTime, ForeignKey, Enum as SAEnum, Numeric
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.models.enums import DeliveryStatus, PostcodeStatus


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(String(32), primary_key=True, index=True)  # Human-readable reference: "PL-2026-AB12CD"
    idempotency_key = Column(String(128), index=True, nullable=True)
    tracking_token = Column(String(64), unique=True, index=True, nullable=False, default=lambda: secrets.token_urlsafe(24))
    merchant_id = Column(String(36), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    operator_id = Column(String(36), ForeignKey("operators.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Recipient details
    recipient_name = Column(String(255), nullable=False)
    recipient_phone = Column(String(32), nullable=False)
    
    # Destination & Postcode Link
    destination_address = Column(String(500), nullable=False)
    destination_landmark = Column(String(255), nullable=True)
    destination_area = Column(String(100), nullable=False)
    destination_state = Column(String(100), nullable=False)
    postcode_input = Column(String(20), nullable=False)
    postcode_status = Column(SAEnum(PostcodeStatus), nullable=False, default=PostcodeStatus.UNVERIFIED)
    verified_postcode = Column(String(10), nullable=True)
    
    # Package & Fee (Stored as Numeric with 2 decimal precision)
    package_description = Column(String(500), nullable=False)
    fee = Column(Numeric(10, 2, asdecimal=False), nullable=False, default=2500.0)
    pickup_address = Column(String(500), nullable=True)
    
    # Status & Coordinates
    status = Column(SAEnum(DeliveryStatus), nullable=False, default=DeliveryStatus.PENDING, index=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    
    # Security: Hashed PIN / OTP, Expiry & Brute-force protection
    otp_hash = Column(String(255), nullable=False)
    otp_expires_at = Column(DateTime, nullable=True)
    otp_attempts = Column(Integer, nullable=False, default=0)
    otp_max_attempts = Column(Integer, nullable=False, default=3)
    otp_locked_until = Column(DateTime, nullable=True)
    pod_verified = Column(Boolean, nullable=False, default=False)
    pod_note = Column(String(500), nullable=True)
    
    # Concurrency control & optimistic locking
    version = Column(Integer, nullable=False, default=1)
    
    estimated_delivery_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    merchant = relationship("Profile", back_populates="deliveries", foreign_keys=[merchant_id])
    assigned_operator = relationship("Operator", back_populates="deliveries", foreign_keys=[operator_id])
    events = relationship("DeliveryEvent", back_populates="delivery", cascade="all, delete-orphan", order_by="DeliveryEvent.occurred_at.asc()")
    outbox_notifications = relationship("NotificationOutbox", back_populates="delivery", cascade="all, delete-orphan")
