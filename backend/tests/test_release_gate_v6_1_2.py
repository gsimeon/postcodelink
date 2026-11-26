"""Release Gate v6.1.2 Acceptance Test Suite:
Verification Integrity, API Contract Alignment, and Strict Evidence Persistence.

Validates the critical governance requirements of Release 6.1.2:
1. VerificationEvidence model default for dataset_version is strictly None (no fabricated '2026.1').
2. Database-backed evidence persistence gate:
   - Absence of database session or persistence failure strictly blocks 'official_verified' claims.
   - Strict mode raises HTTP 503 fail-closed when database is unavailable.
   - Non-strict mode demotes to 'local_reference', clears evidence_id, sets fallback_used=True.
3. Verification Mode Contract:
   - First-class 'verification_mode' parameter ("local_standardization" | "nipost_validate" | "nipost_strict").
   - Backwards compatibility with legacy boolean flags ('strict' and 'live_verify').
   - CleanseAddressResponse faithfully exposes effective 'verification_mode'.
4. Upstream Provenance Preservation:
   - Absence of upstream dataset version produces None, never a synthetic or hardcoded fallback.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.models.verification_evidence import VerificationEvidence
from backend.app.schemas.postcode import CleanseAddressRequest, CleanseAddressResponse
from backend.app.services.nipost_client import NIPOSTLookupStatus, NIPOSTLookupResult
from backend.app.services.postcode_service import cleanse_address
from backend.app.routers.postcodes import execute_postcode_lookup


client = TestClient(app)


# ==============================================================================
# 1. Dataset Version Governance (No Default '2026.1' in Model)
# ==============================================================================

def test_verification_evidence_model_dataset_version_default_is_none():
    """Ensure VerificationEvidence SQLAlchemy model does not define a default '2026.1'
    which previously silently fabricated upstream version provenance.
    """
    col = VerificationEvidence.__table__.columns["dataset_version"]
    assert col.default is None, f"Expected dataset_version column default to be None, got: {col.default}"


# ==============================================================================
# 2. Strict Evidence Persistence Gate (No DB Session or DB Failure)
# ==============================================================================

def test_cleanse_address_db_none_strict_mode_fails_closed_503():
    """When strict verification is requested but no database session is available,
    the service must fail closed with HTTP 503 rather than claiming verification.
    """
    mock_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "105102",
            "area": "Lekki Phase 1",
            "state": "Lagos",
            "lga": "Eti-Osa",
        },
    )

    with patch("backend.app.services.nipost_client.NIPOSTClient.is_configured", True), \
         patch("backend.app.services.nipost_client.NIPOSTClient.upstream_environment", "production"), \
         patch("backend.app.services.nipost_client.NIPOSTClient.lookup_postcode", return_value=mock_result), \
         patch("backend.app.services.nipost_client.NIPOSTClient.validate_postcode", return_value=mock_result):
        with pytest.raises(HTTPException) as exc_info:
            cleanse_address(
                address="Plot 14 Admiralty Way, Lekki Phase 1, Lagos",
                postcode_hint="105102",
                db=None,
                strict=True,
            )
        assert exc_info.value.status_code == 503
        assert "Database session required for official verification evidence persistence" in exc_info.value.detail


def test_cleanse_address_db_none_non_strict_demotes_to_local_reference():
    """When db=None in non-strict mode, live NIPOST response must be demoted:
    - is_live_nipost=False
    - verification_status='local_reference'
    - evidence_id=None
    - fallback_used=True
    """
    mock_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "105102",
            "area": "Lekki Phase 1",
            "state": "Lagos",
            "lga": "Eti-Osa",
        },
    )

    with patch("backend.app.services.nipost_client.NIPOSTClient.is_configured", True), \
         patch("backend.app.services.nipost_client.NIPOSTClient.upstream_environment", "production"), \
         patch("backend.app.services.nipost_client.NIPOSTClient.lookup_postcode", return_value=mock_result), \
         patch("backend.app.services.nipost_client.NIPOSTClient.validate_postcode", return_value=mock_result):
        res = cleanse_address(
            address="Plot 14 Admiralty Way, Lekki Phase 1, Lagos",
            postcode_hint="105102",
            db=None,
            live_verify=True,
            strict=False,
        )
        assert res.is_live_nipost is False
        assert res.verification_status == "local_reference"
        assert res.evidence_id is None
        assert res.fallback_used is True
        assert res.source_owner == "PostcodeLink"
        assert "database unavailable" in res.provenance.lower() or "persistence failed" in res.provenance.lower()


def test_execute_postcode_lookup_db_none_strict_mode_fails_closed_503():
    """execute_postcode_lookup must fail closed with HTTP 503 when strict=True and db=None."""
    mock_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "105102",
            "area": "Lekki Phase 1",
            "state": "Lagos",
            "lga": "Eti-Osa",
        },
    )

    with patch("backend.app.services.nipost_client.NIPOSTClient.is_configured", True), \
         patch("backend.app.services.nipost_client.NIPOSTClient.upstream_environment", "production"), \
         patch("backend.app.services.nipost_client.NIPOSTClient.lookup_postcode", return_value=mock_result), \
         patch("backend.app.services.nipost_client.NIPOSTClient.validate_postcode", return_value=mock_result):
        with pytest.raises(HTTPException) as exc_info:
            execute_postcode_lookup(
                db=None,
                code="105102",
                strict=True,
            )
        assert exc_info.value.status_code == 503
        assert "Database session required for official verification evidence persistence" in exc_info.value.detail


def test_execute_postcode_lookup_db_none_non_strict_demotes():
    """execute_postcode_lookup with db=None in non-strict mode demotes to local reference."""
    mock_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "105102",
            "area": "Lekki Phase 1",
            "state": "Lagos",
            "lga": "Eti-Osa",
        },
    )

    with patch("backend.app.services.nipost_client.NIPOSTClient.is_configured", True), \
         patch("backend.app.services.nipost_client.NIPOSTClient.upstream_environment", "production"), \
         patch("backend.app.services.nipost_client.NIPOSTClient.lookup_postcode", return_value=mock_result), \
         patch("backend.app.services.nipost_client.NIPOSTClient.validate_postcode", return_value=mock_result):
        res = execute_postcode_lookup(
            db=None,
            code="105102",
            strict=False,
        )
        assert res.is_live_nipost is False
        assert res.verification_status == "local_reference"
        assert res.fallback_used is True
        assert res.matches[0].evidence_id is None
        assert res.matches[0].source_owner == "PostcodeLink"


# ==============================================================================
# 3. Verification Mode Contract & Backwards Compatibility
# ==============================================================================

def test_api_cleanse_address_explicit_local_standardization_mode():
    """Calling /cleanse with verification_mode='local_standardization' executes offline
    standardization without querying upstream NIPOST.
    """
    with patch("backend.app.services.nipost_client.NIPOSTClient.lookup_postcode") as mock_lookup:
        resp = client.post("/api/v1/postcodes/cleanse", json={
            "address": "Plot 14 Admiralty Way, Lekki Phase 1, Lagos",
            "postcode": "105102",
            "verification_mode": "local_standardization",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["verification_mode"] == "local_standardization"
        assert data["checked_against_nipost"] is False
        assert data["is_live_nipost"] is False
        assert not mock_lookup.called


def test_api_cleanse_address_explicit_nipost_strict_mode():
    """Calling /cleanse with verification_mode='nipost_strict' fails closed when upstream fails."""
    val_unavail = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.UNAVAILABLE,
        error_message="Gateway timeout connecting to upstream NIPOST.",
    )

    with patch("backend.app.services.nipost_client.NIPOSTClient.is_configured", True), \
         patch("backend.app.services.nipost_client.NIPOSTClient.upstream_environment", "production"), \
         patch("backend.app.services.nipost_client.NIPOSTClient.validate_postcode", return_value=val_unavail), \
         patch("backend.app.services.nipost_client.NIPOSTClient.lookup_postcode", return_value=val_unavail):
        resp = client.post("/api/v1/postcodes/cleanse", json={
            "address": "12 Broad Street, Marina, Lagos",
            "postcode": "100001",
            "verification_mode": "nipost_strict",
        })
        assert resp.status_code == 503
        assert "Official NIPOST API unavailable" in resp.json()["detail"]


def test_api_cleanse_address_legacy_strict_boolean_maps_to_nipost_strict():
    """Legacy clients sending strict=True are mapped to verification_mode='nipost_strict'."""
    val_unavail = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.UNAVAILABLE,
        error_message="Gateway connection reset.",
    )

    with patch("backend.app.services.nipost_client.NIPOSTClient.is_configured", True), \
         patch("backend.app.services.nipost_client.NIPOSTClient.upstream_environment", "production"), \
         patch("backend.app.services.nipost_client.NIPOSTClient.validate_postcode", return_value=val_unavail), \
         patch("backend.app.services.nipost_client.NIPOSTClient.lookup_postcode", return_value=val_unavail):
        resp = client.post("/api/v1/postcodes/cleanse", json={
            "address": "12 Broad Street, Marina, Lagos",
            "postcode": "100001",
            "strict": True,
        })
        assert resp.status_code == 503
