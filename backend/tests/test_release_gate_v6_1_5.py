"""Release Gate v6.1.5 Acceptance Test Suite:
Verification Contract Integrity, Upstream Precision & Evidence Governance.

Validates the critical governance requirements of Release 6.1.5:
1. P1: Two-Stage Verification Inviolability:
   - Validator failure (UNAVAILABLE, UNAUTHORIZED, INVALID_RESPONSE, NOT_FOUND)
     can NEVER be overridden by Autofill.
2. P1: Explicit Authentication Scheme Handling:
   - 'none' scheme omits Authorization/api-key headers even when API key is present.
   - 'bearer' and 'api_key' attach appropriate headers.
   - Unsupported schemes strictly raise ValueError during initialization.
3. P1: HTTP 404 Classification Edge Cases:
   - Generic JSON gateway errors (e.g. {"status": "error", "message": "Endpoint route not found"})
     are classified as UNAVAILABLE, not NOT_FOUND.
   - Explicit machine-readable postcode non-existence with matching code is NOT_FOUND.
4. P1: Canonical Evidence Validity & Coverage Deduplication:
   - validate_verification_evidence() verifies provider=NIPOST, approved method,
     response_hash presence, active status, unexpired window, and code agreement.
   - Coverage aggregation deduplicates evidence per distinct directory record.
5. P1: Differentiated Integration Readiness States:
   - get_integration_status() separates adapter code presence, configuration completeness,
     connectivity health, authentication verification, contract verification, and
     commercial production authorization.
6. P2: Missing Address Metadata Null Preservation:
   - PostcodeRecordSchema and CleanseAddressResponse preserve nulls rather than
     fabricating placeholder defaults like 'Unspecified Area' or 'Nigeria'.
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
    validate_verification_evidence,
)
from backend.app.schemas.postcode import (
    PostcodeRecordSchema,
    CleanseAddressResponse,
)
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.verification_evidence import VerificationEvidence


client = TestClient(app)


# ==============================================================================
# 1. Two-Stage Pipeline Inviolability (Validator Failure Cannot Be Overridden)
# ==============================================================================

def test_validator_unavailable_cannot_be_overridden_by_autofill():
    """When Validator returns UNAVAILABLE, Autofill cannot override it, even if Autofill succeeds."""
    autofill_called = False

    def mock_transport(request: httpx.Request) -> httpx.Response:
        nonlocal autofill_called
        if "validate" in str(request.url):
            return httpx.Response(503, text="Service Unavailable")
        if "lookup" in str(request.url):
            autofill_called = True
            return httpx.Response(200, json={"code": "100001", "area": "Marina", "state": "Lagos"})
        return httpx.Response(404)

    test_client = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="test-key",
        transport=httpx.MockTransport(mock_transport),
    )

    status, data, err, method = test_client.orchestrated_verify("100001")
    assert status == NIPOSTLookupStatus.UNAVAILABLE
    assert data is None
    assert autofill_called is False
    assert method == "validator"


def test_validator_unauthorized_cannot_be_overridden_by_autofill():
    """When Validator returns UNAUTHORIZED (401), Autofill cannot override it."""
    autofill_called = False

    def mock_transport(request: httpx.Request) -> httpx.Response:
        nonlocal autofill_called
        if "validate" in str(request.url):
            return httpx.Response(401, json={"error": "Unauthorized"})
        if "lookup" in str(request.url):
            autofill_called = True
            return httpx.Response(200, json={"code": "100001", "area": "Marina", "state": "Lagos"})
        return httpx.Response(404)

    test_client = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="bad-key",
        transport=httpx.MockTransport(mock_transport),
    )

    status, data, err, method = test_client.orchestrated_verify("100001")
    assert status == NIPOSTLookupStatus.UNAUTHORIZED
    assert data is None
    assert autofill_called is False
    assert method == "validator"


def test_validator_not_found_cannot_be_overridden_by_autofill():
    """When Validator returns NOT_FOUND (non-existent code), Autofill cannot override it."""
    autofill_called = False

    def mock_transport(request: httpx.Request) -> httpx.Response:
        nonlocal autofill_called
        if "validate" in str(request.url):
            return httpx.Response(200, json={"valid": False, "code": "999999", "service": "validator"})
        if "lookup" in str(request.url):
            autofill_called = True
            return httpx.Response(200, json={"code": "999999", "area": "Phantom Area", "state": "Lagos"})
        return httpx.Response(404)

    test_client = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="test-key",
        transport=httpx.MockTransport(mock_transport),
    )

    status, data, err, method = test_client.orchestrated_verify("999999")
    assert status == NIPOSTLookupStatus.NOT_FOUND
    assert autofill_called is False
    assert method == "validator"


def test_validator_found_and_autofill_found_returns_pipeline():
    """When both Validator and Autofill succeed, returns validator_autofill_pipeline."""
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if "validate" in str(request.url):
            return httpx.Response(200, json={"valid": True, "code": "100001", "service": "validator"})
        if "lookup" in str(request.url):
            return httpx.Response(200, json={"code": "100001", "area": "Marina", "state": "Lagos", "lga": "Lagos Island"})
        return httpx.Response(404)

    test_client = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="test-key",
        transport=httpx.MockTransport(mock_transport),
    )

    status, data, err, method = test_client.orchestrated_verify("100001")
    assert status == NIPOSTLookupStatus.FOUND
    assert data["area"] == "Marina"
    assert data["state"] == "Lagos"
    assert method == "validator_autofill_pipeline"


def test_validator_found_and_autofill_missing_returns_partial():
    """When Validator confirms existence but Autofill returns missing metadata, returns partial validator."""
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if "validate" in str(request.url):
            return httpx.Response(200, json={"valid": True, "code": "100001", "service": "validator"})
        if "lookup" in str(request.url):
            return httpx.Response(404, text="No metadata in index")
        return httpx.Response(404)

    test_client = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="test-key",
        transport=httpx.MockTransport(mock_transport),
    )

    status, data, err, method = test_client.orchestrated_verify("100001")
    assert status == NIPOSTLookupStatus.FOUND
    assert method == "validator"
    assert data["valid"] is True


# ==============================================================================
# 2. Authentication Scheme 'none' and Header Enforcement
# ==============================================================================

def test_auth_scheme_none_omits_authorization_header():
    """When auth_scheme='none', no Authorization or api-key header is attached, even if api_key is present."""
    client_none = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="secret-key-12345",
        auth_scheme="none",
    )
    headers = client_none._get_headers()
    assert "Authorization" not in headers
    assert "x-api-key" not in headers
    assert headers["Accept"] == "application/json"


def test_auth_scheme_bearer_attaches_bearer_header():
    """When auth_scheme='bearer', Authorization: Bearer <key> is attached."""
    client_bearer = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="secret-key-12345",
        auth_scheme="bearer",
    )
    headers = client_bearer._get_headers()
    assert headers["Authorization"] == "Bearer secret-key-12345"
    assert "x-api-key" not in headers


def test_auth_scheme_api_key_attaches_custom_header():
    """When auth_scheme='api_key', x-api-key is attached and Authorization is omitted."""
    client_key = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="secret-key-12345",
        auth_scheme="api_key",
    )
    headers = client_key._get_headers()
    assert headers["x-api-key"] == "secret-key-12345"
    assert "Authorization" not in headers


def test_auth_scheme_unsupported_raises_value_error():
    """Unsupported auth schemes must raise ValueError during initialization."""
    with pytest.raises(ValueError) as exc:
        NIPOSTClient(
            base_url="https://api.postcode.gov.ng",
            api_key="key",
            auth_scheme="unsupported_auth_scheme",
        )
    assert "Unsupported NIPOST authentication scheme" in str(exc.value)


# ==============================================================================
# 3. HTTP 404 Classification Edge Case
# ==============================================================================

def test_validate_postcode_generic_gateway_404_classified_as_unavailable():
    """Generic JSON routing errors like {"status": "error", "message": "Endpoint route not found"}
    must be classified as UNAVAILABLE, not NOT_FOUND.
    """
    def mock_transport_gateway_404(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"status": "error", "message": "Endpoint route not found"},
            headers={"content-type": "application/json"},
        )

    test_client = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="test-key",
        transport=httpx.MockTransport(mock_transport_gateway_404),
    )

    res = test_client.validate_postcode("100001")
    assert res.status == NIPOSTLookupStatus.UNAVAILABLE
    assert "endpoint not found" in res.error_message.lower()


def test_validate_postcode_explicit_postcode_not_found_classified_as_not_found():
    """Documented machine-readable error with matching code returns NOT_FOUND."""
    def mock_transport_doc_404(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "valid": False,
                "code": "100001",
                "status": "NOT_FOUND",
                "message": "Postcode 100001 is not registered in national directory",
            },
            headers={"content-type": "application/json"},
        )

    test_client = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="test-key",
        transport=httpx.MockTransport(mock_transport_doc_404),
    )

    res = test_client.validate_postcode("100001")
    assert res.status == NIPOSTLookupStatus.NOT_FOUND
    assert "not registered" in res.error_message.lower() or "not found" in res.error_message.lower()


# ==============================================================================
# 4. Canonical Evidence Validity & Coverage Aggregation
# ==============================================================================

def test_validate_verification_evidence_rules():
    """validate_verification_evidence enforces provider, status, method, hash, expiration, and code."""
    now_utc = datetime.now(timezone.utc)

    # 1. Valid NIPOST evidence
    ev = VerificationEvidence(
        postcode="100001",
        provider="NIPOST",
        status="verified",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        valid_until=now_utc + timedelta(days=10),
        is_active=True,
    )
    assert validate_verification_evidence(ev, expected_code="100001") is True

    # 2. Wrong provider
    ev_bad_prov = VerificationEvidence(
        postcode="100001",
        provider="OTHER_GATEWAY",
        status="verified",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        valid_until=now_utc + timedelta(days=10),
        is_active=True,
    )
    assert validate_verification_evidence(ev_bad_prov) is False

    # 3. Inactive
    ev.is_active = False
    assert validate_verification_evidence(ev) is False
    ev.is_active = True

    # 4. Expired
    ev_expired = VerificationEvidence(
        postcode="100001",
        provider="NIPOST",
        status="verified",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        valid_until=now_utc - timedelta(days=1),
        is_active=True,
    )
    assert validate_verification_evidence(ev_expired) is False

    # 5. Missing response hash
    ev_no_hash = VerificationEvidence(
        postcode="100001",
        provider="NIPOST",
        status="verified",
        verification_method="validator_autofill_pipeline",
        response_hash="",
        valid_until=now_utc + timedelta(days=10),
        is_active=True,
    )
    assert validate_verification_evidence(ev_no_hash) is False

    # 6. Mismatched postcode
    assert validate_verification_evidence(ev, expected_code="999999") is False


def test_coverage_evidence_deduplication():
    """Multiple evidence records for a single postcode do NOT inflate records_with_valid_evidence."""
    mock_db = MagicMock()
    now_utc = datetime.now(timezone.utc)

    # 1 directory record
    r1 = PostcodeDirectory(code="100001", area="Ikeja", state="Lagos", lga="Ikeja", lat=6.61, lng=3.35)

    # 3 duplicate valid evidence rows for the same code
    ev1 = VerificationEvidence(postcode="100001", provider="NIPOST", status="verified", verification_method="validator_autofill_pipeline", response_hash="a"*64, valid_until=now_utc + timedelta(days=5), is_active=True)
    ev2 = VerificationEvidence(postcode="100001", provider="NIPOST", status="verified", verification_method="validator_autofill_pipeline", response_hash="b"*64, valid_until=now_utc + timedelta(days=10), is_active=True)
    ev3 = VerificationEvidence(postcode="100001", provider="NIPOST", status="verified", verification_method="validator_autofill_pipeline", response_hash="c"*64, valid_until=now_utc + timedelta(days=15), is_active=True)

    def mock_query(model):
        q = MagicMock()
        if model == VerificationEvidence:
            q.filter.return_value.all.return_value = [ev1, ev2, ev3]
        elif model == PostcodeDirectory:
            q.all.return_value = [r1]
        return q

    mock_db.query.side_effect = mock_query

    rep = get_postcode_coverage_report(db=mock_db)
    # Distinct directory record count must be 1, NOT 3
    assert rep.total_reference_records == 1
    assert rep.records_with_valid_evidence == 1


# ==============================================================================
# 5. Integration Readiness Structured Dimensions
# ==============================================================================

def test_integration_status_separated_dimensions():
    """get_integration_status() accurately separates configuration, health, and commercial permissions."""
    client_configured = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="test-key",
    )
    status = client_configured.get_integration_status()

    assert status["adapter_installed"] is True
    assert status["configuration_complete"] is True
    assert status["base_url_set"] is True
    assert status["credentials_set"] is True
    assert status["connectivity_healthy"] is False
    assert status["authentication_verified"] is False
    assert status["contract_verified"] is False
    assert status["production_authorized"] is False
    assert status["status"] == "configured"
    assert "Awaiting Live Verification" in status["display_status"]


# ==============================================================================
# 6. Missing Metadata Null Preservation
# ==============================================================================

def test_postcode_record_schema_preserves_null_for_missing_fields():
    """PostcodeRecordSchema must preserve None for missing area and state rather than inventing defaults."""
    rec = PostcodeRecordSchema(code="100001")
    assert rec.code == "100001"
    assert rec.area is None
    assert rec.state is None
    assert rec.lga is None


def test_cleanse_address_response_preserves_null_when_metadata_missing():
    """CleanseAddressResponse preserves None for area and state when missing."""
    resp = CleanseAddressResponse(
        original_address="Somewhere in Unknown Zone",
        formatted_address="Somewhere in Unknown Zone",
        postcode="100001",
        confidence=0.5,
        postcode_status="local_match",
        source="local_directory",
    )
    assert resp.area is None
    assert resp.state is None
