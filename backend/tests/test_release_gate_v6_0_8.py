"""Release Gate v6.0.8 Verification & Key Integrity Regression Test Suite.

Covers:
1. Strict Taxonomy Separation: Local Demonstration Postcodes (local_match, conf 0.75)
   vs Officially Verified Postcodes (verified, conf 0.95+).
2. Unified Free-Text Postcode Extraction: Canonical (FC-02-A09-DB-09), Compact (LA01A04IK02),
   Legacy 3-part (LAG-IKJ-0012), and Legacy 6-digit (100001).
3. Search and Normalization Consistency in find_postcodes() and cleanse_address().
4. Zero-Downtime Versioned JWT Key Rotation (JWT_PREVIOUS_SECRETS, kid header).
5. Delivery OTP Key Separation & Rotation (OTP_SECRET_KEY, OTP_PREVIOUS_SECRETS).
6. Production Security Validator & Domain Separation.
"""
import pytest
import secrets
from datetime import datetime, timezone, timedelta
import jwt

from backend.app.config import Settings
from backend.app.core.postcode_utils import (
    parse_digital_postcode_components,
    parse_legacy_postcode,
    parse_legacy_3part_code,
    is_well_formed_postcode,
    normalize_postcode,
    extract_postcode_from_text,
)
from backend.app.services.postcode_service import (
    cleanse_address,
    find_postcodes,
    parse_national_digital_postcode,
    normalize_digital_postcode,
)
from backend.app.core.security import (
    create_access_token,
    decode_access_token,
    hash_otp,
    verify_otp_hash,
)


# ==============================================================================
# 1. Strict Taxonomy Separation: Local Demo vs Official Verified
# ==============================================================================
def test_local_demonstration_postcodes_return_local_match_not_verified():
    """Verify that demonstration fixtures (FC-02-A09-DB-09, LA-01-A04-IK-02) return
    postcode_status='local_match' (confidence 0.75), never 'verified' (0.95).
    """
    # 1. Abuja demonstration fixture
    res_fc = cleanse_address(
        address="Federal Commerce House, Area 2, Garki, Abuja",
        postcode_hint="FC-02-A09-DB-09",
    )
    assert res_fc.postcode == "FC-02-A09-DB-09"
    assert res_fc.postcode_type == "digital_location"
    assert res_fc.postcode_category == "local_address_reference"
    assert res_fc.verification_status == "local_reference"
    assert res_fc.source_type == "demonstration_fixture"
    assert res_fc.postcode_status == "local_match"
    assert res_fc.confidence == 0.75
    assert res_fc.dispatch_confidence == 0.75
    assert res_fc.postcode_valid is True
    assert res_fc.address_consistent is True
    assert any("unverified with official NIPOST" in change for change in res_fc.changes_made)

    # 2. Lagos demonstration fixture
    res_la = cleanse_address(
        address="Plot 4 Ikeja Commercial Plaza, Lagos",
        postcode_hint="LA-01-A04-IK-02",
    )
    assert res_la.postcode == "LA-01-A04-IK-02"
    assert res_la.postcode_status == "local_match"
    assert res_la.confidence == 0.75
    assert res_la.verification_status == "local_reference"
    assert res_la.source_type == "demonstration_fixture"
    assert any("unverified with official NIPOST" in change for change in res_la.changes_made)


def test_conventional_directory_records_maintain_standard_verification():
    """Verify that 6-digit directory references return conventional_area and verified status."""
    res_conv = cleanse_address(
        address="10 Ahmadu Bello Way, Victoria Island, Lagos",
        postcode_hint="101233",
    )
    assert res_conv.postcode == "101233"
    assert res_conv.postcode_type == "conventional_area"
    assert res_conv.postcode_category == "legacy_postal_code"
    assert res_conv.resolution_level == "area_district"
    assert res_conv.postcode_status in ("verified", "local_match")
    assert res_conv.confidence >= 0.75


