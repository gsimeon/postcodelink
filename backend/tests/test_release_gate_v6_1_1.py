"""Acceptance and Regression Tests for Release Gate v6.1.1.

Verifies:
1. Finding 1: Verification Evidence Persistence Gate Integrity
   - When evidence persistence fails in strict mode (cleanse or lookup), transaction is rolled back and HTTP 503 is raised fail-closed.
   - When evidence persistence fails in non-strict mode (cleanse or lookup), transaction is rolled back, response is demoted to local_reference (confidence 0.75), evidence_id is None, fallback_used is True, and NEVER claimed as official_verified.
2. Finding 2: Upstream Dataset Version Integrity
   - When upstream NIPOST omits dataset_version or returns None, response dataset_version is None (NOT fabricated '2026.1').
   - Adapter / integration version is cleanly separated into api_integration_version = '2026.1'.
   - When upstream NIPOST returns an authentic dataset_version (e.g. '2026.Q4'), it is faithfully preserved.
3. Cleanse & Lookup Schema Alignment:
   - CleanseAddressResponse includes dataset_version and api_integration_version.
"""
import pytest
from unittest.mock import patch
from fastapi import HTTPException

from backend.app.database import SessionLocal, Base, engine
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.verification_evidence import VerificationEvidence
from backend.app.services.postcode_service import cleanse_address
from backend.app.routers.postcodes import execute_postcode_lookup
from backend.app.services.nipost_client import NIPOSTLookupStatus, NIPOSTLookupResult, NIPOSTClient


# Ensure tables exist
Base.metadata.create_all(bind=engine)


# ==============================================================================
# 1. Finding 1: Verification Evidence Persistence Gate (Cleanse)
# ==============================================================================
def test_evidence_persistence_failure_strict_mode_cleanse_raises_503():
    """Verify that when evidence persistence fails in strict mode during cleanse_address,
    the transaction is rolled back and an HTTP 503 is raised fail-closed.
    """
    db = SessionLocal()
    mock_live_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "101233",
            "area": "Victoria Island",
            "state": "Lagos",
            "lga": "Eti-Osa",
            "dataset_version": None,
            "postcode_type": "conventional_area",
            "service": "autofill",
            "valid": True,
        },
    )

    try:
        orch_res = (NIPOSTLookupStatus.FOUND, mock_live_result.data, None, "validator_autofill_pipeline")
        with patch.object(NIPOSTClient, "is_configured", True), \
             patch.object(NIPOSTClient, "upstream_environment", "production"), \
             patch.object(NIPOSTClient, "lookup_postcode", return_value=mock_live_result), \
             patch.object(NIPOSTClient, "orchestrated_verify", return_value=orch_res):
            with patch.object(db, "commit", side_effect=RuntimeError("Disk I/O error or constraint failure")):
                with patch.object(db, "rollback") as mock_rollback:
                    with pytest.raises(HTTPException) as exc_info:
                        cleanse_address(
                            address="Plot 10 Adeola Odeku, Victoria Island, Lagos",
                            postcode_hint="101233",
                            live_verify=True,
                            strict=True,
                            db=db,
                        )

                    # Must fail-closed with 503
                    assert exc_info.value.status_code == 503
                    assert "Verification evidence" in str(exc_info.value.detail) or "persistence" in str(exc_info.value.detail).lower()
                    mock_rollback.assert_called()
    finally:
        db.close()


def test_evidence_persistence_failure_non_strict_cleanse_demotes_to_local_reference():
    """Verify that when evidence persistence fails in non-strict mode during cleanse_address,
    the transaction is rolled back, the result is demoted to local_reference (confidence 0.75),
    evidence_id is None, fallback_used is True, and official_verified is NEVER claimed.
    """
    db = SessionLocal()
    mock_live_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "101233",
            "area": "Victoria Island",
            "state": "Lagos",
            "lga": "Eti-Osa",
            "dataset_version": None,
            "postcode_type": "conventional_area",
            "service": "autofill",
            "valid": True,
        },
    )

    try:
        orch_res = (NIPOSTLookupStatus.FOUND, mock_live_result.data, None, "validator_autofill_pipeline")
        with patch.object(NIPOSTClient, "is_configured", True), \
             patch.object(NIPOSTClient, "upstream_environment", "production"), \
             patch.object(NIPOSTClient, "lookup_postcode", return_value=mock_live_result), \
             patch.object(NIPOSTClient, "orchestrated_verify", return_value=orch_res):
            with patch.object(db, "commit", side_effect=RuntimeError("Transient DB connection drop")):
                with patch.object(db, "rollback") as mock_rollback:
                    res = cleanse_address(
                        address="Plot 10 Adeola Odeku, Victoria Island, Lagos",
                        postcode_hint="101233",
                        live_verify=True,
                        strict=False,
                        db=db,
                    )

                    mock_rollback.assert_called()

                    # Verification status must NOT be official_verified
                    assert res.verification_status == "local_reference"
                    assert res.postcode_status == "local_match"
                    assert res.confidence == 0.75
                    assert res.dispatch_confidence == 0.75
                    assert res.evidence_id is None
                    assert res.fallback_used is True
                    assert any("Downgraded" in c or "persistence failed" in c for c in res.changes_made)
    finally:
        db.close()


