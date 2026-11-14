"""Schemas package."""
from backend.app.schemas.common import APIResponse
from backend.app.schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    ProfileResponse,
)
from backend.app.schemas.postcode import (
    PostcodeRecordSchema,
    PostcodeLookupRequest,
    PostcodeLookupResponse,
    CleanseAddressRequest,
    CleanseAddressResponse,
)
from backend.app.schemas.operator import (
    OperatorBase,
    OperatorCreate,
    OperatorUpdate,
    OperatorResponse,
)
from backend.app.schemas.customer import (
    CustomerBase,
    CustomerCreate,
    CustomerResponse,
)
from backend.app.schemas.delivery import (
    DeliveryCreateRequest,
    DeliveryCreateResponse,
    DeliveryStatusUpdateRequest,
    DeliveryAssignRequest,
    DeliveryVerifyOTPRequest,
    DeliveryResponse,
    DeliveryPublicTrackingResponse,
    DeliveryEventResponse,
    NotificationDispatchPayload,
)

__all__ = [
    "APIResponse",
    "UserRegisterRequest",
    "UserLoginRequest",
    "TokenResponse",
    "ProfileResponse",
    "PostcodeRecordSchema",
    "PostcodeLookupRequest",
    "PostcodeLookupResponse",
    "CleanseAddressRequest",
    "CleanseAddressResponse",
    "OperatorBase",
    "OperatorCreate",
    "OperatorUpdate",
    "OperatorResponse",
    "CustomerBase",
    "CustomerCreate",
    "CustomerResponse",
    "DeliveryCreateRequest",
    "DeliveryCreateResponse",
    "DeliveryStatusUpdateRequest",
    "DeliveryAssignRequest",
    "DeliveryVerifyOTPRequest",
    "DeliveryResponse",
    "DeliveryPublicTrackingResponse",
    "DeliveryEventResponse",
    "NotificationDispatchPayload",
]
