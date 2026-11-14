"""Profile model for system users: merchants, operators, admins."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Enum as SAEnum
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.models.enums import AppRole


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    full_name = Column(String(255), nullable=False)
    role = Column(SAEnum(AppRole), nullable=False, default=AppRole.MERCHANT)
    phone = Column(String(32), nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    business_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    operators = relationship("Operator", back_populates="profile", cascade="all, delete-orphan")
    deliveries = relationship("Delivery", back_populates="merchant", foreign_keys="Delivery.merchant_id")
