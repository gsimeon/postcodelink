"""Pydantic schemas for Nigerian Postcode resolution and validation."""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class PostcodeRecordSchema(BaseModel):
    code: str
    area: Optional[str] = "Unspecified Area"
    state: Optional[str] = "Nigeria"
    lga: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    postcode_type: str = "conventional_area"  # conventional_area | digital_location
    postcode_category: Optional[str] = "local_address_reference"  # legacy_postal_code | official_digital_postcode | local_address_reference
    building_reference: Optional[str] = None
    verification_status: Optional[str] = "local_reference"  # official_verified | local_reference | synthetic_demo | unverified
    provenance: Optional[str] = "PostcodeLink Local Reference Dataset"
    dataset_version: Optional[str] = None
    verified_at: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    evidence_id: Optional[str] = None
    verification_method: Optional[str] = None
    address_metadata_source: Optional[str] = None
    source_owner: Optional[str] = "PostcodeLink"
    source_type: Optional[str] = "local_reference"
    national_components: Optional[dict] = None

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
    is_partial_verification: bool = False
    service_type: Optional[str] = None
    dataset_version: Optional[str] = None
    api_integration_version: str = "2026.1"
    provenance: str = "PostcodeLink Local Reference Dataset"
    lookup_status: str = "local_reference"  # official_verified | not_found | fallback_reference | local_reference
    verification_source: str = "local_nipost_reference_dataset"
    verification_status: str = "local_reference"  # official_verified | local_reference | unverified
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    upstream_status: Optional[str] = None
    upstream_error: Optional[str] = None
    is_partial_verification: bool = False
    evidence_id: Optional[str] = None
    verification_method: Optional[str] = None
    address_metadata_source: Optional[str] = None
    valid_until: Optional[datetime] = None


class CleanseAddressRequest(BaseModel):
    address: str = Field(..., min_length=3)
    area: Optional[str] = None
    state: Optional[str] = None
    postcode: Optional[str] = None
    strict: bool = False
    live_verify: bool = False


class CleanseAddressResponse(BaseModel):
    original_address: str
    formatted_address: str
    area: str
    state: str
    lga: Optional[str] = None
    postcode: str
    postcode_type: str = "conventional_area"  # conventional_area | digital_location
    postcode_category: Optional[str] = "legacy_postal_code"  # legacy_postal_code | official_digital_postcode | local_address_reference
    resolution_level: str = "area_district"  # area_district | building_location
    postcode_status: str  # verified | local_match | unverified | estimated | conflict | invalid
    verification_status: Optional[str] = "local_reference"
    confidence: float
    # Explicit three-dimension validation
    postcode_valid: bool = False
    address_consistent: bool = False
    dispatch_confidence: float = 0.0
    source: str
    matched_record: Optional[PostcodeRecordSchema] = None
    changes_made: List[str] = []
    provenance: Optional[str] = "PostcodeLink Local Reference Dataset"
    source_owner: Optional[str] = "PostcodeLink"
    source_type: Optional[str] = "local_reference"
    national_components: Optional[dict] = None
    checked_against_nipost: bool = False
    is_live_nipost: bool = False
    verification_source: str = "local_nipost_reference_dataset"
    fallback_used: bool = False
    upstream_status: Optional[str] = None
    upstream_error: Optional[str] = None
    is_partial_verification: bool = False
    evidence_id: Optional[str] = None
    verification_method: Optional[str] = None
    address_metadata_source: Optional[str] = None
    valid_until: Optional[datetime] = None
    dataset_version: Optional[str] = None
    api_integration_version: str = "2026.1"
