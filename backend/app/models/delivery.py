"""Delivery order model."""
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, Float, Integer, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.models.enums import DeliveryStatus, PostcodeStatus


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(String(32), primary_key=True, index=True)  # e.g. "PL-2026-AB12CD"
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
    
    # Package & Fee
    package_description = Column(String(500), nullable=False)
    fee = Column(Float, nullable=False, default=2500.0)
    pickup_address = Column(String(500), nullable=True)
    
    # Status & Coordinates
    status = Column(SAEnum(DeliveryStatus), nullable=False, default=DeliveryStatus.PENDING, index=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    
    # Security: Delivery PIN / OTP & Brute-force protection
    otp = Column(String(6), nullable=False)
    otp_attempts = Column(Integer, nullable=False, default=0)
    otp_max_attempts = Column(Integer, nullable=False, default=3)
    otp_locked_until = Column(DateTime, nullable=True)
    pod_verified = Column(Boolean, nullable=False, default=False)
    pod_note = Column(String(500), nullable=True)
    
    estimated_delivery_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    merchant = relationship("Profile", back_populates="deliveries", foreign_keys=[merchant_id])
    assigned_operator = relationship("Operator", back_populates="deliveries", foreign_keys=[operator_id])
    events = relationship("DeliveryEvent", back_populates="delivery", cascade="all, delete-orphan", order_by="DeliveryEvent.occurred_at.asc()")
