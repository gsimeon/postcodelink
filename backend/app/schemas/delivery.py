"""Delivery schemas with privacy preservation and tokenized public tracking."""
from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, model_validator
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
    postcode_input: Optional[str] = None
    postcode: Optional[str] = None
    package_description: str = Field(default="Standard Package", min_length=2)
    fee: float = Field(default=2500.0, ge=0)
    pickup_address: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_postcode_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            p_in = data.get("postcode_input")
            p_code = data.get("postcode")
            if not p_in and p_code:
                data["postcode_input"] = str(p_code)
            elif not p_code and p_in:
                data["postcode"] = str(p_in)
            if not data.get("postcode_input"):
                data["postcode_input"] = ""
        return data


class DeliveryStatusUpdateRequest(BaseModel):
    new_status: DeliveryStatus
    note: Optional[str] = None


class DeliveryAssignRequest(BaseModel):
    operator_id: str


class DeliveryVerifyOTPRequest(BaseModel):
    otp: str = Field(..., min_length=4, max_length=6)
    note: Optional[str] = None


class DeliveryResponse(BaseModel):
    id: str
    tracking_token: str
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
    # NOTE: PIN is strictly absent from all delivery responses
    otp_attempts: int
    otp_max_attempts: int
    pod_verified: bool
    pod_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    assigned_operator: Optional[OperatorResponse] = None
    events: List[DeliveryEventResponse] = []

    model_config = ConfigDict(from_attributes=True)


class NotificationDispatchPayload(BaseModel):
    recipient_phone: str
    status: str = "DISPATCHED"
    channel: str = "SMS / WhatsApp Direct Gateway"
    message_preview: str  # e.g. "PIN dispatched directly to recipient mobile; not exposed in API"


class DeliveryCreateResponse(BaseModel):
    delivery: DeliveryResponse
    notification_dispatch: NotificationDispatchPayload


class PublicTrackingEvent(BaseModel):
    status: DeliveryStatus
    occurred_at: datetime


class DeliveryPublicTrackingResponse(BaseModel):
    id: str
    recipient_name_masked: str  # e.g. "C**** N****"
    recipient_phone_masked: str  # e.g. "080****3421"
    destination_general_location: str  # e.g. "Lekki Phase 1, Lagos"
    postcode_status: PostcodeStatus
    verified_postcode: Optional[str] = None
    status: DeliveryStatus
    requires_pin_confirmation: bool = True
    otp_attempts: int
    otp_max_attempts: int
    is_locked: bool
    lockout_remaining_minutes: Optional[int] = None
    pod_verified: bool
    created_at: datetime
    updated_at: datetime
    assigned_operator_name: Optional[str] = None
    timeline: List[PublicTrackingEvent] = []


class BulkItemResult(BaseModel):
    index: int
    success: bool
    reference: Optional[str] = None
    delivery: Optional[DeliveryResponse] = None
    error: Optional[str] = None


class DeliveryBulkCreateResponse(BaseModel):
    batch_id: Optional[str] = None
    total_items: int
    successful_count: int
    failed_count: int
    results: List[BulkItemResult]
