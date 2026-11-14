"""Operator / Courier fleet model."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, Float, Integer, DateTime, ForeignKey, Enum as SAEnum, JSON
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.models.enums import VehicleType


class Operator(Base):
    __tablename__ = "operators"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    profile_id = Column(String(36), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True)
    business_name = Column(String(255), nullable=False)
    phone = Column(String(32), nullable=False)
    vehicle_type = Column(SAEnum(VehicleType), nullable=False, default=VehicleType.MOTORCYCLE)
    service_areas = Column(JSON, nullable=False, default=list)  # list of strings e.g. ["Ikeja", "Victoria Island"]
    is_available = Column(Boolean, nullable=False, default=True)
    rating = Column(Float, nullable=False, default=5.0)
    completed_deliveries = Column(Integer, nullable=False, default=0)
    active_deliveries_count = Column(Integer, nullable=False, default=0)
    current_lat = Column(Float, nullable=True)
    current_lng = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    profile = relationship("Profile", back_populates="operators")
    deliveries = relationship("Delivery", back_populates="assigned_operator", foreign_keys="Delivery.operator_id")

