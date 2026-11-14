"""Postcode Directory model for official Nigerian postcodes."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Boolean, DateTime
from backend.app.database import Base


class PostcodeDirectory(Base):
    __tablename__ = "postcodes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String(20), nullable=False, index=True)
    area = Column(String(100), nullable=False, index=True)
    state = Column(String(100), nullable=False, index=True)
    lga = Column(String(100), nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    postcode_type = Column(String(32), nullable=False, default="conventional_area")  # conventional_area | digital_location
    building_reference = Column(String(64), nullable=True)
    verification_status = Column(String(32), nullable=False, default="local_reference")  # official_verified | local_reference | synthetic_demo | unverified
    provenance = Column(String(128), nullable=False, default="Local Verification Dataset")
    dataset_version = Column(String(32), nullable=False, default="2024.2")
    verified_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    @property
    def postcode_category(self) -> str:
        """Categorize into official national digital postcode vs legacy 6-digit postal code."""
        if self.postcode_type in ["digital_location", "official_digital_postcode"] or (self.code and len(self.code) > 6):
            return "official_digital_postcode"
        return "legacy_postal_code"

