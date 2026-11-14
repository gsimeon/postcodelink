"""Pydantic schemas for Nigerian Postcode resolution and validation."""
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class PostcodeRecordSchema(BaseModel):
    code: str
    area: str
    state: str
    lga: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class PostcodeLookupRequest(BaseModel):
    state: Optional[str] = None
    area: Optional[str] = None
    code: Optional[str] = None


class PostcodeLookupResponse(BaseModel):
    source: str = "database"
    count: int
    matches: List[PostcodeRecordSchema]
    is_live_nipost: bool = False


class CleanseAddressRequest(BaseModel):
    address: str = Field(..., min_length=3)
    area: Optional[str] = None
    state: Optional[str] = None
    postcode: Optional[str] = None


class CleanseAddressResponse(BaseModel):
    original_address: str
    formatted_address: str
    area: str
    state: str
    lga: Optional[str] = None
    postcode: str
    postcode_status: str  # verified | unverified | estimated | conflict | invalid
    confidence: float
    # Explicit three-dimension validation
    postcode_valid: bool = False
    address_consistent: bool = False
    dispatch_confidence: float = 0.0
    source: str
    matched_record: Optional[PostcodeRecordSchema] = None
    changes_made: List[str] = []