# ==============================================================================
# 2. Finding 1: Verification Evidence Persistence Gate (Lookup)
# ==============================================================================
def test_evidence_persistence_failure_strict_mode_lookup_raises_503():
    """Verify that when evidence persistence fails in strict mode during execute_postcode_lookup,
    the transaction is rolled back and an HTTP 503 is raised.
    """
    db = SessionLocal()
    mock_live_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "101244",
            "area": "Oniru",
            "state": "Lagos",
            "lga": "Ibeju-Lekki",
            "dataset_version": None,
            "postcode_type": "conventional_area",
            "service": "autofill",
            "valid": True,
        },
    )

    try:
        orch_res = (NIPOSTLookupStatus.FOUND, mock_live_result.data, None, "validator_autofill_pipeline")
        with patch.object(NIPOSTClient, "is_configured", True), \
             patch.object(NIPOSTClient, "upstream_environment", "production"), \
             patch.object(NIPOSTClient, "lookup_postcode", return_value=mock_live_result), \
             patch.object(NIPOSTClient, "orchestrated_verify", return_value=orch_res):
            with patch.object(db, "commit", side_effect=RuntimeError("DB write failure")):
                with patch.object(db, "rollback") as mock_rollback:
                    with pytest.raises(HTTPException) as exc_info:
                        execute_postcode_lookup(
                            db=db,
                            code="101244",
                            strict=True,
                        )

                    assert exc_info.value.status_code == 503
                    assert "Verification evidence" in str(exc_info.value.detail) or "persistence" in str(exc_info.value.detail).lower()
                    mock_rollback.assert_called()
    finally:
        db.close()


def test_evidence_persistence_failure_non_strict_lookup_demotes_to_local_reference():
    """Verify that when evidence persistence fails in non-strict mode during execute_postcode_lookup,
    the transaction is rolled back, the lookup result is demoted to local_reference,
    evidence_id is None, and fallback_used is True.
    """
    db = SessionLocal()
    mock_live_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "101244",
            "area": "Oniru",
            "state": "Lagos",
            "lga": "Ibeju-Lekki",
            "dataset_version": None,
            "postcode_type": "conventional_area",
            "service": "autofill",
            "valid": True,
        },
    )

    try:
        orch_res = (NIPOSTLookupStatus.FOUND, mock_live_result.data, None, "validator_autofill_pipeline")
        with patch.object(NIPOSTClient, "is_configured", True), \
             patch.object(NIPOSTClient, "upstream_environment", "production"), \
             patch.object(NIPOSTClient, "lookup_postcode", return_value=mock_live_result), \
             patch.object(NIPOSTClient, "orchestrated_verify", return_value=orch_res):
            with patch.object(db, "commit", side_effect=RuntimeError("DB write failure")):
                with patch.object(db, "rollback") as mock_rollback:
                    res = execute_postcode_lookup(
                        db=db,
                        code="101244",
                        strict=False,
                    )

                    mock_rollback.assert_called()
                    assert res.verification_status == "local_reference"
                    assert res.evidence_id is None
                    assert res.fallback_used is True
                    assert len(res.matches) == 1
                    assert res.matches[0].verification_status == "local_reference"
                    assert res.matches[0].evidence_id is None
    finally:
        db.close()


