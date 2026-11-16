r"""Release Gate v6.0.9 Regression Test Suite.

Covers:
1. P1 Blocker: Database-Backed Local Records vs Official Verification
   - Records with verification_status='local_reference' return postcode_status='local_match' (conf 0.75).
   - Records with verification_status='official_verified' return postcode_status='verified' (conf 0.95).
2. P1 Blocker: Mandatory OTP Key Separation in Production
   - Production settings validator strictly rejects empty or missing OTP_SECRET_KEY.
   - get_otp_secret_key() in production raises RuntimeError rather than falling back to SECRET_KEY.
3. P2: JWT Key Identifier (kid) Header Selection & Verification
   - Active kid selection, previous kid lookup, unknown/retired kid rejection, signature mismatch rejection.
   - Unversioned legacy token fallback compatibility.
4. P2: Hardened 6-Digit Postcode Extraction
   - Explicit label prioritization, Nigerian postal zone filtering ([1-9]\d{5}), and multiple-candidate ambiguity guards.
5. NIPOST Validator vs Autofill Contract Decoupling
   - Validator existence check separated from Autofill metadata retrieval.
"""
import pytest
import secrets
from datetime import datetime, timezone, timedelta
import jwt

from backend.app.database import SessionLocal
from backend.app.models.postcode import PostcodeDirectory
from backend.app.config import Settings, settings
from backend.app.core.postcode_utils import extract_postcode_from_text
from backend.app.services.postcode_service import cleanse_address
from backend.app.core.security import (
    create_access_token,
    decode_access_token,
    get_otp_secret_key,
    hash_otp,
    verify_otp_hash,
)
from backend.app.services.nipost_client import NIPOSTClient


# ==============================================================================
# 1. P1: Database-Backed Local Records vs Official Verification
# ==============================================================================
def test_database_backed_local_reference_record_returns_local_match():
    """Verify that records stored in SQLite/PostgreSQL with verification_status='local_reference'
    are returned with postcode_status='local_match' (conf 0.75), never 'verified' (0.95).
    """
    db = SessionLocal()
    test_code = "109888"
    try:
        # 1. Ensure test record exists with verification_status='local_reference'
        rec = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == test_code).first()
        if not rec:
            rec = PostcodeDirectory(
                code=test_code,
                area="Epe Local Demonstration District",
                state="Lagos",
                lga="Epe",
                lat=6.5841,
                lng=3.9834,
                verification_status="local_reference",
                provenance="PostcodeLink Local Reference Dataset",
                dataset_version="2024.2",
                is_active=True,
            )
            db.add(rec)
            db.commit()

        # 2. Cleanse address using database session
        res = cleanse_address(
            address="Plot 5 Marina Road, Epe Local Demonstration District, Lagos",
            postcode_hint=test_code,
            db=db,
        )

        assert res.postcode == test_code
        assert res.postcode_status == "local_match"
        assert res.verification_status == "local_reference"
        assert res.confidence == 0.75
        assert res.dispatch_confidence == 0.75
        assert res.source == "postgresql_postcode_directory"
        assert res.matched_record is not None
        assert res.matched_record.verification_status == "local_reference"
        assert any("unverified with official NIPOST" in c for c in res.changes_made)
    finally:
        db.close()


def test_database_backed_official_verified_record_returns_verified():
    """Verify that records in the database with verification_status='official_verified'
    are returned with postcode_status='verified' and confidence 0.95.
    """
    db = SessionLocal()
    official_code = "109777"
    try:
        rec = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == official_code).first()
        if not rec:
            rec = PostcodeDirectory(
                code=official_code,
                area="Official FMCIDE Pilot Tech Zone",
                state="Lagos",
                lga="Eti-Osa",
                lat=6.4421,
                lng=3.4751,
                verification_status="official_verified",
                provenance="Official NIPOST Live Directory Gateway",
                dataset_version="2026.1",
                is_active=True,
            )
            db.add(rec)
            db.commit()

        res = cleanse_address(
            address="Plot 10, Official FMCIDE Pilot Tech Zone, Lagos",
            postcode_hint=official_code,
            db=db,
        )

        assert res.postcode == official_code
        assert res.postcode_status == "verified"
        assert res.verification_status == "official_verified"
        assert res.confidence == 0.95
        assert res.dispatch_confidence == 0.95
        assert res.source == "postgresql_postcode_directory"
        assert any("Verified against official NIPOST registry" in c for c in res.changes_made)
    finally:
        db.close()