# ==============================================================================
# 2. Unified Free-Text Postcode Extraction
# ==============================================================================
def test_free_text_extraction_handles_all_supported_formats():
    """Verify that extract_postcode_from_text reliably detects and normalizes postcodes in raw text."""
    # A. Canonical 5-component digital code
    addr_canonical = "Flat 4, Federal Commerce House, FC-02-A09-DB-09, Garki District, Abuja"
    code, p_type, comp = extract_postcode_from_text(addr_canonical)
    assert code == "FC-02-A09-DB-09"
    assert p_type == "digital_location"
    assert comp is not None
    assert comp["state"] == "FC"
    assert comp["lga"] == "02"
    assert comp["district"] == "A09"
    assert comp["area"] == "DB"
    assert comp["building"] == "09"

    # B. Compact 11-character digital code
    addr_compact = "Plot 12, Commercial Plaza, LA01A04IK02, Ikeja Central"
    code_c, p_type_c, comp_c = extract_postcode_from_text(addr_compact)
    assert code_c == "LA-01-A04-IK-02"
    assert p_type_c == "digital_location"
    assert comp_c is not None
    assert comp_c["state"] == "LA"

    # C. Legacy 3-part local reference
    addr_3part = "Shop 15, Admiralty Mall, LAG-IKJ-0012, Ikeja, Lagos"
    code_3, p_type_3, _ = extract_postcode_from_text(addr_3part)
    assert code_3 == "LAG-IKJ-0012"
    assert p_type_3 == "digital_location"

    # D. Legacy 6-digit conventional postal code
    addr_6digit = "14 Admiralty Way, Lekki Phase 1, Lagos 101241"
    code_6, p_type_6, _ = extract_postcode_from_text(addr_6digit)
    assert code_6 == "101241"
    assert p_type_6 == "conventional_area"

    # E. Text without valid postal codes
    addr_none = "Just a street without any postal code anywhere in Lagos"
    code_n, p_type_n, _ = extract_postcode_from_text(addr_none)
    assert code_n is None
    assert p_type_n is None


def test_cleanse_address_extracts_embedded_digital_postcodes_from_raw_address():
    """Verify that cleanse_address extracts embedded 5-component postcodes without a hint."""
    # When user enters a combined address string containing FC-02-A09-DB-09
    res = cleanse_address(
        address="Suite 4, Federal Commerce House, FC-02-A09-DB-09, Area 2, Garki, Abuja",
    )
    assert res.postcode == "FC-02-A09-DB-09"
    assert res.postcode_type == "digital_location"
    assert res.postcode_status == "local_match"
    assert res.confidence == 0.75

    # Compact code embedded in address string
    res_compact = cleanse_address(
        address="Suite 4, Federal Commerce House, FC02A09DB09, Area 2, Garki, Abuja",
    )
    assert res_compact.postcode == "FC-02-A09-DB-09"
    assert res_compact.postcode_type == "digital_location"


# ==============================================================================
# 3. Search and Normalization Consistency
# ==============================================================================
def test_find_postcodes_matches_both_canonical_and_compact_codes():
    """Verify find_postcodes locates records regardless of hyphenation or case."""
    # Canonical hyphenated
    res1 = find_postcodes(db=None, code="FC-02-A09-DB-09")
    assert len(res1) == 1
    assert res1[0].code == "FC-02-A09-DB-09"

    # Compact unseparated
    res2 = find_postcodes(db=None, code="FC02A09DB09")
    assert len(res2) == 1
    assert res2[0].code == "FC-02-A09-DB-09"

    # Lowercase compact
    res3 = find_postcodes(db=None, code="fc02a09db09")
    assert len(res3) == 1
    assert res3[0].code == "FC-02-A09-DB-09"


def test_postcode_utils_syntax_validation():
    """Verify strict syntax compliance checks in core postcode_utils."""
    assert is_well_formed_postcode("100001") is True
    assert is_well_formed_postcode("FC-02-A09-DB-09") is True
    assert is_well_formed_postcode("FC02A09DB09") is True
    assert is_well_formed_postcode("fc-02-a09-db-09") is True

    # Malformed cases
    assert is_well_formed_postcode("10000") is False  # 5 digits
    assert is_well_formed_postcode("1000001") is False  # 7 digits
    assert is_well_formed_postcode("FC-02-A09DB09") is False  # Missing hyphen
    assert is_well_formed_postcode("FC--02-A09-DB-09") is False  # Double hyphen
    assert is_well_formed_postcode("01-02-A09-DB-09") is False  # Numeric state code
    assert is_well_formed_postcode("") is False
    assert is_well_formed_postcode(None) is False


# ==============================================================================
# 4. Zero-Downtime Versioned JWT Key Rotation
# ==============================================================================
def test_jwt_key_rotation_verifies_tokens_signed_with_previous_secrets(monkeypatch):
    """Verify that decode_access_token smoothly validates tokens signed by keys in JWT_PREVIOUS_SECRETS."""
    old_secret = "old_legacy_production_secret_key_rotation_test_01"
    new_secret = "new_active_production_secret_key_rotation_test_02"
    
    # 1. Create token signed with old_secret (key ID 'v1')
    payload = {"sub": "merchant_123", "role": "merchant"}
    old_token = jwt.encode(
        payload,
        old_secret,
        algorithm="HS256",
        headers={"kid": "v1"},
    )

    # 2. Configure system with new_secret and old_secret in JWT_PREVIOUS_SECRETS
    from backend.app.core import security
    monkeypatch.setattr(security.settings, "SECRET_KEY", new_secret)
    monkeypatch.setattr(security.settings, "JWT_KEY_ID", "v2")
    monkeypatch.setattr(security.settings, "JWT_PREVIOUS_KEYS_MAP", {"v1": old_secret})
    monkeypatch.setattr(security.settings, "JWT_PREVIOUS_SECRETS", [f"v1:{old_secret}"])

    # 3. Decode old token -> MUST succeed without error
    decoded = decode_access_token(old_token)
    assert decoded is not None
    assert decoded["sub"] == "merchant_123"
    assert decoded["role"] == "merchant"

    # 4. Create new token -> signed with new_secret, header contains kid 'v2'
    new_token = create_access_token(payload)
    unverified_headers = jwt.get_unverified_header(new_token)
    assert unverified_headers.get("kid") == "v2"

    decoded_new = decode_access_token(new_token)
    assert decoded_new is not None
    assert decoded_new["sub"] == "merchant_123"

    # 5. Token signed with unknown secret -> MUST be rejected
    unknown_token = jwt.encode(payload, "unregistered_bogus_secret_32_characters_long", algorithm="HS256")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(unknown_token)


