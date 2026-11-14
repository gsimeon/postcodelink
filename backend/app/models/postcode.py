"""Postcode Directory model for official Nigerian postcodes."""
import uuid
from sqlalchemy import Column, String, Float, Boolean
from backend.app.database import Base


class PostcodeDirectory(Base):
    __tablename__ = "postcodes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String(10), nullable=False, index=True)
    area = Column(String(100), nullable=False, index=True)
    state = Column(String(100), nullable=False, index=True)
    lga = Column(String(100), nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    postcode_type = Column(String(24), nullable=False, default="conventional_area")
    building_reference = Column(String(64), nullable=True)
    provenance = Column(String(128), nullable=False, default="NIPOST Official Digital Postcode Directory")
    dataset_version = Column(String(32), nullable=False, default="2024.2")
    is_active = Column(Boolean, nullable=False, default=True)

