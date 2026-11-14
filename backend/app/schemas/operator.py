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


class OperatorDirectoryResponse(BaseModel):
    """Restricted operator directory for merchant dispatch views.
    
    Protects fleet privacy: omits personal telephone numbers, exact GPS coordinates,
    and internal delivery counters.
    """
    id: str
    business_name: str
    vehicle_type: VehicleType
    service_areas: List[str] = Field(default_factory=list)
    is_available: bool
    rating: float
    has_capacity: bool = True

    model_config = ConfigDict(from_attributes=True)


class OperatorAssignedResponse(BaseModel):
    """Operator details revealed to a merchant only after delivery assignment."""
    id: str
    business_name: str
    phone: str
    vehicle_type: VehicleType
    rating: float

    model_config = ConfigDict(from_attributes=True)


class OperatorResponse(OperatorBase):
    id: str
    profile_id: Optional[str] = None
    rating: float
    completed_deliveries: int
    active_deliveries_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
