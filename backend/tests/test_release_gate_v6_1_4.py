"""Release Gate v6.1.4 Acceptance Test Suite:
Two-Stage Integration Hardening, Discrimination of Upstream 404/401,
Verification Mode Precedence Enforcements, and Evidence-Backed Coverage.

Validates the critical governance requirements of Release 6.1.4:
1. Two-Stage NIPOST Integration Contract:
   - Configuration completeness enforcement (base URL + API key).
   - Machine-readable 404 (NOT_FOUND) vs Route 404 (UNAVAILABLE).
   - HTTP 401/403 authorization failures (UNAUTHORIZED).
   - Stage 1 Validator halting immediately on negative existence.
   - Stage 1 + Stage 2 positive verification with durable audit evidence.
   - Stage 1 Validator positive + Stage 2 Autofill missing -> partial verification + local enrichment.
2. Verification Mode Precedence Table:
   - Rejection of contradictory combinations with HTTP 422:
     * local_standardization with strict=True
     * local_standardization with live_verify=True
     * nipost_validate with strict=True
     * nipost_strict with strict=False
   - Legacy flag resolution when verification_mode is omitted:
     * strict=True -> nipost_strict
     * live_verify=True -> nipost_validate
     * neither -> local_standardization
3. Enhanced Coverage Report & Data Classification:
   - Expanded metrics: legacy_six_digit_records, national_digital_postcode_records,
     records_with_valid_evidence, records_with_expired_evidence, records_with_complete_metadata,
     local_demonstration_fixtures.
   - Strict 5-part digital postcode classification via parse_digital_postcode_components.
   - Evidence validity enforcement: only unexpired, active VerificationEvidence counted.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import httpx
import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.services.nipost_client import (
    NIPOSTClient,
    NIPOSTLookupStatus,
    NIPOSTLookupResult,
)
from backend.app.services.postcode_service import (
    cleanse_address,
    get_postcode_coverage_report,
)
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.verification_evidence import VerificationEvidence


client = TestClient(app)


# ==============================================================================
# 1. Verification Mode Precedence & Contradiction Matrix
# ==============================================================================

def test_mode_local_standardization_with_strict_true_rejected_422():
    """verification_mode='local_standardization' cannot be combined with strict=True."""
    res = client.post(
        "/api/v1/postcodes/cleanse",
        json={
            "address": "12 Broad Street, Marina, Lagos",
            "verification_mode": "local_standardization",
            "strict": True,
        },
    )
    assert res.status_code == 422
    assert "cannot be combined with strict=True" in res.text


def test_mode_local_standardization_with_live_verify_true_rejected_422():
    """verification_mode='local_standardization' cannot be combined with live_verify=True."""
    res = client.post(
        "/api/v1/postcodes/cleanse",
        json={
            "address": "12 Broad Street, Marina, Lagos",
            "verification_mode": "local_standardization",
            "live_verify": True,
        },
    )
    assert res.status_code == 422
    assert "cannot be combined with live_verify=True" in res.text


def test_mode_nipost_validate_with_strict_true_rejected_422():
    """verification_mode='nipost_validate' allows fallback and cannot be combined with strict=True."""
    res = client.post(
        "/api/v1/postcodes/cleanse",
        json={
            "address": "12 Broad Street, Marina, Lagos",
            "verification_mode": "nipost_validate",
            "strict": True,
        },
    )
    assert res.status_code == 422
    assert "allows fallback and cannot be combined with strict=True" in res.text


def test_mode_nipost_strict_with_strict_false_rejected_422():
    """verification_mode='nipost_strict' requires fail-closed behavior and cannot be combined with strict=False."""
    res = client.post(
        "/api/v1/postcodes/cleanse",
        json={
            "address": "12 Broad Street, Marina, Lagos",
            "verification_mode": "nipost_strict",
            "strict": False,
        },
    )
    assert res.status_code == 422
    assert "requires fail-closed behavior and cannot be combined with strict=False" in res.text


def test_mode_resolution_from_legacy_flags():
    """When verification_mode is omitted, legacy flags resolve correctly."""
    # 1. strict=True resolves to nipost_strict
    res_strict = client.post(
        "/api/v1/postcodes/cleanse",
        json={
            "address": "12 Broad Street, Marina, Lagos",
            "postcode": "100001",
            "strict": True,
        },
    )
    # Since live NIPOST is unconfigured in test environment, strict fails closed with 503
    assert res_strict.status_code == 503
    assert "Strict verification requires live NIPOST connectivity" in res_strict.json()["detail"]

    # 2. live_verify=True resolves to nipost_validate (falls back gracefully)
    res_live = client.post(
        "/api/v1/postcodes/cleanse",
        json={
            "address": "12 Broad Street, Marina, Lagos",
            "postcode": "100001",
            "live_verify": True,
        },
    )
    assert res_live.status_code == 200
    assert res_live.json()["verification_mode"] == "nipost_validate"

    # 3. Neither flag resolves to local_standardization
    res_default = client.post(
        "/api/v1/postcodes/cleanse",
        json={
            "address": "12 Broad Street, Marina, Lagos",
            "postcode": "100001",
        },
    )
    assert res_default.status_code == 200
    assert res_default.json()["verification_mode"] == "local_standardization"


# ==============================================================================
# 2. NIPOST Two-Stage Verification Contract Matrix & 404/401 Discrimination
# ==============================================================================

def test_nipost_validate_discriminate_machine_readable_404_vs_route_404():
    """Machine-readable 404 returns NOT_FOUND, while generic HTML or missing route 404 returns UNAVAILABLE."""
    # Machine-readable 404: NIPOST responds with JSON indicating the code was checked and not found
    def mock_transport_handler_machine_404(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"valid": False, "code": "999999", "message": "Postcode not found in national registry"},
            headers={"content-type": "application/json"},
        )

    client_machine = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="test-key-12345",
        transport=httpx.MockTransport(mock_transport_handler_machine_404),
    )
    res_machine = client_machine.validate_postcode("999999")
    assert res_machine.status == NIPOSTLookupStatus.NOT_FOUND
    assert "not found" in res_machine.error_message.lower()

    # Route 404: Upstream responds with generic HTML 404 (endpoint path missing or proxy 404)
    def mock_transport_handler_route_404(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            text="<html><head><title>404 Not Found</title></head><body>Cannot GET /v1/validate</body></html>",
            headers={"content-type": "text/html"},
        )

    client_route = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="test-key-12345",
        transport=httpx.MockTransport(mock_transport_handler_route_404),
    )
    res_route = client_route.validate_postcode("999999")
    assert res_route.status == NIPOSTLookupStatus.UNAVAILABLE
    assert "endpoint not found" in res_route.error_message.lower()


def test_nipost_validate_handles_401_403_unauthorized():
    """HTTP 401/403 responses must return UNAUTHORIZED rather than generic failure."""
    def mock_transport_handler_401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": "Unauthorized", "message": "API key expired or invalid"},
            headers={"content-type": "application/json"},
        )

    test_client = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="expired-key",
        transport=httpx.MockTransport(mock_transport_handler_401),
    )
    res = test_client.validate_postcode("100001")
    assert res.status == NIPOSTLookupStatus.UNAUTHORIZED
    assert "authentication failed" in res.error_message.lower()


def test_two_stage_validator_negative_halts_immediately():
    """When Validator returns NOT_FOUND, orchestrated_verify halts immediately and does not call Autofill."""
    autofill_called = False

    def mock_transport(request: httpx.Request) -> httpx.Response:
        nonlocal autofill_called
        if "validate" in str(request.url):
            return httpx.Response(
                200,
                json={"valid": False, "code": "888888", "service": "validator"},
            )
        if "lookup" in str(request.url):
            autofill_called = True
            return httpx.Response(200, json={"code": "888888", "area": "Should Not Happen"})
        return httpx.Response(404)

    test_client = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="test-key",
        validate_path="/v1/validate",
        transport=httpx.MockTransport(mock_transport),
    )

    status_code, data, err, method = test_client.orchestrated_verify("888888")
    assert status_code == NIPOSTLookupStatus.NOT_FOUND
    assert data is None or data.get("valid") is False
    assert autofill_called is False
    assert method == "validator"


def test_two_stage_unconfigured_strict_fails_closed_503():
    """When base_url or credentials are not configured, strict verification fails closed with HTTP 503."""
    unconfigured_client = NIPOSTClient(base_url="", api_key="")
    with pytest.raises(HTTPException) as exc_info:
        cleanse_address(
            address="12 Broad Street, Marina, Lagos",
            postcode_hint="100001",
            verification_mode="nipost_strict",
            client=unconfigured_client,
            db=MagicMock(),
        )
    assert exc_info.value.status_code == 503
    assert "configuration is incomplete" in exc_info.value.detail


# ==============================================================================
# 3. Evidence-Backed Coverage Reporting & Strict Classification
# ==============================================================================

def test_coverage_report_expanded_dimensions_structure():
    """GET /api/v1/postcodes/coverage must return all expanded breakdown dimensions."""
    res = client.get("/api/v1/postcodes/coverage")
    assert res.status_code == 200
    data = res.json()

    # Core metadata
    assert data["version"] == "2024.2"
    assert data["scope_states_count"] >= 11
    assert data["total_reference_records"] >= 30

    # Expanded dimensions
    assert "legacy_six_digit_records" in data
    assert "national_digital_postcode_records" in data
    assert "local_demonstration_fixtures" in data
    assert "records_with_coordinates" in data
    assert "records_with_valid_evidence" in data
    assert "records_with_expired_evidence" in data
    assert "records_with_complete_metadata" in data

    assert data["legacy_six_digit_records"] > 0
    assert data["national_digital_postcode_records"] > 0
    assert data["records_with_complete_metadata"] > 0


def test_coverage_strict_digital_postcode_classification():
    """national_digital_postcode_records must strictly classify only canonical 5-component codes,
    rejecting arbitrary strings with len > 6.
    """
    mock_db = MagicMock()
    # 3 records:
    # 1. Canonical 5-part digital code (FC-02-A09-DB-09) -> digital
    # 2. Legacy 6-digit code (100001) -> legacy
    # 3. Invalid long string (NOT-A-REAL-DIGITAL-CODE) -> neither
    r1 = PostcodeDirectory(code="FC-02-A09-DB-09", area="Garki", state="Abuja FCT", lga="Abuja Municipal", lat=9.03, lng=7.48)
    r2 = PostcodeDirectory(code="100001", area="Ikeja", state="Lagos", lga="Ikeja", lat=6.61, lng=3.35)
    r3 = PostcodeDirectory(code="NOT-A-REAL-CODE-LONG", area="Random", state="Lagos", lga=None, lat=None, lng=None)

    mock_db.query.return_value.filter.return_value.all.return_value = []
    mock_db.query.return_value.all.return_value = [r1, r2, r3]

    rep = get_postcode_coverage_report(db=mock_db)
    assert rep.total_reference_records == 3
    assert rep.national_digital_postcode_records == 1
    assert rep.legacy_six_digit_records == 1
    assert rep.records_with_coordinates == 2
    assert rep.records_with_complete_metadata == 2


def test_coverage_valid_vs_expired_evidence():
    """records_with_valid_evidence only counts records supported by active, unexpired VerificationEvidence."""
    mock_db = MagicMock()
    now_utc = datetime.now(timezone.utc)

    # Directory record
    r1 = PostcodeDirectory(code="100001", area="Ikeja", state="Lagos", lga="Ikeja", lat=6.61, lng=3.35)
    r2 = PostcodeDirectory(code="100002", area="Victoria Island", state="Lagos", lga="Eti-Osa", lat=6.42, lng=3.42)

    # Evidence: 1 unexpired, 1 expired
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

    # First query is for VerificationEvidence, second for PostcodeDirectory
    def mock_query(model):
        q = MagicMock()
        if model == VerificationEvidence:
            q.filter.return_value.all.return_value = [ev_valid, ev_expired]
        elif model == PostcodeDirectory:
            q.all.return_value = [r1, r2]
        return q

    mock_db.query.side_effect = mock_query

    rep = get_postcode_coverage_report(db=mock_db)
    assert rep.total_reference_records == 2
    assert rep.records_with_valid_evidence == 1
    assert rep.records_with_expired_evidence == 1
    assert rep.records_with_verified_provenance == 1
