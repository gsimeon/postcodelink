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
    is_active = Column(Boolean, nullable=False, default=True)

