"""Release Gate v6.1.3 Acceptance Test Suite:
API and Verification Integrity, Heuristic Match Quality, and Adapter Hardening.

Validates the critical governance requirements of Release 6.1.3:
1. Strict Verification Mode Validation:
   - VerificationMode = Literal["local_standardization", "nipost_validate", "nipost_strict"]
   - Invalid mode strings (e.g. "nipost_strcit") rejected with HTTP 422 Unprocessable Content.
   - Contradictory inputs (e.g. verification_mode="local_standardization" with strict=True
     or live_verify=True) rejected with HTTP 422 Unprocessable Content.
2. Disentangled Verification Semantics:
   - Upstream contact is decoupled from positive verification.
   - Negative responses (NOT_FOUND, INVALID_INPUT) return upstream_contacted=True,
     postcode_exists=False, is_live_nipost=False, and match_quality_score=0.0.
   - Positive responses (FOUND) return upstream_contacted=True, postcode_exists=True,
     and is_live_nipost=True ONLY when backed by persisted evidence.
3. Calibrated Heuristic Match Quality:
   - match_quality_score field is populated and explicitly exposed in CleanseAddressResponse.
4. NIPOST Adapter Configuration Hardening:
   - NIPOSTClient.is_configured requires BOTH base_url AND api_key.
   - configuration_complete reflects full credential state.
   - get_integration_status() and check_health() provide structured operational readiness.
5. Postcode Coverage & Readiness Reporting:
   - GET /api/v1/postcodes/coverage returns edition 2024.2, 11 states covered,
     record counts, coordinates, digital building codes, and adapter integration status.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.services.nipost_client import (
    NIPOSTClient,
    NIPOSTLookupStatus,
    NIPOSTLookupResult,
)
from backend.app.services.postcode_service import cleanse_address, get_postcode_coverage_report
from backend.app.routers.postcodes import execute_postcode_lookup


client = TestClient(app)


# ==============================================================================
# 1. Strict Verification Mode Validation (Pydantic Literal + Contradiction Rejection)
# ==============================================================================

def test_invalid_verification_mode_rejected_with_422():
    """Any invalid verification mode string (e.g. typos like 'nipost_strcit')
    must be strictly rejected by Pydantic schema with HTTP 422 Unprocessable Content.
    """
    res = client.post(
        "/api/v1/postcodes/cleanse",
        json={
            "address": "Plot 14 Admiralty Way, Lekki, Lagos",
            "verification_mode": "nipost_strcit",
        },
    )
    assert res.status_code == 422
    assert "Input should be 'local_standardization', 'nipost_validate' or 'nipost_strict'" in res.text


def test_contradictory_flags_local_standardization_with_strict_rejected_422():
    """Caller specifying local_standardization with strict=True is an invalid,
    contradictory contract that must fail validation with HTTP 422.
    """
    res = client.post(
        "/api/v1/postcodes/cleanse",
        json={
            "address": "Plot 14 Admiralty Way, Lekki, Lagos",
            "verification_mode": "local_standardization",
            "strict": True,
        },
    )
    assert res.status_code == 422
    assert "Contradictory parameters" in res.text


def test_contradictory_flags_local_standardization_with_live_verify_rejected_422():
    """Caller specifying local_standardization with live_verify=True is an invalid,
    contradictory contract that must fail validation with HTTP 422.
    """
    res = client.post(
        "/api/v1/postcodes/cleanse",
        json={
            "address": "Plot 14 Admiralty Way, Lekki, Lagos",
            "verification_mode": "local_standardization",
            "live_verify": True,
        },
    )
    assert res.status_code == 422
    assert "Contradictory parameters" in res.text


# ==============================================================================
# 2. NIPOST Adapter Configuration Hardening
# ==============================================================================

def test_nipost_client_configuration_requires_both_base_url_and_api_key():
    """configuration_complete must return False if either base_url or api_key
    is missing, empty, or whitespace.
    """
    # Missing api_key
    client1 = NIPOSTClient(base_url="https://api.nipost.gov.ng", api_key="")
    assert client1.configuration_complete is False
    assert client1.adapter_installed is True

    # Missing base_url
    client2 = NIPOSTClient(base_url="", api_key="secret-key")
    assert client2.configuration_complete is False

    # Fully configured
    client3 = NIPOSTClient(base_url="https://api.nipost.gov.ng", api_key="secret-key")
    assert client3.configuration_complete is True
    assert client3.adapter_installed is True


def test_nipost_client_integration_status_and_health_unconfigured():
    """Unconfigured NIPOST client reports honest status and health without exception."""
    c = NIPOSTClient(base_url="", api_key="")
    status = c.get_integration_status()
    assert status["adapter_installed"] is True
    assert status["configuration_complete"] is False
    assert status["base_url_set"] is False
    assert status["credentials_set"] is False
    assert status["auth_scheme"] == "x-api-key"
    assert status["status"] == "unconfigured"

    health = c.check_health()
    assert health["healthy"] is False
    assert "Configuration incomplete" in health["reason"]


# ==============================================================================
# 3. Disentangled Verification Semantics (Negative Upstream Responses)
# ==============================================================================

def test_negative_nipost_response_not_found_semantics():
    """When NIPOST returns NOT_FOUND, the response must have:
    - is_live_nipost = False (must NEVER be True)
    - upstream_contacted = True
    - postcode_exists = False
    - match_quality_score = 0.0
    - postcode_status = 'unverified'
    """
    mock_client = MagicMock(spec=NIPOSTClient)
    mock_client.is_configured = True
    mock_client.lookup_postcode.return_value = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.NOT_FOUND,
        error_message="Postal code 999999 not registered in national database.",
        http_status=404,
    )
    mock_db = MagicMock()

    resp = cleanse_address(
        address="Nonexistent Street 999999",
        postcode_hint="999999",
        verification_mode="nipost_validate",
        client=mock_client,
        db=mock_db,
    )

    assert resp.is_live_nipost is False
    assert resp.upstream_contacted is True
    assert resp.postcode_exists is False
    assert resp.match_quality_score == 0.0
    assert resp.postcode_status == "unverified"
    assert resp.confidence == 0.0
    assert resp.dispatch_confidence == 0.0


def test_negative_nipost_response_invalid_input_semantics():
    """When NIPOST returns INVALID_INPUT in non-strict mode:
    - is_live_nipost = False
    - upstream_contacted = True
    - postcode_exists = False
    - match_quality_score = 0.0
    """
    mock_client = MagicMock(spec=NIPOSTClient)
    mock_client.is_configured = True
    mock_client.lookup_postcode.return_value = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.INVALID_INPUT,
        error_message="Invalid postcode format: abc",
        http_status=422,
    )
    mock_db = MagicMock()

    resp = cleanse_address(
        address="Somewhere in Lagos",
        postcode_hint="abc",
        verification_mode="nipost_validate",
        client=mock_client,
        db=mock_db,
    )

    assert resp.is_live_nipost is False
    assert resp.upstream_contacted is True
    assert resp.postcode_exists is False
    assert resp.match_quality_score == 0.0


def test_positive_nipost_response_evidence_persisted_semantics():
    """When NIPOST returns FOUND and evidence is persisted in DB:
    - is_live_nipost = True
    - upstream_contacted = True
    - postcode_exists = True
    - match_quality_score >= 0.9
    - verification_status = 'official_verified'
    """
    mock_client = MagicMock(spec=NIPOSTClient)
    mock_client.is_configured = True
    mock_client.lookup_postcode.return_value = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "105102",
            "area": "Lekki Phase 1",
            "state": "Lagos",
            "lga": "Eti-Osa",
            "postcode_type": "conventional_area",
            "postcode_category": "official_postal_district",
            "resolution_level": "area_dispatch",
            "source_owner": "NIPOST",
            "source_type": "official_directory",
            "dataset_version": "2026.1",
        },
        http_status=200,
    )

    mock_db = MagicMock()
    # Mock successful DB evidence persistence
    mock_db.commit = MagicMock()
    mock_db.refresh = MagicMock()

    resp = cleanse_address(
        address="Plot 14 Admiralty Way, Lekki Phase 1, Lagos",
        postcode_hint="105102",
        verification_mode="nipost_validate",
        client=mock_client,
        db=mock_db,
    )

    assert resp.is_live_nipost is True
    assert resp.upstream_contacted is True
    assert resp.postcode_exists is True
    assert resp.match_quality_score == 0.95
    assert resp.postcode_status == "verified"
    assert resp.verification_status == "official_verified"


# ==============================================================================
# 4. Postcode Coverage & Readiness Reporting
# ==============================================================================

def test_coverage_endpoint_returns_verifiable_metrics():
    """GET /api/v1/postcodes/coverage must return 200 with edition 2024.2,
    at least 11 states, total reference postcodes, coordinates, and adapter status.
    """
    res = client.get("/api/v1/postcodes/coverage")
    assert res.status_code == 200
    data = res.json()

    assert data["version"] == "2024.2"
    assert data["scope_states_count"] >= 11
    assert "Lagos" in data["states_covered"]
    assert "Abuja FCT" in data["states_covered"]
    assert "Rivers" in data["states_covered"]
    assert data["total_reference_records"] >= 30
    assert data["records_with_coordinates"] > 0
    assert data["digital_building_level_records"] > 0

    # Verify adapter status structure
    adapter_status = data["upstream_integration"]
    assert adapter_status["adapter_installed"] is True
    assert "configuration_complete" in adapter_status
    assert "auth_scheme" in adapter_status
    assert "display_status" in adapter_status


def test_postcode_lookup_upstream_semantics_on_not_found():
    """execute_postcode_lookup returns upstream_contacted=True and
    postcode_exists=False when upstream NIPOST returns NOT_FOUND.
    """
    mock_client = MagicMock(spec=NIPOSTClient)
    mock_client.lookup_postcode.return_value = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.NOT_FOUND,
        error_message="Not found in live directory",
        http_status=404,
    )
    mock_db = MagicMock()

    resp = execute_postcode_lookup(
        db=mock_db,
        code="999999",
        strict=False,
        client=mock_client,
    )

    assert resp.is_live_nipost is False
    assert resp.upstream_contacted is True
    assert resp.postcode_exists is False
    assert resp.lookup_status == "not_found"
    assert resp.verification_status == "unverified"
    assert resp.upstream_contacted is True
    assert resp.postcode_exists is False
    assert resp.lookup_status == "not_found"
    assert resp.verification_status == "unverified"
