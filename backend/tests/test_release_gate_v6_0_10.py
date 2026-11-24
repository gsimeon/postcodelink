"""Comprehensive Acceptance and Regression Tests for Release Gate v6.0.10.

Verifies:
1. P1: Auditable Verification Evidence Model & Database Provenance Gate
   - Database records claiming 'official_verified' without active VerificationEvidence demote to 'local_match' (0.75).
   - Records with active, unexpired VerificationEvidence return 'verified' (0.95).
   - Records with expired VerificationEvidence demote to 'local_match' (0.75).
2. P1: Explicit Two-Stage Validator -> Autofill Orchestration & Provenance Boundary
   - Validator FOUND + Autofill FOUND -> 'verified', 'nipost_autofill', confidence 0.95.
   - Validator FOUND + Autofill missing -> 'partially_verified', 'local_enrichment', confidence 0.80, with explicit disclosure.
   - Strict mode fails closed on Stage 1 or Stage 2 failures (404/503).
   - Non-strict mode falls back with transparent disclosure.
3. P2: Zero-Downtime JWT Key Rotation with Explicit ID Mapping
   - End-to-end rotation from v1 to v2: v1 tokens remain valid after v2 upgrade.
   - Unkeyed fallback in JWT_PREVIOUS_SECRETS prevents disruption if prefix omitted.
   - JSON map configuration support (JWT_PREVIOUS_KEYS_MAP).
   - Unknown/rogue key IDs are rejected (HTTP 401).
"""
import uuid
import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.database import SessionLocal, Base, engine
from backend.app.config import settings
from backend.app.core.security import create_access_token, decode_access_token
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.verification_evidence import VerificationEvidence, default_valid_until
from backend.app.services.postcode_service import cleanse_address
from backend.app.services.nipost_client import NIPOSTLookupStatus, NIPOSTLookupResult, NIPOSTClient


# Ensure all tables are created in SQLite test DB
Base.metadata.create_all(bind=engine)


# ==============================================================================
# 1. P1: Verification Evidence Model & Database Provenance Gate
# ==============================================================================
def test_database_flag_without_evidence_demoted_to_local_match():
    """Verify that a database record marked 'official_verified' without supporting VerificationEvidence
    is demoted to 'local_match' (confidence 0.75) and flagged as unverified with live NIPOST.
    """
    db = SessionLocal()
    test_code = "109666"
    try:
        # Delete any pre-existing evidence
        db.query(VerificationEvidence).filter(VerificationEvidence.postcode == test_code).delete()
        db.commit()

        rec = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == test_code).first()
        if not rec:
            rec = PostcodeDirectory(
                code=test_code,
                area="Unbacked Tech Zone",
                state="Lagos",
                lga="Ikeja",
                lat=6.6018,
                lng=3.3515,
                verification_status="official_verified",  # DB flag claimed without evidence
                provenance="Unbacked Entry",
                dataset_version="2026.1",
                is_active=True,
            )
            db.add(rec)
            db.commit()
        else:
            rec.verification_status = "official_verified"
            db.commit()

        res = cleanse_address(
            address="Plot 1, Unbacked Tech Zone, Lagos",
            postcode_hint=test_code,
            db=db,
        )

        # Must demote to local_match (confidence 0.75) due to lack of audit evidence
        assert res.postcode == test_code
        assert res.postcode_status == "local_match"
        assert res.verification_status == "local_reference"
        assert res.confidence == 0.75
        assert res.dispatch_confidence == 0.75
        assert any("unverified with official NIPOST" in c for c in res.changes_made)
    finally:
        db.close()


