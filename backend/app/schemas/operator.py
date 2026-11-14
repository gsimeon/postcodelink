"""Operator schemas."""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from backend.app.models.enums import VehicleType


class OperatorBase(BaseModel):
    business_name: str = Field(..., min_length=2)
    phone: str = Field(..., min_length=7)
    vehicle_type: VehicleType = VehicleType.MOTORCYCLE
    service_areas: List[str] = Field(default_factory=list)
    is_available: bool = True
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None


class OperatorCreate(OperatorBase):
    profile_id: Optional[str] = None


class OperatorUpdate(BaseModel):
    business_name: Optional[str] = None
    phone: Optional[str] = None
    vehicle_type: Optional[VehicleType] = None
    service_areas: Optional[List[str]] = None
    is_available: Optional[bool] = None
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None


class OperatorResponse(OperatorBase):
    id: str
    profile_id: Optional[str] = None
    rating: float
    completed_deliveries: int
    active_deliveries_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
