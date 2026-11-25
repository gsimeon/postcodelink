"""Postcode & address string normalization helpers."""
import re
from typing import Any, Dict, Optional

from backend.app.core.postcode_utils import (
    parse_digital_postcode_components,
    parse_legacy_3part_code,
)


def parse_national_digital_postcode(code: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse Nigeria's official 11-character 5-component national digital postcode via shared core utility."""
    return parse_digital_postcode_components(code)


def normalize_digital_postcode(code: Optional[str]) -> Optional[str]:
    """Normalize and format Nigerian digital postcodes into canonical format.
    Returns canonical format for 11-char national digital codes or 3-part local reference codes;
    returns None for legacy 6-digit conventional codes or invalid strings.
    """
    if not code or not isinstance(code, str):
        return None
    cleaned = code.strip().upper()
    nat = parse_digital_postcode_components(cleaned)
    if nat:
        return nat["canonical_code"]
    loc = parse_legacy_3part_code(cleaned)
    if loc:
        return loc
    return None


def normalize_string(text: Optional[str]) -> str:
    """Normalize string for consistent substring and regex matching."""
    if not text:
        return ""
    s = text.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s