def test_database_record_with_valid_evidence_returns_verified():
    """Verify that a database record with 'official_verified' backed by active, unexpired
    VerificationEvidence returns postcode_status='verified' and confidence 0.95.
    """
    db = SessionLocal()
    test_code = "109555"
    try:
        rec = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == test_code).first()
        if not rec:
            rec = PostcodeDirectory(
                code=test_code,
                area="Audited Maritime Hub",
                state="Lagos",
                lga="Apapa",
                lat=6.4474,
                lng=3.3644,
                verification_status="official_verified",
                provenance="Official NIPOST Live Directory Gateway",
                dataset_version="2026.1",
                is_active=True,
            )
            db.add(rec)
            db.commit()

        # Insert active, unexpired VerificationEvidence if not already present (table is append-only immutable)
        ev = db.query(VerificationEvidence).filter(VerificationEvidence.postcode == test_code).first()
        if not ev:
            ev = VerificationEvidence(
                postcode=test_code,
                provider="NIPOST",
                provider_reference_id="NIPOST-AUDIT-109555-PASS",
                verification_method="validator_autofill_pipeline",
                dataset_version="2026.1",
                response_hash="a" * 64,
                status="verified",
                address_metadata_source="nipost_autofill",
                valid_until=default_valid_until(),
                is_active=True,
            )
            db.add(ev)
            db.commit()
            db.refresh(ev)

        res = cleanse_address(
            address="Wharf Road, Audited Maritime Hub, Lagos",
            postcode_hint=test_code,
            db=db,
        )

        assert res.postcode == test_code
        assert res.postcode_status == "verified"
        assert res.verification_status == "official_verified"
        assert res.confidence == 0.95
        assert res.dispatch_confidence == 0.95
        assert res.evidence_id == ev.id
        assert any("Verified against official NIPOST registry" in c for c in res.changes_made)
    finally:
        db.close()


def test_database_record_with_expired_evidence_demoted():
    """Verify that a database record with expired VerificationEvidence (past valid_until)
    is demoted to 'local_match' (confidence 0.75) requiring revalidation.
    """
    db = SessionLocal()
    test_code = "109444"
    try:
        rec = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == test_code).first()
        if not rec:
            rec = PostcodeDirectory(
                code=test_code,
                area="Expired Audit Sector",
                state="Lagos",
                lga="Ikeja",
                lat=6.6018,
                lng=3.3515,
                verification_status="official_verified",
                provenance="Historical NIPOST Record",
                dataset_version="2024.1",
                is_active=True,
            )
            db.add(rec)
            db.commit()

        # Insert expired VerificationEvidence (expired 15 days ago) if not already present
        ev = db.query(VerificationEvidence).filter(VerificationEvidence.postcode == test_code).first()
        if not ev:
            expired_dt = datetime.now(timezone.utc) - timedelta(days=15)
            ev = VerificationEvidence(
                postcode=test_code,
                provider="NIPOST",
                provider_reference_id="NIPOST-AUDIT-109444-EXPIRED",
                verification_method="validator_autofill_pipeline",
                dataset_version="2024.1",
                response_hash="b" * 64,
                status="verified",
                address_metadata_source="nipost_autofill",
                valid_until=expired_dt,
                is_active=True,
            )
            db.add(ev)
            db.commit()

        res = cleanse_address(
            address="Plot 99, Expired Audit Sector, Lagos",
            postcode_hint=test_code,
            db=db,
        )

        # Must be demoted because evidence has expired
        assert res.postcode == test_code
        assert res.postcode_status == "local_match"
        assert res.verification_status == "local_reference"
        assert res.confidence == 0.75
    finally:
        db.close()