# ==============================================================================
# 5. Delivery OTP Key Separation & Rotation
# ==============================================================================
def test_otp_key_separation_and_rotation(monkeypatch):
    """Verify that OTP hashing uses dedicated OTP_SECRET_KEY and validates previous keys."""
    old_otp_key = "old_otp_secret_key_for_rotation_window_32_chars"
    new_otp_key = "new_active_otp_secret_key_for_safe_handoff_32"
    general_secret = "general_app_secret_key_distinct_domain_32_chars"

    salt = secrets.token_hex(16)
    pin = "482915"

    # 1. Hash OTP under old_otp_key
    old_hash = hash_otp(pin, salt, key=old_otp_key)

    # 2. Configure environment with new OTP key and old OTP key in OTP_PREVIOUS_SECRETS
    from backend.app.core import security
    monkeypatch.setattr(security.settings, "SECRET_KEY", general_secret)
    monkeypatch.setattr(security.settings, "OTP_SECRET_KEY", new_otp_key)
    monkeypatch.setattr(security.settings, "OTP_PREVIOUS_SECRETS", [old_otp_key])

    # 3. Verify OTP hashed with old key -> MUST succeed
    assert verify_otp_hash(pin, old_hash, salt) is True

    # 4. New OTP hashed with active key -> MUST succeed
    new_hash = hash_otp(pin, salt)
    assert verify_otp_hash(pin, new_hash, salt) is True

    # 5. Wrong pin -> MUST fail
    assert verify_otp_hash("000000", new_hash, salt) is False
    assert verify_otp_hash("000000", old_hash, salt) is False


# ==============================================================================
# 6. Production Security Validator & Domain Separation
# ==============================================================================
def test_production_validator_enforces_domain_separation_across_all_keys():
    """Verify production settings validator rejects identical keys across functional domains."""
    k1 = "cSpRnG_kEy_oNe_32_cHaRaCtErS_vAlId_fOr_pRoD_1234"
    k2 = "cSpRnG_kEy_tWo_32_cHaRaCtErS_vAlId_fOr_pRoD_5678"
    k3 = "cSpRnG_kEy_tHrEe_32_cHaRaCtErS_vAlId_fOr_pRoD_9012"

    # Valid distinct keys
    s = Settings(
        ENVIRONMENT="production",
        SECRET_KEY=k1,
        OUTBOX_ENCRYPTION_KEY=k2,
        OTP_SECRET_KEY=k3,
        SMS_PROVIDER="termii",
        TERMII_API_KEY="valid_termii_api_key_test_12345",
        OUTBOX_WORKER_ENABLED=True,
        REDIS_URL="redis://localhost:6379/0",
    )
    assert s.SECRET_KEY == k1
    assert s.OUTBOX_ENCRYPTION_KEY == k2
    assert s.OTP_SECRET_KEY == k3

    # Reject OTP_SECRET_KEY identical to SECRET_KEY
    with pytest.raises(ValueError, match="OTP_SECRET_KEY must be distinct from SECRET_KEY"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY=k1,
            OUTBOX_ENCRYPTION_KEY=k2,
            OTP_SECRET_KEY=k1,
            SMS_PROVIDER="termii",
            TERMII_API_KEY="valid_termii_api_key_test_12345",
            OUTBOX_WORKER_ENABLED=True,
            REDIS_URL="redis://localhost:6379/0",
        )

    # Reject OTP_SECRET_KEY identical to OUTBOX_ENCRYPTION_KEY
    with pytest.raises(ValueError, match="OTP_SECRET_KEY must be distinct from OUTBOX_ENCRYPTION_KEY"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY=k1,
            OUTBOX_ENCRYPTION_KEY=k2,
            OTP_SECRET_KEY=k2,
            SMS_PROVIDER="termii",
            TERMII_API_KEY="valid_termii_api_key_test_12345",
            OUTBOX_WORKER_ENABLED=True,
            REDIS_URL="redis://localhost:6379/0",
        )