# ==============================================================================
# 2. P1: Mandatory OTP Key Separation in Production
# ==============================================================================
def test_production_validator_strictly_rejects_missing_or_empty_otp_secret_key():
    """Verify production Settings initialization fails if OTP_SECRET_KEY is empty or omitted."""
    # A. Empty OTP_SECRET_KEY in production
    with pytest.raises(ValueError, match="OTP_SECRET_KEY must be explicitly configured"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="cSpRnG_kEy_oNe_32_cHaRaCtErS_vAlId_fOr_pRoD_1234",
            OUTBOX_ENCRYPTION_KEY="cSpRnG_kEy_tWo_32_cHaRaCtErS_vAlId_fOr_pRoD_5678",
            OTP_SECRET_KEY="",
            SMS_PROVIDER="termii",
            TERMII_API_KEY="valid_termii_api_key_test_12345",
            OUTBOX_WORKER_ENABLED=True,
            REDIS_URL="redis://localhost:6379/0",
        )

    # B. Missing OTP_SECRET_KEY (default empty) in production
    with pytest.raises(ValueError, match="OTP_SECRET_KEY must be explicitly configured"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="cSpRnG_kEy_oNe_32_cHaRaCtErS_vAlId_fOr_pRoD_1234",
            OUTBOX_ENCRYPTION_KEY="cSpRnG_kEy_tWo_32_cHaRaCtErS_vAlId_fOr_pRoD_5678",
            SMS_PROVIDER="termii",
            TERMII_API_KEY="valid_termii_api_key_test_12345",
            OUTBOX_WORKER_ENABLED=True,
            REDIS_URL="redis://localhost:6379/0",
        )