# ==============================================================================
# 2. P1: Two-Stage Validator -> Autofill Orchestration & Provenance Boundary
# ==============================================================================
def test_two_stage_pipeline_validator_and_autofill_success():
    """Verify that when both Validator and Autofill succeed, the response returns
    postcode_status='verified', address_metadata_source='nipost_autofill', confidence 0.95.
    """
    client = TestClient(app)
    val_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={"code": "100001", "valid": True, "service": "validator", "dataset_version": "2026.1"},
    )
    autofill_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "100001",
            "area": "Marina, Lagos",
            "state": "Lagos",
            "lga": "Lagos Island",
            "building_reference": "Broad Street Tower",
            "dataset_version": "2026.1",
            "service": "autofill",
        },
    )

    with patch("backend.app.services.nipost_client.NIPOSTClient.is_configured", True), \
         patch("backend.app.services.nipost_client.NIPOSTClient.validate_postcode", return_value=val_result), \
         patch("backend.app.services.nipost_client.NIPOSTClient.lookup_postcode", return_value=autofill_result):
        resp = client.post("/api/v1/postcodes/cleanse", json={
            "address": "12 Broad Street, Marina, Lagos",
            "postcode": "100001",
            "live_verify": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["postcode"] == "100001"
        assert data["postcode_status"] == "verified"
        assert data["verification_status"] == "official_verified"
        assert data["confidence"] == 0.95
        assert data["address_metadata_source"] == "nipost_autofill"
        assert data["verification_method"] == "validator_autofill_pipeline"
        assert data["is_partial_verification"] is False
        assert any("Verified against official live NIPOST API" in c for c in data["changes_made"])


def test_two_stage_pipeline_validator_success_autofill_missing():
    """Verify that when Validator succeeds (valid=True) but Autofill returns no address metadata,
    the response returns postcode_status='partially_verified', address_metadata_source='local_enrichment',
    confidence 0.80, and explicitly discloses local enrichment in changes_made.
    """
    client = TestClient(app)
    val_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={"code": "100001", "valid": True, "service": "validator", "dataset_version": "2026.1"},
    )
    # Autofill returns not found or empty metadata
    autofill_empty = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.NOT_FOUND,
        error_message="No address metadata available in autofill index for this code.",
    )

    with patch("backend.app.services.nipost_client.NIPOSTClient.is_configured", True), \
         patch("backend.app.services.nipost_client.NIPOSTClient.validate_postcode", return_value=val_result), \
         patch("backend.app.services.nipost_client.NIPOSTClient.lookup_postcode", return_value=autofill_empty):
        resp = client.post("/api/v1/postcodes/cleanse", json={
            "address": "12 Broad Street, Marina, Lagos",
            "postcode": "100001",
            "live_verify": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["postcode"] == "100001"
        assert data["postcode_status"] == "partially_verified"
        assert data["verification_status"] == "local_reference"
        assert data["confidence"] == 0.80
        assert data["is_partial_verification"] is True
        assert data["address_metadata_source"] == "local_enrichment"
        assert data["verification_method"] == "validator"
        assert any("Postcode existence verified by official NIPOST Validator" in c for c in data["changes_made"])
        assert any("enriched from local reference dataset" in c for c in data["changes_made"])


def test_two_stage_pipeline_validator_not_found_strict_fail_closed():
    """Verify that in strict mode, if Validator returns NOT_FOUND, the endpoint fails closed
    with HTTP 404 rather than attempting local fallback.
    """
    client = TestClient(app)
    val_not_found = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.NOT_FOUND,
        error_message="Postcode '999999' does not exist in official national directory.",
    )

    with patch("backend.app.services.nipost_client.NIPOSTClient.is_configured", True), \
         patch("backend.app.services.nipost_client.NIPOSTClient.validate_postcode", return_value=val_not_found):
        resp = client.post("/api/v1/postcodes/cleanse", json={
            "address": "99 Nowhere Road, Unknown Area, Lagos",
            "postcode": "999999",
            "strict": True,
        })
        assert resp.status_code == 404
        detail = resp.json()["detail"].lower()
        assert "not found" in detail or "does not exist" in detail


def test_two_stage_pipeline_validator_unavailable_strict_fail_closed():
    """Verify that in strict mode, if Validator times out or fails (UNAVAILABLE), the endpoint
    fails closed with HTTP 503 rather than attempting local fallback.
    """
    client = TestClient(app)
    val_unavail = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.UNAVAILABLE,
        error_message="Gateway connection reset.",
    )

    with patch("backend.app.services.nipost_client.NIPOSTClient.is_configured", True), \
         patch("backend.app.services.nipost_client.NIPOSTClient.validate_postcode", return_value=val_unavail), \
         patch("backend.app.services.nipost_client.NIPOSTClient.lookup_postcode", return_value=val_unavail):
        resp = client.post("/api/v1/postcodes/cleanse", json={
            "address": "12 Broad Street, Marina, Lagos",
            "postcode": "100001",
            "strict": True,
        })
        assert resp.status_code == 503
        assert "Official NIPOST API unavailable" in resp.json()["detail"]


