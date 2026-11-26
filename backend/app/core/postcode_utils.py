"""Core unified postcode utilities for Nigerian postal codes and digital location codes.

Centralizes:
1. Syntax validation and 5-component decomposition of Nigeria's official 11-character
   National Digital Postcode standard (SS-LL-DDD-AA-BB: State, LGA, District, Area, Building).
2. Legacy 6-digit postal code parsing.
3. Postcode normalization across canonical hyphenated and compact forms.
4. Free-text address postcode extraction.
"""
import re
from typing import Optional, Dict, Any, Tuple


# Regex specifications (Official NIPOST 5-component format: State[2A]-LGA[2N]-District[3AN]-Area[2A]-Building[2N])
CANONICAL_DIGITAL_REGEX = re.compile(
    r"^([A-Z]{2})-([0-9]{2})-([0-9A-Z]{3})-([A-Z]{2})-([0-9]{2})$"
)
CANONICAL_DIGITAL_SPACE_REGEX = re.compile(
    r"^([A-Z]{2}) ([0-9]{2}) ([0-9A-Z]{3}) ([A-Z]{2}) ([0-9]{2})$"
)
COMPACT_DIGITAL_REGEX = re.compile(
    r"^([A-Z]{2})([0-9]{2})([0-9A-Z]{3})([A-Z]{2})([0-9]{2})$"
)
LEGACY_6DIGIT_REGEX = re.compile(r"^\d{6}$")
LEGACY_3PART_LOCAL_REGEX = re.compile(r"^([A-Z]{3})-([A-Z0-9]{3,4})-([A-Z0-9]{4,5})$")

# Free-text address search patterns
TEXT_CANONICAL_DIGITAL_PATTERN = re.compile(
    r"\b([A-Za-z]{2}-[0-9]{2}-[0-9A-Za-z]{3}-[A-Za-z]{2}-[0-9]{2})\b"
)
TEXT_COMPACT_DIGITAL_PATTERN = re.compile(
    r"\b([A-Za-z]{2}[0-9]{2}[0-9A-Za-z]{3}[A-Za-z]{2}[0-9]{2})\b"
)
TEXT_LEGACY_3PART_PATTERN = re.compile(
    r"\b([A-Za-z]{3}-[A-Za-z0-9]{3,4}-[A-Za-z0-9]{4,5})\b"
)
TEXT_LABELLED_6DIGIT_PATTERN = re.compile(
    r"(?i)\b(?:postcode|postal\s*code|postal|zipcode|zip|p\.?o\.?\s*box|code)\s*[:#-]?\s*([1-9]\d{5})\b"
)
TEXT_LEGACY_6DIGIT_PATTERN = re.compile(r"\b([1-9]\d{5})\b")