def test_get_otp_secret_key_refuses_fallback_in_production(monkeypatch):
    """Verify get_otp_secret_key() raises RuntimeError if OTP_SECRET_KEY is absent in production."""
    from backend.app.core import security
    monkeypatch.setattr(security.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(security.settings, "OTP_SECRET_KEY", "")

    with pytest.raises(RuntimeError, match="Fallback to SECRET_KEY is strictly forbidden"):
        get_otp_secret_key()


def test_get_otp_secret_key_allows_development_fallback(monkeypatch):
    """Verify get_otp_secret_key() cleanly falls back to SECRET_KEY in development environment."""
    from backend.app.core import security
    monkeypatch.setattr(security.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(security.settings, "OTP_SECRET_KEY", "")
    monkeypatch.setattr(security.settings, "SECRET_KEY", "dev_secret_key_12345_test_value")

    assert get_otp_secret_key() == "dev_secret_key_12345_test_value"


# ==============================================================================
# 3. P2: JWT Key Identifier (kid) Header Selection & Verification
# ==============================================================================
def test_jwt_kid_selection_and_unknown_key_rejection(monkeypatch):
    """Verify decode_access_token() selects the key matching the token's kid header and rejects unknown kids."""
    from backend.app.core import security
    key_v1 = "legacy_v1_cSpRnG_kEy_32_cHaRaCtErS_vAlId_001"
    key_v2 = "active_v2_cSpRnG_kEy_32_cHaRaCtErS_vAlId_002"

    monkeypatch.setattr(security.settings, "SECRET_KEY", key_v2)
    monkeypatch.setattr(security.settings, "JWT_KEY_ID", "v2")
    monkeypatch.setattr(security.settings, "JWT_PREVIOUS_KEYS_MAP", {"v1": key_v1})

    payload = {"sub": "merchant_999", "role": "merchant"}

    # 1. Active key (kid: v2)
    token_v2 = create_access_token(payload)
    decoded_v2 = decode_access_token(token_v2)
    assert decoded_v2["sub"] == "merchant_999"

    # 2. Previous key (kid: v1)
    token_v1 = jwt.encode(payload, key_v1, algorithm="HS256", headers={"kid": "v1"})
    decoded_v1 = decode_access_token(token_v1)
    assert decoded_v1["sub"] == "merchant_999"

    # 3. Unknown or retired key ID (kid: v999) -> MUST be rejected immediately
    token_unknown_kid = jwt.encode(payload, key_v1, algorithm="HS256", headers={"kid": "v999"})
    with pytest.raises(jwt.PyJWTError, match="Unknown or retired JWT key identifier"):
        decode_access_token(token_unknown_kid)

    # 4. Signature mismatch: claims kid 'v2' but signed with different key
    token_mismatched = jwt.encode(payload, key_v1, algorithm="HS256", headers={"kid": "v2"})
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token_mismatched)

    # 5. Legacy unversioned token without kid header -> verifies via active/fallback
    token_legacy = jwt.encode(payload, key_v2, algorithm="HS256")
    decoded_legacy = decode_access_token(token_legacy)
    assert decoded_legacy["sub"] == "merchant_999"


# ==============================================================================
# 4. P2: Hardened 6-Digit Postcode Extraction
# ==============================================================================
def test_hardened_six_digit_extraction_prefers_labels_and_filters_non_zones():
    """Verify that extract_postcode_from_text() avoids false positives on arbitrary numbers."""
    # A. Explicitly labelled postcode
    text_labelled = "Deliver to Shop 4 Admiralty Mall, Lekki, Postal Code: 101241, Lagos State"
    code, p_type, _ = extract_postcode_from_text(text_labelled)
    assert code == "101241"
    assert p_type == "conventional_area"

    # B. Numbers starting with 0 are NOT valid Nigerian postal zones (1-9)
    text_non_zone = "Order tracking # 012345, Delivery to Victoria Island, Lagos"
    code_nz, _, _ = extract_postcode_from_text(text_non_zone)
    assert code_nz is None

    # C. Ambiguity Guard: Multiple distinct unlabelled 6-digit numbers in same text -> returns None
    text_ambiguous = "Tracking reference 123456, Delivery package 654321, Marina, Lagos"
    code_amb, _, _ = extract_postcode_from_text(text_ambiguous)
    assert code_amb is None

    # D. Labelled number takes priority over unlabelled arbitrary number
    text_mixed = "Waybill 889900 for package, Postcode: 100001, Ikeja Central"
    code_mix, _, _ = extract_postcode_from_text(text_mixed)
    assert code_mix == "100001"

    # E. Single valid unlabelled 6-digit code at the end of address
    text_single = "14 Admiralty Way, Lekki Phase 1, Lagos 101241"
    code_s, _, _ = extract_postcode_from_text(text_single)
    assert code_s == "101241"


# ==============================================================================
# 5. NIPOST Validator vs Autofill Contract Decoupling
# ==============================================================================
def test_nipost_client_decoupled_validator_and_autofill_contracts():
    """Verify that NIPOSTClient cleanly separates existence validation from address metadata retrieval."""
    client = NIPOSTClient(base_url="https://api.postcode.gov.ng", api_key="test_key")

    # 1. Validator payload adapter: returns existence check without fabricating address fields
    validator_payload = {
        "postcode": "100001",
        "valid": True,
        "status": "ACTIVE",
    }
    val_status, adapted_val, val_err = client._adapt_validator_payload(validator_payload, "100001")
    assert adapted_val is not None
    assert adapted_val["valid"] is True
    assert adapted_val["code"] == "100001"
    # Metadata is not present in validator payload
    assert adapted_val.get("state") is None or adapted_val.get("state") == ""

    # 2. Autofill payload adapter: parses full address entity dictionary
    autofill_payload = {
        "code": "100001",
        "area": "Ikeja Central / Alausa",
        "state": "Lagos",
        "lga": "Ikeja",
        "latitude": 6.6186,
        "longitude": 3.3570,
    }
    af_status, adapted_af, af_err = client._adapt_autofill_payload(autofill_payload, "100001")
    assert adapted_af is not None
    assert adapted_af["area"] == "Ikeja Central / Alausa"
    assert adapted_af["state"] == "Lagos"
    assert adapted_af["lga"] == "Ikeja"
    assert adapted_af["lat"] == 6.6186
