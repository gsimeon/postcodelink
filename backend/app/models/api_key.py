"""ApiKey model for merchant API key authentication and quota enforcement."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from backend.app.database import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    merchant_id = Column(String(36), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False, default="Default API Key")
    key_prefix = Column(String(16), nullable=False, index=True)  # Public prefix e.g. pl_live_a1b2
    hashed_key = Column(String(128), nullable=False, unique=True, index=True)  # Cryptographic hash
    monthly_quota = Column(Integer, nullable=False, default=10000)
    usage_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)

    # Relationships
    merchant = relationship("Profile", foreign_keys=[merchant_id])
