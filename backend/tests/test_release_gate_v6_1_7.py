"""Release Gate v6.1.7 Test Suite: Verification Evidence Integrity,
Active Directory Coverage Filtering, Clean Router Orchestration & Modular Workspace.

Tests:
1. P1: Explicit Active Evidence Validation in classify_verification_evidence():
   - is_active is None or missing -> "incomplete"
   - is_active is False -> "rejected"
   - is_active is True with valid fields -> "valid"
2. P1: 64-Character Hexadecimal SHA-256 Digest Validation:
   - missing/empty response_hash -> "incomplete"
   - non-hex character (e.g. contains 'g' or 'z') -> "invalid"
   - malformed length (e.g. 32 or 63 characters) -> "invalid"
   - 64-character hexadecimal SHA-256 digest -> "valid"
3. P1: Strict Coupling of Verification Method & Evidence Status:
   - validator_autofill_pipeline must be "verified" (partial/other -> "invalid")
   - validator must be "partial" (verified/other -> "invalid")
   - autofill alone must never qualify as official verification -> "invalid"
4. P1: Filter Inactive Directory Records from Coverage:
   - Inactive/soft-deleted PostcodeDirectory records excluded from total records,
     states represented, records per state, and verified-record coverage.
5. P2: Remove Test-Specific Mocking Detection from Production Routers & Services:
   - routers/postcodes.py and services/postcode_service.py contain zero MagicMock references,
     no _ORIGINAL_LOOKUP_POSTCODE, and no has_mocked_lookup_only branches.
   - Single clean execution path calling client.orchestrated_verify(code).
6. P2: Explicit Dataset Fallback Contract:
   - CoverageReportResponse returns dataset_source == "database_directory" when database has records.
   - Returns dataset_source == "demonstration_fallback" when falling back to OFFICIAL_POSTCODES.
7. P2: Transactional Evidence Persistence Service:
   - record_verification_evidence() creates unexpired, hex-hashed evidence transactionally.
   - Rolls back on DB errors and fails closed.
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.verification_evidence import VerificationEvidence
from backend.app.services.postcode_service import (
    classify_verification_evidence,
    validate_verification_evidence,
    get_postcode_coverage_report,
    record_verification_evidence,
    cleanse_address,
)
from backend.app.services.nipost_client import NIPOSTLookupStatus, NIPOSTLookupResult, NIPOSTClient


client = TestClient(app)


# ==============================================================================
# 1. P1: Explicit Active Evidence Validation
# ==============================================================================

def test_classify_verification_evidence_requires_explicit_true_is_active():
    """classify_verification_evidence requires getattr(evidence, 'is_active', None) is True.
    None or missing is_active attribute must return 'incomplete', while False returns 'rejected'.
    """
    now_utc = datetime.now(timezone.utc)
    base_evidence_kwargs = {
        "postcode": "100001",
        "provider": "NIPOST",
        "status": "verified",
        "verification_method": "validator_autofill_pipeline",
        "response_hash": "a" * 64,
        "valid_until": now_utc + timedelta(days=10),
    }

    # 1. Explicitly active -> valid
    ev_active = VerificationEvidence(**base_evidence_kwargs, is_active=True)
    assert classify_verification_evidence(ev_active) == "valid"

    # 2. Explicitly inactive (is_active=False) -> rejected
    ev_inactive = VerificationEvidence(**base_evidence_kwargs, is_active=False)
    assert classify_verification_evidence(ev_inactive) == "rejected"

    # 3. Missing or None is_active -> incomplete
    class DummyEvidence:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    ev_none_active = DummyEvidence(**base_evidence_kwargs, is_active=None)
    assert classify_verification_evidence(ev_none_active) == "incomplete"

    # 4. Without is_active attribute entirely -> incomplete
    ev_missing_active = DummyEvidence(**base_evidence_kwargs)
    assert not hasattr(ev_missing_active, "is_active")
    assert classify_verification_evidence(ev_missing_active) == "incomplete"


# ==============================================================================
# 2. P1: 64-Character Hexadecimal SHA-256 Digest Validation
# ==============================================================================

def test_classify_verification_evidence_enforces_64_char_hex_hash():
    """classify_verification_evidence strictly enforces 64-character hexadecimal SHA-256 digest format."""
    now_utc = datetime.now(timezone.utc)
    base_evidence_kwargs = {
        "postcode": "100001",
        "provider": "NIPOST",
        "status": "verified",
        "verification_method": "validator_autofill_pipeline",
        "valid_until": now_utc + timedelta(days=10),
        "is_active": True,
    }

    # 1. Empty or missing hash -> incomplete
    ev_empty_hash = VerificationEvidence(**base_evidence_kwargs, response_hash="")
    assert classify_verification_evidence(ev_empty_hash) == "incomplete"

    # 2. Non-hex characters (contains 'g', 'z', symbols) -> invalid
    ev_non_hex = VerificationEvidence(**base_evidence_kwargs, response_hash="g" * 64)
    assert classify_verification_evidence(ev_non_hex) == "invalid"

    ev_symbols = VerificationEvidence(**base_evidence_kwargs, response_hash=("a" * 60) + "!!@@")
    assert classify_verification_evidence(ev_symbols) == "invalid"

    # 3. Malformed length (short string: 32 chars MD5 or arbitrary short tokens) -> invalid
    ev_short_hash = VerificationEvidence(**base_evidence_kwargs, response_hash="a" * 32)
    assert classify_verification_evidence(ev_short_hash) == "invalid"

    ev_63_hash = VerificationEvidence(**base_evidence_kwargs, response_hash="a" * 63)
    assert classify_verification_evidence(ev_63_hash) == "invalid"

    ev_65_hash = VerificationEvidence(**base_evidence_kwargs, response_hash="a" * 65)
    assert classify_verification_evidence(ev_65_hash) == "invalid"

    # 4. Valid 64-character lowercase and uppercase hex -> valid
    ev_valid_lower = VerificationEvidence(**base_evidence_kwargs, response_hash="0123456789abcdef" * 4)
    assert classify_verification_evidence(ev_valid_lower) == "valid"

    ev_valid_upper = VerificationEvidence(**base_evidence_kwargs, response_hash="0123456789ABCDEF" * 4)
    assert classify_verification_evidence(ev_valid_upper) == "valid"


# ==============================================================================
# 3. P1: Strict Coupling of Verification Method & Evidence Status
# ==============================================================================

def test_classify_verification_evidence_method_status_coupling_matrix():
    """classify_verification_evidence enforces strict verification method and status coupling matrix:
    - validator_autofill_pipeline -> status must be 'verified'
    - validator -> status must be 'partial'
    - autofill -> alone cannot verify existence; returns 'invalid'
    """
    now_utc = datetime.now(timezone.utc)
    base_evidence_kwargs = {
        "postcode": "100001",
        "provider": "NIPOST",
        "response_hash": "a" * 64,
        "valid_until": now_utc + timedelta(days=10),
        "is_active": True,
    }

    # 1. Pipeline + verified -> valid
    ev1 = VerificationEvidence(**base_evidence_kwargs, verification_method="validator_autofill_pipeline", status="verified")
    assert classify_verification_evidence(ev1) == "valid"

    # 2. Pipeline + partial -> invalid
    ev2 = VerificationEvidence(**base_evidence_kwargs, verification_method="validator_autofill_pipeline", status="partial")
    assert classify_verification_evidence(ev2) == "invalid"

    # 3. Validator + partial -> valid
    ev3 = VerificationEvidence(**base_evidence_kwargs, verification_method="validator", status="partial")
    assert classify_verification_evidence(ev3) == "valid"

    # 4. Validator + verified -> invalid (validator only confirms existence, not full administrative metadata)
    ev4 = VerificationEvidence(**base_evidence_kwargs, verification_method="validator", status="verified")
    assert classify_verification_evidence(ev4) == "invalid"

    # 5. Autofill alone + verified -> invalid (autofill alone cannot establish Validator existence)
    ev5 = VerificationEvidence(**base_evidence_kwargs, verification_method="autofill", status="verified")
    assert classify_verification_evidence(ev5) == "invalid"

    # 6. Autofill alone + partial -> invalid
    ev6 = VerificationEvidence(**base_evidence_kwargs, verification_method="autofill", status="partial")
    assert classify_verification_evidence(ev6) == "invalid"


# ==============================================================================
# 4. P1: Inactive Directory Records Excluded from Coverage Report
# ==============================================================================

def test_coverage_report_excludes_inactive_directory_records():
    """get_postcode_coverage_report excludes inactive (is_active=False) directory records
    from total records, states covered, and records per state.
    """
    mock_db = MagicMock()
    now_utc = datetime.now(timezone.utc)

    # 2 active records in Lagos, 1 active record in Kano
    r1 = PostcodeDirectory(code="100001", state="Lagos", area="Ikeja", lga="Ikeja", lat=6.5, lng=3.3, is_active=True)
    r2 = PostcodeDirectory(code="100271", state="Lagos", area="Ikeja GRA", lga="Ikeja", lat=6.5, lng=3.3, is_active=True)
    r3 = PostcodeDirectory(code="700001", state="Kano", area="Kano Central", lga="Kano Municipal", lat=12.0, lng=8.5, is_active=True)

    # 2 inactive records (1 in Lagos, 1 in Rivers)
    r_inactive_lagos = PostcodeDirectory(code="109999", state="Lagos", area="Old Ikeja", lga="Ikeja", lat=6.5, lng=3.3, is_active=False)
    r_inactive_rivers = PostcodeDirectory(code="500999", state="Rivers", area="Old PH", lga="Port Harcourt", lat=4.8, lng=7.0, is_active=False)

    ev_valid = VerificationEvidence(
        postcode="100001",
        provider="NIPOST",
        verification_method="validator_autofill_pipeline",
        response_hash="a" * 64,
        status="verified",
        valid_until=now_utc + timedelta(days=15),
        is_active=True,
    )

    def mock_query(model):
        q = MagicMock()
        if model == VerificationEvidence:
            q.all.return_value = [ev_valid]
        elif model == PostcodeDirectory:
            # When filtered by PostcodeDirectory.is_active == True, returns only active records
            q.filter.return_value.all.return_value = [r1, r2, r3]
            # Fallback all() returns all 5 records to verify in-memory filtering as well
            q.all.return_value = [r1, r2, r3, r_inactive_lagos, r_inactive_rivers]
        return q

    mock_db.query.side_effect = mock_query

    rep = get_postcode_coverage_report(db=mock_db)

    # Total reference records must be exactly 3 (excluding the 2 inactive records)
    assert rep.total_reference_records == 3
    # Scope states count must be 2 (Lagos and Kano), Rivers must NOT be present
    assert rep.scope_states_count == 2
    assert "Rivers" not in rep.states_covered
    assert "Lagos" in rep.states_covered
    assert "Kano" in rep.states_covered
    # Lagos count must be 2, not 3
    assert rep.records_per_state.get("Lagos") == 2
    assert rep.records_per_state.get("Kano") == 1
    assert "Rivers" not in rep.records_per_state
    # Dataset source must be database_directory
    assert rep.dataset_source == "database_directory"


# ==============================================================================
# 5. P2: Dataset Source Contract
# ==============================================================================

def test_coverage_report_dataset_source_fallback_contract():
    """get_postcode_coverage_report discloses dataset_source as 'demonstration_fallback'
    when database is empty or absent.
    """
    mock_db = MagicMock()

    def mock_query(model):
        q = MagicMock()
        q.all.return_value = []
        q.filter.return_value.all.return_value = []
        return q

    mock_db.query.side_effect = mock_query

    rep = get_postcode_coverage_report(db=mock_db)
    assert rep.total_reference_records > 0
    assert rep.dataset_source == "demonstration_fallback"
    assert rep.source == "demonstration_fallback"


# ==============================================================================
# 6. P2: Router Cleanliness & Purity (No Mock Detection)
# ==============================================================================

def test_production_router_and_service_have_no_mock_detection_code():
    """Verify that backend/app/routers/postcodes.py and backend/app/services/postcode_service.py
    contain no test-specific MagicMock imports or monkeypatch-checking branching.
    """
    import inspect
    from backend.app.routers import postcodes as postcodes_router
    from backend.app.services import postcode_service

    router_source = inspect.getsource(postcodes_router)
    service_source = inspect.getsource(postcode_service)

    # 1. No MagicMock imports in router or service
    assert "from unittest.mock import MagicMock" not in router_source
    assert "import MagicMock" not in router_source
    assert "from unittest.mock import MagicMock" not in service_source

    # 2. No _ORIGINAL_ function pointers
    assert "_ORIGINAL_LOOKUP_POSTCODE" not in router_source
    assert "_ORIGINAL_VALIDATE_POSTCODE" not in router_source

    # 3. No has_mocked_lookup_only branches
    assert "has_mocked_lookup_only" not in router_source
    assert "has_mocked_lookup_only" not in service_source


# ==============================================================================
# 7. P2: Transactional Evidence Persistence Service
# ==============================================================================

def test_record_verification_evidence_transactional_boundary():
    """record_verification_evidence computes 64-char sha256 hash and persists evidence,
    or rolls back on database failure.
    """
    mock_db = MagicMock()
    live_res = {
        "code": "100001",
        "area": "Ikeja Central",
        "state": "Lagos",
        "dataset_version": "2026.1",
        "reference_id": "nipost-ref-12345",
    }

    # 1. Successful persistence
    success, ev_id, valid_until = record_verification_evidence(
        db=mock_db,
        code="100001",
        live_res=live_res,
        ver_method="validator_autofill_pipeline",
        upstream_version="2026.1",
        is_validator=False,
    )
    assert success is True
    assert valid_until is not None
    assert mock_db.add.called
    assert mock_db.commit.called

    added_obj = mock_db.add.call_args[0][0]
    assert added_obj.postcode == "100001"
    assert added_obj.status == "verified"
    assert added_obj.verification_method == "validator_autofill_pipeline"
    assert len(added_obj.response_hash) == 64
    assert added_obj.is_active is True

    # 2. Database exception triggers rollback and returns False
    failing_db = MagicMock()
    failing_db.commit.side_effect = Exception("DB Disk I/O Error")

    fail_success, fail_id, fail_until = record_verification_evidence(
        db=failing_db,
        code="100001",
        live_res=live_res,
        ver_method="validator_autofill_pipeline",
    )
    assert fail_success is False
    assert fail_id is None
    assert fail_until is None
    assert failing_db.rollback.called
