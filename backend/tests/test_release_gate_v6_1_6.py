"""Acceptance and regression tests for Release Gate v6.1.6:
End-to-End Verification Integrity, Scheme-Aware Configuration, Fail-Closed Audit Evidence,
and Accurate Geographic Coverage.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import httpx
import pytest
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.services.nipost_client import NIPOSTClient, NIPOSTLookupStatus, NIPOSTLookupResult
from backend.app.models.verification_evidence import VerificationEvidence
from backend.app.models.postcode import PostcodeDirectory
from backend.app.services.postcode_service import (
    classify_verification_evidence,
    validate_verification_evidence,
    get_postcode_coverage_report,
    cleanse_address,
)

client = TestClient(app)


# ==============================================================================
# 1. P1: Postcode Lookup Two-Stage Verification Inviolability
# ==============================================================================

def test_lookup_endpoint_fails_closed_when_validator_fails_despite_autofill_200():
    """CRITICAL REGRESSION TEST:
    Simulates Validator returning HTTP 503 (UNAVAILABLE) while Autofill returns HTTP 200 (FOUND).
    The /api/v1/postcodes/lookup API with strict=True MUST fail closed with HTTP 503
    and MUST NOT call Autofill or return an official verification result.
    """
    autofill_called = False

    def mock_validator(code):
        return NIPOSTLookupResult(
            status=NIPOSTLookupStatus.UNAVAILABLE,
            http_status=503,
            error_message="Upstream NIPOST validator gateway timeout",
        )

    def mock_autofill(code):
        nonlocal autofill_called
        autofill_called = True
        return NIPOSTLookupResult(
            status=NIPOSTLookupStatus.FOUND,
            http_status=200,
            data={"code": code, "area": "Ikeja", "state": "Lagos", "dataset_version": "2026.1"},
        )

    with patch.object(NIPOSTClient, "is_configured", True), \
         patch.object(NIPOSTClient, "validate_postcode", side_effect=mock_validator), \
         patch.object(NIPOSTClient, "lookup_postcode", side_effect=mock_autofill):

        # A. Strict mode must return HTTP 503
        resp = client.get("/api/v1/postcodes/lookup?code=100001&strict=true")
        assert resp.status_code == 503
        assert "Official NIPOST API unavailable" in resp.json()["detail"]
        assert autofill_called is False, "Autofill MUST NOT be called when Validator stage fails"


def test_lookup_endpoint_fallback_discloses_validator_failure_without_official_evidence():
    """In non-strict mode, when Validator returns 503 and Autofill returns 200:
    The endpoint must fall back to local reference, report upstream UNAVAILABLE,
    and NOT return or persist official verification.
    """
    autofill_called = False

    def mock_validator(code):
        return NIPOSTLookupResult(
            status=NIPOSTLookupStatus.UNAVAILABLE,
            http_status=503,
            error_message="Upstream gateway unreachable",
        )

    def mock_autofill(code):
        nonlocal autofill_called
        autofill_called = True
        return NIPOSTLookupResult(
            status=NIPOSTLookupStatus.FOUND,
            http_status=200,
            data={"code": code, "area": "Ikeja", "state": "Lagos"},
        )

    with patch.object(NIPOSTClient, "is_configured", True), \
         patch.object(NIPOSTClient, "validate_postcode", side_effect=mock_validator), \
         patch.object(NIPOSTClient, "lookup_postcode", side_effect=mock_autofill):

        resp = client.get("/api/v1/postcodes/lookup?code=100001&strict=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["verification_status"] == "local_reference"
        assert data["is_live_nipost"] is False
        assert data["fallback_used"] is True
        assert data["upstream_status"] == "UNAVAILABLE"
        assert autofill_called is False


def test_lookup_endpoint_two_stage_success_returns_official_verified():
    """When both Validator and Autofill succeed, /lookup returns official_verified."""
    def mock_validator(code):
        return NIPOSTLookupResult(
            status=NIPOSTLookupStatus.FOUND,
            http_status=200,
            data={"code": code, "valid": True, "service": "validator"},
        )

    def mock_autofill(code):
        return NIPOSTLookupResult(
            status=NIPOSTLookupStatus.FOUND,
            http_status=200,
            data={"code": code, "area": "Ikeja Central / Alausa", "state": "Lagos", "lga": "Ikeja", "dataset_version": "2026.1"},
        )

    with patch.object(NIPOSTClient, "is_configured", True), \
         patch.object(NIPOSTClient, "validate_postcode", side_effect=mock_validator), \
         patch.object(NIPOSTClient, "lookup_postcode", side_effect=mock_autofill):

        resp = client.get("/api/v1/postcodes/lookup?code=100001&strict=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["lookup_status"] == "official_verified"
        assert data["verification_status"] == "official_verified"
        assert data["is_live_nipost"] is True
        assert data["verification_method"] == "validator_autofill_pipeline"
        assert data["matches"][0]["verification_status"] == "official_verified"


def test_lookup_endpoint_validator_success_autofill_missing_returns_partial():
    """When Validator succeeds but Autofill returns missing metadata, /lookup returns partially_verified."""
    def mock_validator(code):
        return NIPOSTLookupResult(
            status=NIPOSTLookupStatus.FOUND,
            http_status=200,
            data={"code": code, "valid": True, "service": "validator"},
        )

    def mock_autofill(code):
        return NIPOSTLookupResult(
            status=NIPOSTLookupStatus.NOT_FOUND,
            http_status=404,
            error_message="Metadata record not found",
        )

    with patch.object(NIPOSTClient, "is_configured", True), \
         patch.object(NIPOSTClient, "validate_postcode", side_effect=mock_validator), \
         patch.object(NIPOSTClient, "lookup_postcode", side_effect=mock_autofill):

        resp = client.get("/api/v1/postcodes/lookup?code=100001&strict=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_partial_verification"] is True
        assert data["lookup_status"] == "partially_verified"
        assert data["verification_method"] == "validator"


# ==============================================================================
# 2. P1: Scheme-Aware Configuration Completeness
# ==============================================================================

def test_scheme_aware_configuration_none_requires_only_base_url():
    """For auth_scheme='none', configuration_complete is True with only base_url (no API key)."""
    c_none = NIPOSTClient(base_url="https://api.postcode.gov.ng", api_key="", auth_scheme="none")
    assert c_none.configuration_complete is True
    status = c_none.get_integration_status()
    assert status["configuration_complete"] is True
    assert status["status"] == "configured"
    assert status["auth_scheme"] == "none"

    health = c_none.check_health()
    # It attempts the health probe and does not fail early due to missing API key
    assert "API key missing" not in (health.get("reason") or "")


def test_scheme_aware_configuration_bearer_requires_both_url_and_key():
    """For auth_scheme='bearer', configuration_complete requires both base_url and api_key."""
    c_no_key = NIPOSTClient(base_url="https://api.postcode.gov.ng", api_key="", auth_scheme="bearer")
    assert c_no_key.configuration_complete is False
    status = c_no_key.get_integration_status()
    assert status["configuration_complete"] is False
    assert status["status"] == "awaiting_credentials"

    c_with_key = NIPOSTClient(base_url="https://api.postcode.gov.ng", api_key="secret-key", auth_scheme="bearer")
    assert c_with_key.configuration_complete is True
    assert c_with_key.get_integration_status()["status"] == "configured"


def test_scheme_aware_configuration_api_key_requires_both_url_and_key():
    """For auth_scheme='api_key', configuration_complete requires both base_url and api_key."""
    c_no_key = NIPOSTClient(base_url="https://api.postcode.gov.ng", api_key="", auth_scheme="api_key")
    assert c_no_key.configuration_complete is False

    c_with_key = NIPOSTClient(base_url="https://api.postcode.gov.ng", api_key="secret-key", auth_scheme="api_key")
    assert c_with_key.configuration_complete is True


# ==============================================================================
# 3. P1: Fail-Closed Evidence Validation & Segregation
# ==============================================================================

def test_classify_verification_evidence_segregates_failure_modes():
    """classify_verification_evidence returns exact state without permissive defaults."""
    now_utc = datetime.now(timezone.utc)

    # 1. Valid
    ev_valid = VerificationEvidence(
        postcode="100001",
        provider="NIPOST",
        status="verified",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        valid_until=now_utc + timedelta(days=10),
        is_active=True,
    )
    assert classify_verification_evidence(ev_valid) == "valid"
    assert validate_verification_evidence(ev_valid) is True

    # 2. Incomplete: missing provider
    ev_no_prov = VerificationEvidence(
        postcode="100001",
        provider="",
        status="verified",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        valid_until=now_utc + timedelta(days=10),
        is_active=True,
    )
    assert classify_verification_evidence(ev_no_prov) == "incomplete"
    assert validate_verification_evidence(ev_no_prov) is False

    # 3. Incomplete: missing response_hash
    ev_no_hash = VerificationEvidence(
        postcode="100001",
        provider="NIPOST",
        status="verified",
        verification_method="validator_autofill_pipeline",
        response_hash="",
        valid_until=now_utc + timedelta(days=10),
        is_active=True,
    )
    assert classify_verification_evidence(ev_no_hash) == "incomplete"
    assert validate_verification_evidence(ev_no_hash) is False

    # 4. Incomplete: missing method
    ev_no_method = VerificationEvidence(
        postcode="100001",
        provider="NIPOST",
        status="verified",
        verification_method="",
        response_hash="a" * 64,
        valid_until=now_utc + timedelta(days=10),
        is_active=True,
    )
    assert classify_verification_evidence(ev_no_method) == "incomplete"
    assert validate_verification_evidence(ev_no_method) is False

    # 5. Expired
    ev_exp = VerificationEvidence(
        postcode="100001",
        provider="NIPOST",
        status="verified",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        valid_until=now_utc - timedelta(days=1),
        is_active=True,
    )
    assert classify_verification_evidence(ev_exp) == "expired"
    assert validate_verification_evidence(ev_exp) is False

    # 6. Rejected
    ev_rej = VerificationEvidence(
        postcode="100001",
        provider="NIPOST",
        status="rejected",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        valid_until=now_utc + timedelta(days=10),
        is_active=True,
    )
    assert classify_verification_evidence(ev_rej) == "rejected"

    # 7. Inactive
    ev_inact = VerificationEvidence(
        postcode="100001",
        provider="NIPOST",
        status="verified",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        valid_until=now_utc + timedelta(days=10),
        is_active=False,
    )
    assert classify_verification_evidence(ev_inact) == "rejected"

    # 8. Invalid provider
    ev_wrong_prov = VerificationEvidence(
        postcode="100001",
        provider="UNOFFICIAL_API",
        status="verified",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        valid_until=now_utc + timedelta(days=10),
        is_active=True,
    )
    assert classify_verification_evidence(ev_wrong_prov) == "invalid"


# ==============================================================================
# 4. P2: Accurate Geographic Coverage & Metrics Segregation
# ==============================================================================

def test_coverage_report_calculates_actual_active_state_records():
    """get_postcode_coverage_report derives states_covered from actual active records,
    not static 37-state metadata.
    """
    now_utc = datetime.now(timezone.utc)
    mock_db = MagicMock()

    # Create 3 directory records spanning only 2 states (Lagos, Kano)
    r1 = PostcodeDirectory(code="100001", area="Ikeja", state="Lagos", lga="Ikeja", lat=6.61, lng=3.35, is_active=True)
    r2 = PostcodeDirectory(code="100002", area="VI", state="Lagos", lga="Eti-Osa", lat=6.42, lng=3.42, is_active=True)
    r3 = PostcodeDirectory(code="700001", area="Kano Central", state="Kano", lga="Kano Municipal", lat=12.0, lng=8.5, is_active=True)

    ev_valid = VerificationEvidence(
        postcode="100001",
        provider="NIPOST",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        status="verified",
        valid_until=now_utc + timedelta(days=15),
        is_active=True,
    )
    ev_expired = VerificationEvidence(
        postcode="100002",
        provider="NIPOST",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        status="verified",
        valid_until=now_utc - timedelta(days=2),
        is_active=True,
    )
    ev_rejected = VerificationEvidence(
        postcode="999999",
        provider="NIPOST",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        status="rejected",
        valid_until=now_utc + timedelta(days=10),
        is_active=True,
    )
    ev_incomplete = VerificationEvidence(
        postcode="888888",
        provider="NIPOST",
        verification_method="validator_autofill_pipeline",
        response_hash="",
        status="verified",
        valid_until=now_utc + timedelta(days=10),
        is_active=True,
    )

    def mock_query(model):
        q = MagicMock()
        if model == VerificationEvidence:
            q.all.return_value = [ev_valid, ev_expired, ev_rejected, ev_incomplete]
        elif model == PostcodeDirectory:
            q.all.return_value = [r1, r2, r3]
            q.filter.return_value.all.return_value = [r1, r2, r3]
        return q

    mock_db.query.side_effect = mock_query

    rep = get_postcode_coverage_report(db=mock_db)

    # Actual states covered must be exactly 2 (Lagos, Kano), NOT 37
    assert rep.scope_states_count == 2
    assert sorted(rep.states_covered) == ["Kano", "Lagos"]
    assert "Kano" in rep.states_with_active_records
    assert "Lagos" in rep.states_with_active_records

    # Static metadata states still exposed separately
    assert len(rep.states_in_dataset_metadata) >= 11

    # Evidence metrics strictly segregated
    assert rep.records_with_valid_evidence == 1
    assert rep.records_with_expired_evidence == 1
    assert rep.records_with_rejected_evidence == 1
    assert rep.records_with_incomplete_evidence == 1


# ==============================================================================
# 5. P2: Complete Address Metadata Null Preservation
# ==============================================================================

def test_cleanse_address_null_preservation_across_all_failure_branches():
    """cleanse_address preserves None for missing area and state on invalid,
    not found, and unrecognized addresses without synthetic defaults.
    """
    # 1. Invalid input
    res_inv = cleanse_address(address="Invalid addr", postcode_hint="ABC!@#", live_verify=False)
    assert res_inv.area is None or res_inv.area != "Invalid Location"
    assert res_inv.state is None or res_inv.state != "Nigeria"

    # 2. Unrecognized address
    res_unrec = cleanse_address(address="Unknown Farm Settlement Outside All Grids", live_verify=False)
    assert res_unrec.area is None
    assert res_unrec.state is None
    assert res_unrec.postcode == ""
    assert res_unrec.postcode_status == "unverified"