# ==============================================================================
# 3. Finding 2: Upstream Dataset Version Integrity
# ==============================================================================
def test_dataset_version_integrity_cleanse_omits_fabricated_version():
    """Verify that when upstream NIPOST returns dataset_version=None,
    cleanse_address returns dataset_version=None (NOT fabricated '2026.1'),
    and api_integration_version='2026.1'.
    """
    db = SessionLocal()
    mock_live_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "101233",
            "area": "Victoria Island",
            "state": "Lagos",
            "lga": "Eti-Osa",
            "dataset_version": None,  # Upstream omits version
            "postcode_type": "conventional_area",
            "service": "autofill",
            "valid": True,
        },
    )

    try:
        orch_res = (NIPOSTLookupStatus.FOUND, mock_live_result.data, None, "validator_autofill_pipeline")
        with patch.object(NIPOSTClient, "is_configured", True), \
             patch.object(NIPOSTClient, "upstream_environment", "production"), \
             patch.object(NIPOSTClient, "lookup_postcode", return_value=mock_live_result), \
             patch.object(NIPOSTClient, "orchestrated_verify", return_value=orch_res):
            res = cleanse_address(
                address="Plot 10 Adeola Odeku, Victoria Island, Lagos",
                postcode_hint="101233",
                live_verify=True,
                strict=False,
                db=db,
            )

            # Must be None, NEVER fabricated '2026.1'
            assert res.dataset_version is None
            # Adapter version is preserved
            assert res.api_integration_version == "2026.1"
            assert res.verification_status == "official_verified"
            assert res.evidence_id is not None
    finally:
        db.close()


def test_dataset_version_integrity_lookup_omits_fabricated_version():
    """Verify that when upstream NIPOST returns dataset_version=None,
    execute_postcode_lookup returns dataset_version=None (NOT fabricated '2026.1'),
    and api_integration_version='2026.1'.
    """
    db = SessionLocal()
    mock_live_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "101233",
            "area": "Victoria Island",
            "state": "Lagos",
            "lga": "Eti-Osa",
            "dataset_version": None,  # Upstream omits version
            "postcode_type": "conventional_area",
            "service": "autofill",
            "valid": True,
        },
    )

    try:
        orch_res = (NIPOSTLookupStatus.FOUND, mock_live_result.data, None, "validator_autofill_pipeline")
        with patch.object(NIPOSTClient, "is_configured", True), \
             patch.object(NIPOSTClient, "upstream_environment", "production"), \
             patch.object(NIPOSTClient, "lookup_postcode", return_value=mock_live_result), \
             patch.object(NIPOSTClient, "orchestrated_verify", return_value=orch_res):
            res = execute_postcode_lookup(
                db=db,
                code="101233",
                strict=False,
            )

            assert res.dataset_version is None
            assert res.api_integration_version == "2026.1"
            assert res.verification_status == "official_verified"
    finally:
        db.close()


def test_dataset_version_preserved_when_provided_by_upstream():
    """Verify that when upstream NIPOST returns an authentic dataset_version (e.g. '2026.Q4'),
    both cleanse_address and execute_postcode_lookup preserve it accurately.
    """
    db = SessionLocal()
    mock_live_result = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.FOUND,
        data={
            "code": "101233",
            "area": "Victoria Island",
            "state": "Lagos",
            "lga": "Eti-Osa",
            "dataset_version": "2026.Q4",  # Upstream supplies version
            "postcode_type": "conventional_area",
            "service": "autofill",
            "valid": True,
        },
    )

    try:
        orch_res = (NIPOSTLookupStatus.FOUND, mock_live_result.data, None, "validator_autofill_pipeline")
        with patch.object(NIPOSTClient, "is_configured", True), \
             patch.object(NIPOSTClient, "upstream_environment", "production"), \
             patch.object(NIPOSTClient, "lookup_postcode", return_value=mock_live_result), \
             patch.object(NIPOSTClient, "orchestrated_verify", return_value=orch_res):
            cleanse_res = cleanse_address(
                address="Plot 10 Adeola Odeku, Victoria Island, Lagos",
                postcode_hint="101233",
                live_verify=True,
                strict=False,
                db=db,
            )
            assert cleanse_res.dataset_version == "2026.Q4"
            assert cleanse_res.api_integration_version == "2026.1"

            lookup_res = execute_postcode_lookup(
                db=db,
                code="101233",
                strict=False,
            )
            assert lookup_res.dataset_version == "2026.Q4"
            assert lookup_res.api_integration_version == "2026.1"
    finally:
        db.close()