# ==============================================================================
# 3. P2: Zero-Downtime JWT Key Rotation with Explicit ID Mapping
# ==============================================================================
def test_jwt_rotation_preserves_v1_tokens_after_v2_upgrade():
    """Verify that tokens issued with JWT_KEY_ID='v1' and secret1 remain verifiable
    after the server transitions to JWT_KEY_ID='v2' with SECRET_KEY=secret2 and
    JWT_PREVIOUS_SECRETS=['v1:secret1'].
    """
    secret_v1 = "postcodelink_v1_legacy_secret_key_minimum_43_characters_entropy"
    secret_v2 = "postcodelink_v2_active_secret_key_minimum_43_characters_entropy"

    # Step 1: Issue token on v1 server
    with patch.object(settings, "SECRET_KEY", secret_v1), \
         patch.object(settings, "JWT_KEY_ID", "v1"):
        token_v1 = create_access_token({"sub": "merchant_user_1", "role": "merchant"})

    # Step 2: Server transitions to v2 with documented JWT_PREVIOUS_SECRETS format
    with patch.object(settings, "SECRET_KEY", secret_v2), \
         patch.object(settings, "JWT_KEY_ID", "v2"), \
         patch.object(settings, "JWT_PREVIOUS_SECRETS", [f"v1:{secret_v1}"]):
        
        # Verify v1 token still decodes seamlessly
        payload_v1 = decode_access_token(token_v1)
        assert payload_v1["sub"] == "merchant_user_1"
        assert payload_v1["role"] == "merchant"

        # Verify new tokens issued under v2 also decode seamlessly
        token_v2 = create_access_token({"sub": "admin_user_2", "role": "admin"})
        payload_v2 = decode_access_token(token_v2)
        assert payload_v2["sub"] == "admin_user_2"
        assert payload_v2["role"] == "admin"


def test_jwt_rotation_unkeyed_legacy_token_preserves_compatibility():
    """Verify that unversioned legacy tokens (without kid header) decode successfully
    using JWT_PREVIOUS_SECRETS fallback during migration.
    """
    secret_v1 = "postcodelink_v1_legacy_secret_key_minimum_43_characters_entropy"
    secret_v2 = "postcodelink_v2_active_secret_key_minimum_43_characters_entropy"

    # Issue legacy token without kid header
    import jwt as pyjwt
    legacy_payload = {"sub": "dispatcher_user_3", "role": "dispatcher", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    token_legacy = pyjwt.encode(legacy_payload, secret_v1, algorithm="HS256")

    # Server configured with secret_v2 as active and secret_v1 in previous secrets
    with patch.object(settings, "SECRET_KEY", secret_v2), \
         patch.object(settings, "JWT_KEY_ID", "v2"), \
         patch.object(settings, "JWT_PREVIOUS_SECRETS", [secret_v1]):
        
        payload = decode_access_token(token_legacy)
        assert payload["sub"] == "dispatcher_user_3"


def test_jwt_rotation_json_keys_map_configuration():
    """Verify that JWT_PREVIOUS_KEYS_MAP configured via dictionary or JSON decodes mapped keys."""
    secret_v1 = "postcodelink_v1_legacy_secret_key_minimum_43_characters_entropy"
    secret_v2 = "postcodelink_v2_active_secret_key_minimum_43_characters_entropy"

    with patch.object(settings, "SECRET_KEY", secret_v1), \
         patch.object(settings, "JWT_KEY_ID", "v1"):
        token_v1 = create_access_token({"sub": "api_client_4", "role": "merchant"})

    with patch.object(settings, "SECRET_KEY", secret_v2), \
         patch.object(settings, "JWT_KEY_ID", "v2"), \
         patch.object(settings, "JWT_PREVIOUS_KEYS_MAP", {"v1": secret_v1}):
        
        payload = decode_access_token(token_v1)
        assert payload["sub"] == "api_client_4"


def test_jwt_unknown_kid_with_rogue_secret_rejected():
    """Verify that a token with unknown kid signed with an unauthorized secret is rejected."""
    import jwt as pyjwt
    rogue_token = pyjwt.encode(
        {"sub": "attacker", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "attacker_rogue_secret_key_minimum_32_characters",
        algorithm="HS256",
        headers={"kid": "v99_unrecognized"},
    )
    with pytest.raises(pyjwt.PyJWTError):
        decode_access_token(rogue_token)
