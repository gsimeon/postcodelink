"""Delivery schemas."""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from backend.app.models.enums import DeliveryStatus, PostcodeStatus
from backend.app.schemas.operator import OperatorResponse


class DeliveryEventResponse(BaseModel):
    id: str
    delivery_id: str
    status: DeliveryStatus
    actor_name: str
    actor_role: str
    note: Optional[str] = None
    occurred_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeliveryCreateRequest(BaseModel):
    recipient_name: str = Field(..., min_length=2)
    recipient_phone: str = Field(..., min_length=7)
    destination_address: str = Field(..., min_length=3)
    destination_landmark: Optional[str] = None
    destination_area: str
    destination_state: str
    postcode_input: str
    package_description: str = Field(..., min_length=2)
    fee: float = Field(default=2500.0, ge=0)
    pickup_address: Optional[str] = None
    merchant_id: Optional[str] = None


class DeliveryStatusUpdateRequest(BaseModel):
    new_status: DeliveryStatus
    actor_name: str = "Merchant Admin"
    actor_role: str = "merchant"
    note: Optional[str] = None


class DeliveryAssignRequest(BaseModel):
    operator_id: str
    actor_name: str = "Merchant Dispatcher"


class DeliveryVerifyOTPRequest(BaseModel):
    otp: str = Field(..., min_length=4, max_length=6)
    recipient_phone: Optional[str] = None
    operator_id: Optional[str] = None
    note: Optional[str] = None


class DeliveryResponse(BaseModel):
    id: str
    merchant_id: Optional[str] = None
    operator_id: Optional[str] = None
    recipient_name: str
    recipient_phone: str
    destination_address: str
    destination_landmark: Optional[str] = None
    destination_area: str
    destination_state: str
    postcode_input: str
    postcode_status: PostcodeStatus
    verified_postcode: Optional[str] = None
    package_description: str
    fee: float
    pickup_address: Optional[str] = None
    status: DeliveryStatus
    lat: Optional[float] = None
    lng: Optional[float] = None
    otp: str  # Displayed to merchant/operator in dashboard
    otp_attempts: int
    otp_max_attempts: int
    pod_verified: bool
    pod_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    assigned_operator: Optional[OperatorResponse] = None
    events: List[DeliveryEventResponse] = []

    model_config = ConfigDict(from_attributes=True)


class DeliveryPublicTrackingResponse(BaseModel):
    id: str
    recipient_name: str
    recipient_phone_masked: str  # e.g. "080****3421"
    destination_address: str
    destination_landmark: Optional[str] = None
    destination_area: str
    destination_state: str
    postcode_status: PostcodeStatus
    verified_postcode: Optional[str] = None
    package_description: str
    fee: float
    status: DeliveryStatus
    lat: Optional[float] = None
    lng: Optional[float] = None
    otp_masked: str  # e.g. "***924"
    otp_attempts: int
    otp_max_attempts: int
    is_locked: bool
    lockout_remaining_minutes: Optional[int] = None
    pod_verified: bool
    created_at: datetime
    updated_at: datetime
    assigned_operator_name: Optional[str] = None
    events: List[DeliveryEventResponse] = []
