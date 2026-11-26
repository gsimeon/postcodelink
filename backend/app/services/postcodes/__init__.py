"""Modularized postcode intelligence sub-package."""
from backend.app.services.postcodes.evidence import (
    classify_verification_evidence,
    record_verification_evidence,
    validate_verification_evidence,
)
from backend.app.services.postcodes.normalization import (
    normalize_digital_postcode,
    normalize_string,
    parse_national_digital_postcode,
)

__all__ = [
    "classify_verification_evidence",
    "normalize_digital_postcode",
    "normalize_string",
    "parse_national_digital_postcode",
    "record_verification_evidence",
    "validate_verification_evidence",
]
