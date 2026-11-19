"""Pydantic schemas for Nigerian Postcode resolution and validation."""
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, model_validator

VerificationMode = Literal["local_standardization", "nipost_validate", "nipost_strict"]


class PostcodeRecordSchema(BaseModel):
    code: str
    area: Optional[str] = None
    state: Optional[str] = None
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
    upstream_contacted: bool = False
    postcode_exists: Optional[bool] = None
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
    verification_mode: Optional[VerificationMode] = None  # "local_standardization" | "nipost_validate" | "nipost_strict"

    @model_validator(mode="after")
    def validate_mode_and_legacy_flags(self) -> "CleanseAddressRequest":
        fields_set = self.model_fields_set
        if self.verification_mode == "local_standardization":
            if self.strict or ("strict" in fields_set and self.strict):
                raise ValueError(
                    "Contradictory parameters: verification_mode='local_standardization' cannot be combined with strict=True. "
                    "Local standardization is an offline mode with zero upstream verification."
                )
            if self.live_verify or ("live_verify" in fields_set and self.live_verify):
                raise ValueError(
                    "Contradictory parameters: verification_mode='local_standardization' cannot be combined with live_verify=True. "
                    "Local standardization is an offline mode with zero upstream verification."
                )
        elif self.verification_mode == "nipost_validate":
            if "strict" in fields_set and self.strict:
                raise ValueError(
                    "Contradictory parameters: verification_mode='nipost_validate' allows fallback and cannot be combined with strict=True. "
                    "Use 'nipost_strict' for fail-closed verification."
                )
        elif self.verification_mode == "nipost_strict":
            if "strict" in fields_set and not self.strict:
                raise ValueError(
                    "Contradictory parameters: verification_mode='nipost_strict' requires fail-closed behavior and cannot be combined with strict=False."
                )
        return self


class CleanseAddressResponse(BaseModel):
    original_address: str
    formatted_address: str
    area: Optional[str] = None
    state: Optional[str] = None
    lga: Optional[str] = None
    postcode: str
    postcode_type: str = "conventional_area"  # conventional_area | digital_location
    postcode_category: Optional[str] = "legacy_postal_code"  # legacy_postal_code | official_digital_postcode | local_address_reference
    resolution_level: str = "area_district"  # area_district | building_location
    postcode_status: str  # verified | local_match | unverified | estimated | conflict | invalid
    verification_status: Optional[str] = "local_reference"
    verification_mode: VerificationMode = "nipost_validate"  # Effective mode applied
    
    # Internal heuristic match quality (explicitly labeled as internal heuristic, NOT delivery probability)
    confidence: float
    dispatch_confidence: float = 0.0
    match_quality_score: float = 0.0

    # Factual trust indicators
    postcode_valid: bool = False
    postcode_exists: Optional[bool] = None  # True if confirmed upstream, False if rejected/not found, None if unverified/offline
    address_consistent: bool = False
    upstream_contacted: bool = False

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
    fallback_reason: Optional[str] = None
    upstream_status: Optional[str] = None
    upstream_error: Optional[str] = None
    is_partial_verification: bool = False
    evidence_id: Optional[str] = None
    verification_method: Optional[str] = None
    address_metadata_source: Optional[str] = None
    valid_until: Optional[datetime] = None
    dataset_version: Optional[str] = None
    api_integration_version: str = "2026.1"


class CoverageReportResponse(BaseModel):
    edition: str = "Local Demonstration & Reference Edition"
    version: str = "2024.2"
    scope_states_count: int
    states_covered: List[str]
    states_in_dataset_metadata: List[str] = []
    states_with_active_records: List[str] = []
    states_with_verified_records: List[str] = []
    states_with_only_demo_records: List[str] = []
    total_reference_records: int
    records_per_state: Dict[str, int]
    records_with_coordinates: int
    records_with_verified_provenance: int = 0
    records_with_valid_evidence: int = 0
    records_with_expired_evidence: int = 0
    records_with_rejected_evidence: int = 0
    records_with_incomplete_evidence: int = 0
    records_with_invalid_evidence: int = 0
    records_with_complete_metadata: int = 0
    legacy_six_digit_records: int = 0
    national_digital_postcode_records: int = 0
    local_demonstration_fixtures: int = 0
    digital_building_level_records: int = 0
    upstream_integration: Dict[str, Any]