def parse_digital_postcode_components(code: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse and validate the 5 canonical components of the Nigerian National Digital Postcode standard:
    SS-LL-DDD-AA-BB (2A-2N-3AN-2A-2N format)
    - State (SS): 2 uppercase alphabetic characters (e.g. 'EK', 'LA', 'FC')
    - Local Government (LL): 2 numeric digits (e.g. '01', '02', '10')
    - District (DDD): 3 alphanumeric characters (e.g. 'A03', 'A09', '100')
    - Area/Ward (AA): 2 uppercase alphabetic characters (e.g. 'FK', 'DB', 'EF')
    - Building/Unit (BB): 2 numeric digits (e.g. '01', '09', '34')
    
    Accepts:
    1. Canonical display format: SS-LL-DDD-AA-BB (15 characters with hyphens, e.g. 'EK-01-A03-FK-01') or SS LL DDD AA BB (15 characters with spaces)
    2. Normalized compact unseparated format: SSLLDDDAABB (11 characters, e.g. 'EK01A03FK01')
    
    Strictly rejects:
    - Malformed separator placement, mixed separators, or double hyphens.
    - Swapped or incorrect component widths (e.g. 3-char building or 1-char LGA).
    - Non-alphabetic state/area codes or non-numeric LGA/building codes.
    """
    if not code or not isinstance(code, str):
        return None
    clean = code.strip().upper()

    if "-" in clean:
        m = CANONICAL_DIGITAL_REGEX.match(clean)
        if not m:
            return None
    elif " " in clean:
        m = CANONICAL_DIGITAL_SPACE_REGEX.match(clean)
        if not m:
            return None
    else:
        m = COMPACT_DIGITAL_REGEX.match(clean)
        if not m:
            return None

    state, lga, district, area, building = m.groups()
    compact = f"{state}{lga}{district}{area}{building}"
    return {
        "state": state,
        "lga": lga,
        "district": district,
        "area": area,
        "building": building,
        "canonical_code": f"{state}-{lga}-{district}-{area}-{building}",
        "compact_code": compact,
        "total_length": 11,
    }


def parse_legacy_postcode(code: Optional[str]) -> Optional[str]:
    """Parse and validate a legacy 6-digit conventional Nigerian postal code (e.g. '100001')."""
    if not code or not isinstance(code, str):
        return None
    clean = code.strip()
    if LEGACY_6DIGIT_REGEX.match(clean):
        return clean
    return None


def parse_legacy_3part_code(code: Optional[str]) -> Optional[str]:
    """Parse local demonstration 3-part reference code (e.g. 'LAG-IKJ-0012' or 'lag ikj 0012')."""
    if not code or not isinstance(code, str):
        return None
    clean = re.sub(r"[\s\-]+", "-", code.strip().upper())
    m = LEGACY_3PART_LOCAL_REGEX.match(clean)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def is_well_formed_postcode(code: Optional[str]) -> bool:
    """Validate whether a Nigerian postcode string complies with national syntax standards:
    1. Legacy 6-digit numeric postal code (e.g. '100001', '900001').
    2. Official 11-character 5-component national digital postcode standard:
       Canonical: SS-LL-DDD-AA-BB (e.g. 'FC-02-A09-DB-09')
       Normalized: SSLLDDDAABB (e.g. 'FC02A09DB09')
    """
    if not code or not isinstance(code, str):
        return False
    clean = code.strip().upper()
    if parse_legacy_postcode(clean):
        return True
    if parse_digital_postcode_components(clean) is not None:
        return True
    return False


def normalize_postcode(code: Optional[str]) -> Optional[str]:
    """Normalize any recognized Nigerian postcode into its canonical display format."""
    if not code or not isinstance(code, str):
        return None
    clean = code.strip().upper()

    # 1. Official National 11-character digital postcode
    dig = parse_digital_postcode_components(clean)
    if dig:
        return dig["canonical_code"]

    # 2. Legacy 6-digit postal code
    leg = parse_legacy_postcode(clean)
    if leg:
        return leg

    # 3. Legacy 3-part local reference
    loc = parse_legacy_3part_code(clean)
    if loc:
        return loc

    return None


def extract_postcode_from_text(text: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    """Search and extract Nigerian postal codes embedded inside free-text delivery addresses.
    
    Returns:
    (normalized_code, postcode_type, national_components)
    - postcode_type: 'digital_location' | 'conventional_area' | None
    - national_components: dictionary of 5 components if digital, else None
    """
    if not text or not isinstance(text, str):
        return None, None, None

    clean = text.strip()

    # 1. Priority 1: Canonical 5-component digital postcode (SS-LL-DDD-AA-BB)
    match_canonical = TEXT_CANONICAL_DIGITAL_PATTERN.findall(clean)
    for candidate in match_canonical:
        components = parse_digital_postcode_components(candidate)
        if components:
            return components["canonical_code"], "digital_location", components

    # 2. Priority 2: Compact 11-character digital postcode (SSLLDDDAABB)
    match_compact = TEXT_COMPACT_DIGITAL_PATTERN.findall(clean)
    for candidate in match_compact:
        components = parse_digital_postcode_components(candidate)
        if components:
            return components["canonical_code"], "digital_location", components

    # 3. Priority 3: Local demonstration 3-part reference (e.g. LAG-IKJ-0012)
    match_3part = TEXT_LEGACY_3PART_PATTERN.findall(clean)
    for candidate in match_3part:
        norm = parse_legacy_3part_code(candidate)
        if norm:
            return norm, "digital_location", None

    # 4. Priority 4: Explicitly labelled 6-digit conventional postal code (e.g. 'Postcode: 100001')
    match_labelled = TEXT_LABELLED_6DIGIT_PATTERN.findall(clean)
    if match_labelled:
        unique_labelled = list(dict.fromkeys(match_labelled))
        if len(unique_labelled) == 1:
            return unique_labelled[0], "conventional_area", None
        # Conflicting labelled postal codes in same address -> ambiguous
        return None, None, None

    # 5. Priority 5: Standalone unlabelled 6-digit conventional code
    match_6digit = TEXT_LEGACY_6DIGIT_PATTERN.findall(clean)
    if match_6digit:
        unique_unlabelled = list(dict.fromkeys(match_6digit))
        # Ambiguity Guard: If multiple distinct 6-digit numbers exist without a label
        # (e.g. tracking ref and building number), do not silently select an arbitrary one!
        if len(unique_unlabelled) == 1:
            return unique_unlabelled[0], "conventional_area", None
        return None, None, None

    return None, None, None
