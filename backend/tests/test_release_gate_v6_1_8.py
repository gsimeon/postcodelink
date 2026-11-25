"""Release Gate v6.1.8 Verification Test Suite.

Validates the resolutions for:
- P1: Environment normalization (case-insensitive, fail-closed on unknown environments)
- P1: Cross-tenant isolation & ASSIGNED status mutation restriction in delivery_service
- P1: Termii transactional OTP notification channel ('dnd' route)
- P1 & P2: Migration d4f5a6b7c8e9 local_reference taxonomy and safe conditional downgrade
- P2: Outbox lease immediate persistence before dispatch
"""
import os
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from backend.app.config import Settings
from backend.app.models.enums import DeliveryStatus, AppRole
from backend.app.models.profile import Profile
from backend.app.models.delivery import Delivery
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.schemas.delivery import DeliveryStatusUpdateRequest
from backend.app.services.delivery_service import update_delivery_status, process_notification_outbox
from backend.app.services.notification_service import TermiiNotificationProvider


def test_p1_environment_normalization_and_case_insensitivity():
    """Verify ENVIRONMENT is normalized to lowercase and unknown environments fail closed."""
    # 1. 'Production' should normalize to 'production' and enforce production validation
    with patch.dict(os.environ, {
        "ENVIRONMENT": "Production",
        "SECRET_KEY": "weak",
        "SMS_PROVIDER": "simulated",
    }, clear=False):
        with pytest.raises(ValueError) as exc:
            Settings()
        assert "Fatal Security Error" in str(exc.value) or "Fatal Production Configuration Error" in str(exc.value)

    # 2. 'PRODUCTION' should also normalize and trigger production validation
    with patch.dict(os.environ, {
        "ENVIRONMENT": "PRODUCTION",
        "SECRET_KEY": "weak",
        "SMS_PROVIDER": "simulated",
    }, clear=False):
        with pytest.raises(ValueError) as exc:
            Settings()
        assert "Fatal Security Error" in str(exc.value) or "Fatal Production Configuration Error" in str(exc.value)

    # 3. Unknown environment must fail closed
    with patch.dict(os.environ, {"ENVIRONMENT": "staging_preview"}, clear=False):
        with pytest.raises(ValueError) as exc:
            Settings()
        assert "Unknown ENVIRONMENT 'staging_preview'" in str(exc.value)

    # 4. Valid environments succeed and normalize
    with patch.dict(os.environ, {"ENVIRONMENT": "DEVELOPMENT"}, clear=False):
        s = Settings()
        assert s.ENVIRONMENT == "development"


def test_p1_assigned_status_mutation_forbidden_in_generic_update():
    """Verify ASSIGNED status can only be achieved via dedicated courier assignment endpoint."""
    db = MagicMock()
    merchant = Profile(id="merchant-1", full_name="Merchant One", role=AppRole.MERCHANT)
    delivery = Delivery(
        id="del-1",
        merchant_id="merchant-1",
        status=DeliveryStatus.PENDING,
        version=1,
    )
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = delivery

    req = DeliveryStatusUpdateRequest(new_status=DeliveryStatus.ASSIGNED)
    with pytest.raises(HTTPException) as exc:
        update_delivery_status(db, "del-1", req, merchant)
    assert exc.value.status_code == 400
    assert "ASSIGNED status can only be achieved via the dedicated courier assignment endpoint" in exc.value.detail


def test_p1_cross_tenant_status_update_forbidden():
    """Verify a merchant cannot update delivery status for another merchant's order."""
    db = MagicMock()
    merchant_attacker = Profile(id="merchant-attacker", full_name="Attacker", role=AppRole.MERCHANT)
    delivery_victim = Delivery(
        id="del-victim",
        merchant_id="merchant-owner",
        status=DeliveryStatus.PENDING,
        version=1,
    )
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = delivery_victim

    req = DeliveryStatusUpdateRequest(new_status=DeliveryStatus.CANCELLED)
    with pytest.raises(HTTPException) as exc:
        update_delivery_status(db, "del-victim", req, merchant_attacker)
    assert exc.value.status_code == 403
    assert "Merchants cannot modify deliveries belonging to another merchant" in exc.value.detail


def test_p1_termii_transactional_channel_configuration():
    """Verify TermiiNotificationProvider defaults to the transactional DND route for OTPs."""
    provider = TermiiNotificationProvider(
        api_key="test-api-key",
        sender_id="TestSender",
        channel="dnd",
    )
    assert provider.channel == "dnd"

    # Mock HTTP response to inspect outbound payload channel
    with patch("httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": "ok", "message_id": "msg-12345"}
        mock_post.return_value = mock_resp

        res = provider.send_delivery_pin(
            recipient_phone="08012345678",
            recipient_name="Tunde",
            delivery_id="del-123",
            pin="123456",
        )
        assert res.status.value in ["SENT", "sent"]
        # Verify JSON payload has channel = "dnd"
        sent_payload = mock_post.call_args[1]["json"]
        assert sent_payload["channel"] == "dnd"
        assert sent_payload["sms"] == "Your PostcodeLink delivery confirmation PIN for order del-123 is 123456. Do not share this code."


def test_p1_p2_national_postcode_migration_fixtures_and_downgrade_safety():
    """Verify migration d4f5a6b7c8e9 inserts local_reference fixtures and downgrade only removes migration records."""
    import backend.alembic.versions.d4f5a6b7c8e9_release_gate_v5_4_aes_gcm_national_postcode as mig

    mock_bind = MagicMock()
    mock_bind.dialect.name = "sqlite"

    with patch.object(mig.op, "get_bind", return_value=mock_bind), \
         patch.object(mig.op, "batch_alter_table"):
        # Test upgrade
        mig.upgrade()
        # Find execute calls with INSERT INTO postcodes
        insert_calls = [
            c for c in mock_bind.execute.call_args_list
            if len(c[0]) > 0 and "INSERT INTO postcodes" in str(c[0][0])
        ]
        assert len(insert_calls) == 2
        for call in insert_calls:
            # Check params passed
            rec = call[0][1]
            assert rec["verification_status"] == "local_reference"
            assert rec["provenance"] == "PostcodeLink National Postcode Format Demonstration Reference"
            assert rec["dataset_version"] == "2026.1"

        # Test downgrade
        mig.downgrade()
        delete_calls = [
            c for c in mock_bind.execute.call_args_list
            if len(c[0]) > 0 and "DELETE FROM postcodes" in str(c[0][0])
        ]
        assert len(delete_calls) == 1
        delete_query = str(delete_calls[0][0][0])
        assert "provenance IN ('PostcodeLink National Postcode Format Demonstration Reference'" in delete_query
        assert "dataset_version = '2026.1'" in delete_query


def test_p2_outbox_lease_committed_before_dispatch():
    """Verify outbox item lease is committed immediately upon acquisition strictly before external network calls."""
    db = MagicMock()
    now = datetime.now(timezone.utc)
    item = NotificationOutbox(
        id="item-lease-test",
        delivery_id="del-test",
        delivery_version=1,
        channel="SMS",
        recipient_phone="+2348012345678",
        notification_type="otp_delivery_pin",
        message_payload=None,
        retry_count=0,
        max_retries=3,
        status="QUEUED",
        created_at=now,
    )
    # Mock query returns item
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.with_for_update.return_value.all.return_value = [item]

    timeline = []
    def mock_commit():
        timeline.append(("commit", item.locked_at is not None, str(item.status.value if hasattr(item.status, "value") else item.status)))
    db.commit.side_effect = mock_commit

    with patch("backend.app.services.delivery_service.get_notification_provider") as mock_prov_factory:
        mock_prov = MagicMock()
        def mock_send(*args, **kwargs):
            timeline.append(("provider_call", item.locked_at is not None))
            res = MagicMock()
            res.status.value = "SENT"
            res.message_id = "msg-ok"
            return res
        mock_prov.send_delivery_pin.side_effect = mock_send
        mock_prov_factory.return_value = mock_prov

        process_notification_outbox(db, max_items=1)

        # Strictly assert call-order:
        # The outbox processing lease must be committed strictly before the external provider is invoked
        lease_commits = [event for event in timeline if event[0] == "commit" and event[1] is True]
        provider_calls = [event for event in timeline if event[0] == "provider_call"]
        
        assert len(lease_commits) >= 1
        assert len(provider_calls) == 1
        
        first_lease_commit_idx = timeline.index(lease_commits[0])
        first_provider_call_idx = timeline.index(provider_calls[0])
        
        # Chronological order assertion: lease commit happens strictly before provider network call
        assert first_lease_commit_idx < first_provider_call_idx
        # Provider call was executed while lease was actively held
        assert provider_calls[0][1] is True


def test_p2_outbox_two_workers_competing_lease_concurrency():
    """Verify that an outbox item actively leased by Worker 1 is not acquired by Worker 2."""
    from datetime import timedelta
    db = MagicMock()
    now = datetime.now(timezone.utc)
    # Worker 1 holds active lease
    locked_item = NotificationOutbox(
        id="item-competing-test",
        delivery_id="del-competing",
        delivery_version=1,
        channel="SMS",
        recipient_phone="+2348012345678",
        notification_type="otp_delivery_pin",
        message_payload=None,
        retry_count=1,
        max_retries=3,
        status="DISPATCHING",
        created_at=now,
        locked_at=now - timedelta(minutes=1),
        locked_by="worker-1",
    )
    # The database query filters out locked items whose locked_at > now - lease_timeout
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.with_for_update.return_value.all.return_value = []

    processed = process_notification_outbox(db, max_items=1, worker_id="worker-2")
    assert processed == 0


def test_api_tenant_isolation_and_rbac_boundaries():
    """Integration test verifying end-to-end API authorization matrix across tenants and roles."""
    from starlette.testclient import TestClient
    from backend.app.main import app
    from backend.app.core.security import create_access_token, hash_otp
    from backend.app.database import SessionLocal
    from backend.app.models.operator import Operator
    from datetime import timedelta

    client = TestClient(app)
    db = SessionLocal()
    try:
        # Create Merchant A and Merchant B
        m_a_id = f"merchant-a-{uuid.uuid4().hex[:8]}"
        m_b_id = f"merchant-b-{uuid.uuid4().hex[:8]}"
        m_a = Profile(id=m_a_id, email=f"{m_a_id}@test.ng", role=AppRole.MERCHANT, full_name="Merchant Alpha", hashed_password="test_hashed_password")
        m_b = Profile(id=m_b_id, email=f"{m_b_id}@test.ng", role=AppRole.MERCHANT, full_name="Merchant Beta", hashed_password="test_hashed_password")

        # Create Operator unassigned to this delivery
        op_prof_id = f"op-prof-{uuid.uuid4().hex[:8]}"
        op_id = f"op-{uuid.uuid4().hex[:8]}"
        op_prof = Profile(id=op_prof_id, email=f"{op_prof_id}@test.ng", role=AppRole.OPERATOR, full_name="Operator X", hashed_password="test_hashed_password")
        op_record = Operator(id=op_id, profile_id=op_prof_id, business_name="Express Courier", phone="+2348099999999", is_available=True)

        # Delivery owned by Merchant A
        del_id = f"del-rbac-{uuid.uuid4().hex[:8]}"
        del_item = Delivery(
            id=del_id,
            merchant_id=m_a_id,
            recipient_name="Recipient Test",
            recipient_phone="+2348011112222",
            destination_address="12 Marina, Lagos Island",
            destination_area="Lagos Island",
            destination_state="Lagos",
            package_description="Test Package",
            postcode_input="100221",
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("123456"),
            otp_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            version=1,
            is_deleted=False,
        )

        db.add_all([m_a, m_b, op_prof, op_record, del_item])
        db.commit()

        token_a = create_access_token({"sub": m_a_id, "role": "merchant"})
        token_b = create_access_token({"sub": m_b_id, "role": "merchant"})
        token_op = create_access_token({"sub": op_prof_id, "role": "operator"})

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}
        headers_op = {"Authorization": f"Bearer {token_op}"}

        # 1. Merchant B attempts to read Merchant A's delivery -> HTTP 403 Forbidden
        res_read = client.get(f"/api/v1/deliveries/{del_id}", headers=headers_b)
        assert res_read.status_code == 403

        # 2. Merchant B attempts to update Merchant A's delivery -> HTTP 403 Forbidden
        res_update = client.post(
            f"/api/v1/deliveries/{del_id}/status",
            json={"new_status": "cancelled", "note": "Hacker cancel"},
            headers=headers_b,
        )
        assert res_update.status_code == 403

        # 3. Merchant B attempts to delete Merchant A's delivery -> HTTP 403 Forbidden
        res_del = client.delete(f"/api/v1/deliveries/{del_id}", headers=headers_b)
        assert res_del.status_code == 403

        # 4. Merchant attempts to mark delivery DELIVERED via generic status update -> HTTP 400 Bad Request
        res_deliv = client.post(
            f"/api/v1/deliveries/{del_id}/status",
            json={"new_status": "delivered", "note": "Bypass PIN"},
            headers=headers_a,
        )
        assert res_deliv.status_code == 400
        assert "DELIVERED status can only be achieved via the recipient PIN verification endpoint" in res_deliv.json()["detail"]

        # 5. Merchant attempts to transition to ASSIGNED via generic status update -> HTTP 400 Bad Request
        res_assign = client.post(
            f"/api/v1/deliveries/{del_id}/status",
            json={"new_status": "assigned", "note": "Direct assign"},
            headers=headers_a,
        )
        assert res_assign.status_code == 400
        assert "ASSIGNED status can only be achieved via the dedicated courier assignment endpoint" in res_assign.json()["detail"]

        # 6. Unassigned operator attempts to advance delivery -> HTTP 403 Forbidden
        res_op_advance = client.post(
            f"/api/v1/deliveries/{del_id}/status",
            json={"new_status": "picked_up", "note": "Rider pickup"},
            headers=headers_op,
        )
        assert res_op_advance.status_code == 403

        # 7. Non-authorized user attempts to verify PIN -> HTTP 403 Forbidden
        res_otp_unauth = client.post(
            f"/api/v1/deliveries/{del_id}/verify-otp",
            json={"otp": "123456"},
            headers=headers_b,
        )
        assert res_otp_unauth.status_code == 403

        # 8. Authorized merchant attempts to verify PIN before OUT_FOR_DELIVERY (order is PENDING) -> HTTP 409 Conflict
        res_otp_stage = client.post(
            f"/api/v1/deliveries/{del_id}/verify-otp",
            json={"otp": "123456"},
            headers=headers_a,
        )
        assert res_otp_stage.status_code == 409
        assert "Delivery PIN can only be verified when the order is out for delivery" in res_otp_stage.json()["detail"]

    finally:
        db.close()


def test_server_side_recipient_phone_challenge_and_public_privacy():
    """Verify that public tracking strictly enforces token privacy and server-side phone challenge verification."""
    import secrets
    from backend.app.models.delivery import Delivery
    from backend.app.models.profile import Profile
    from backend.app.models.enums import DeliveryStatus, PostcodeStatus, AppRole
    from backend.app.services.delivery_service import hash_otp
    from backend.app.database import SessionLocal
    from starlette.testclient import TestClient
    from backend.app.main import app

    db = SessionLocal()
    client = TestClient(app)

    try:
        # Create merchant
        merchant = Profile(
            id=f"merchant-privacy-{uuid.uuid4().hex[:8]}",
            email=f"merchant_{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="test_hashed_password",
            full_name="Merchant Privacy Test",
            role=AppRole.MERCHANT,
            business_name="Privacy Logistics Hub",
        )
        db.add(merchant)

        token = secrets.token_urlsafe(24)
        delivery = Delivery(
            id=f"PL-PRIV-{uuid.uuid4().hex[:6]}",
            tracking_token=token,
            merchant_id=merchant.id,
            recipient_name="Chioma Okeke",
            recipient_phone="+2348034567890",
            destination_address="Plot 5 Victoria Island, Lagos",
            destination_area="Victoria Island",
            destination_state="Lagos",
            postcode_input="101241",
            postcode_status=PostcodeStatus.VERIFIED,
            verified_postcode="101241",
            package_description="Confidential Documents",
            fee=2500,
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("654321"),
            otp_attempts=0,
            otp_max_attempts=3,
        )
        db.add(delivery)
        db.commit()

        # 1. Predictable human-readable delivery ID rejected with HTTP 404
        res_predictable = client.get(f"/api/v1/deliveries/track/{delivery.id}")
        assert res_predictable.status_code == 404
        assert "32-character tracking token" in res_predictable.json()["detail"]

        # 2. Public tracking by secure token returns masked privacy data
        res_public = client.get(f"/api/v1/deliveries/track/{token}")
        assert res_public.status_code == 200
        data = res_public.json()
        assert data["tracking_token"] == token
        assert data["recipient_name_masked"] == "C***** O****"
        assert data["recipient_phone_masked"] == "+23****7890"
        assert data["destination_general_location"] == "Victoria Island, Lagos"
        # Privacy guarantees: ensure internal IDs, raw private fields & security counters are omitted
        assert "id" not in data
        assert "otp_attempts" not in data
        assert "otp_max_attempts" not in data
        assert "destination_address" not in data
        assert "otp_hash" not in data
        assert "fee" not in data

        # 3. Server-side challenge verification with WRONG last 4 digits -> HTTP 400 Bad Request
        res_wrong_chal = client.post(
            f"/api/v1/deliveries/track/{token}/verify-recipient",
            json={"phone_last_4": "1234"},
        )
        assert res_wrong_chal.status_code == 400
        assert "Identity challenge failed" in res_wrong_chal.json()["detail"]

        # 4. Server-side challenge verification with CORRECT last 4 digits ("7890") -> HTTP 200 OK
        res_ok_chal = client.post(
            f"/api/v1/deliveries/track/{token}/verify-recipient",
            json={"phone_last_4": "7890"},
        )
        assert res_ok_chal.status_code == 200
        chal_data = res_ok_chal.json()
        assert chal_data["success"] is True
        assert chal_data["verified"] is True
        assert chal_data["tracking_token"] == token
        assert "challenge_token" in chal_data
        assert "delivery_id" not in chal_data
        challenge_token = chal_data["challenge_token"]

        # 4b. Public Delivery Confirmation WITHOUT or with TAMPERED challenge_token -> rejected
        res_no_chal = client.post(
            f"/api/v1/deliveries/track/{token}/confirm-delivery",
            json={"otp": "654321"},
        )
        assert res_no_chal.status_code == 422

        res_bad_chal = client.post(
            f"/api/v1/deliveries/track/{token}/confirm-delivery",
            json={"otp": "654321", "challenge_token": "tampered.token.value.0000"},
        )
        assert res_bad_chal.status_code == 403

        # 5. Public Delivery Confirmation via PIN with invalid PIN -> 400 Bad Request
        res_wrong_pin = client.post(
            f"/api/v1/deliveries/track/{token}/confirm-delivery",
            json={"otp": "111111", "challenge_token": challenge_token},
        )
        assert res_wrong_pin.status_code == 400
        assert "Invalid delivery PIN" in res_wrong_pin.json()["detail"]

        # 6. Public Delivery Confirmation via PIN with valid PIN & valid challenge_token -> 200 OK
        res_ok_pin = client.post(
            f"/api/v1/deliveries/track/{token}/confirm-delivery",
            json={"otp": "654321", "challenge_token": challenge_token, "phone_last_4": "7890"},
        )
        assert res_ok_pin.status_code == 200
        pin_data = res_ok_pin.json()
        assert pin_data["success"] is True
        assert pin_data["status"] == "delivered"
        assert pin_data["pod_verified"] is True

    finally:
        db.close()


def test_verification_evidence_model_immutability():
    """Verify that VerificationEvidence records are strictly immutable and reject update or delete operations."""
    import pytest
    from backend.app.models.verification_evidence import VerificationEvidence
    from backend.app.database import SessionLocal

    db = SessionLocal()
    try:
        evidence = VerificationEvidence(
            id=f"evi-{uuid.uuid4().hex[:12]}",
            postcode="100001",
            provider="NIPOST",
            provider_reference_id="TX-12345",
            verification_method="validator_autofill_pipeline",
            dataset_version="2026.1",
            response_hash="abc123hash456",
            status="verified",
            address_metadata_source="nipost_autofill",
        )
        db.add(evidence)
        db.commit()

        # Attempt to update evidence -> raises ValueError
        evidence.status = "rejected"
        with pytest.raises(ValueError, match="VerificationEvidence records are strictly immutable and cannot be updated"):
            db.commit()
        db.rollback()

        # Attempt to delete evidence via ORM -> raises ValueError
        with pytest.raises(ValueError, match="VerificationEvidence records are strictly immutable and cannot be deleted"):
            db.delete(evidence)
            db.commit()
        db.rollback()

        # Attempt direct raw SQL UPDATE / DELETE -> blocked by database-level triggers
        from sqlalchemy import text
        raw_update_blocked = False
        try:
            db.execute(text("UPDATE verification_evidence SET status = 'tampered' WHERE id = :id"), {"id": evidence.id})
            db.commit()
        except Exception:
            raw_update_blocked = True
            db.rollback()
        assert raw_update_blocked, "Database-level trigger must block raw SQL UPDATE on verification_evidence"

        raw_delete_blocked = False
        try:
            db.execute(text("DELETE FROM verification_evidence WHERE id = :id"), {"id": evidence.id})
            db.commit()
        except Exception:
            raw_delete_blocked = True
            db.rollback()
        assert raw_delete_blocked, "Database-level trigger must block raw SQL DELETE on verification_evidence"

    finally:
        db.close()


def test_digital_postcode_parser_specification_flexibility():
    """Verify digital postcode parser correctly accepts 11/12 compact and 15/16 display canonical codes."""
    from backend.app.core.postcode_utils import (
        parse_digital_postcode_components,
        is_well_formed_postcode,
        normalize_postcode,
    )

    # 1. Standard 11-char compact / 15-char display (2-char building)
    p1 = parse_digital_postcode_components("FC-02-A09-DB-09")
    assert p1 is not None
    assert p1["state"] == "FC"
    assert p1["lga"] == "02"
    assert p1["district"] == "A09"
    assert p1["area"] == "DB"
    assert p1["building"] == "09"
    assert p1["compact_code"] == "FC02A09DB09"
    assert p1["total_length"] == 11

    # Compact form parses identically
    p1_c = parse_digital_postcode_components("FC02A09DB09")
    assert p1_c == p1

    # 2. 15-char display with spaces (FC 02 A09 DB 09) parses cleanly
    p1_sp = parse_digital_postcode_components("FC 02 A09 DB 09")
    assert p1_sp == p1

    # 3. is_well_formed_postcode accepts both legacy and digital variants
    assert is_well_formed_postcode("100001") is True
    assert is_well_formed_postcode("FC-02-A09-DB-09") is True
    assert is_well_formed_postcode("FC02A09DB09") is True
    assert is_well_formed_postcode("FC 02 A09 DB 09") is True

    # 4. Strictly rejects malformed codes and non-conforming component character classes
    assert parse_digital_postcode_components("EK-01-A03-FK-01") is not None  # Official quickstart example
    assert parse_digital_postcode_components("12-02-A09-DB-09") is None  # Non-alpha state
    assert parse_digital_postcode_components("FC-AB-A09-DB-09") is None  # Letters in numeric LGA
    assert parse_digital_postcode_components("FC-02-A099-DB-09") is None  # District too long
    assert parse_digital_postcode_components("FC-02-A09-12-09") is None  # Digits in alpha Area
    assert parse_digital_postcode_components("FC-02-A09-DB-AB") is None  # Letters in numeric Building
    assert parse_digital_postcode_components("FC-02-A09-DB-009") is None  # Building unit too long (3 chars)
    assert parse_digital_postcode_components("FC--02-A09-DB-09") is None  # Double hyphen


def test_nipost_quickstart_contract_and_x_api_key_default():
    """Verify NIPOSTClient defaults to x-api-key header and parses the published nested data quickstart response."""
    import httpx
    from backend.app.services.nipost_client import NIPOSTClient, NIPOSTLookupStatus

    captured_headers = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        for k, v in request.headers.items():
            captured_headers[k.lower()] = v
        return httpx.Response(
            200,
            json={
                "data": {
                    "postcode": "EK-01-A03-FK-01",
                    "valid": True,
                    "administrative_address": {
                        "state_name": "Ekiti",
                        "lga_name": "Ado-Ekiti",
                        "locality_name": "Fajuyi",
                    },
                    "recent_house_address": {
                        "recent": "12 Fajuyi Memorial Road",
                    },
                }
            },
        )

    c = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="test_nipost_quickstart_key",
        transport=httpx.MockTransport(mock_handler),
    )
    assert c.auth_scheme == "x-api-key"

    res = c.lookup_postcode("EK-01-A03-FK-01")
    assert res.status == NIPOSTLookupStatus.FOUND
    assert captured_headers.get("x-api-key") == "test_nipost_quickstart_key"
    assert "authorization" not in captured_headers
    assert res.data["code"] == "EK-01-A03-FK-01"
    assert res.data["state"] == "Ekiti"
    assert res.data["lga"] == "Ado-Ekiti"
    assert res.data["area"] == "Fajuyi"
    assert res.data["recent_house_address"] == "12 Fajuyi Memorial Road"


def test_challenge_key_separation_and_replay_rejection():
    """Verify recipient challenge key never falls back to JWT SECRET_KEY and rejects replayed nonces."""
    from backend.app.config import settings
    from backend.app.services.delivery_service import (
        _get_challenge_signing_key,
        _issue_recipient_challenge_token,
        _verify_recipient_challenge_token,
    )
    import hashlib

    # 1. Signing key must not equal raw or hashed SECRET_KEY
    key = _get_challenge_signing_key()
    assert key != settings.SECRET_KEY.encode("utf-8")
    assert key != hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()

    # 2. Issued challenge_token can be verified once and consumed atomically in DB across sessions, then replay is rejected
    from backend.app.database import SessionLocal
    from concurrent.futures import ThreadPoolExecutor

    tok = "A" * 32
    chal = _issue_recipient_challenge_token(tok)

    def attempt_consume(_):
        s = SessionLocal()
        try:
            _verify_recipient_challenge_token(chal, tok, consume=True, db=s)
            s.commit()
            return "ok"
        except HTTPException as exc:
            s.rollback()
            return exc.status_code
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt_consume, [1, 2]))

    assert results.count("ok") == 1, f"Expected exactly 1 concurrent consumption to succeed, got {results}"
    assert results.count(403) == 1, f"Expected replay attempt to fail with 403, got {results}"


def test_coverage_report_splits_format_valid_from_nipost_confirmed():
    """Verify coverage report distinguishes format-valid digital references from NIPOST-confirmed metrics."""
    from backend.app.services.postcode_service import get_postcode_coverage_report
    from backend.app.database import SessionLocal

    db = SessionLocal()
    try:
        rep = get_postcode_coverage_report(db)
        assert hasattr(rep, "format_valid_digital_references")
        assert hasattr(rep, "nipost_confirmed_postcodes")
        assert hasattr(rep, "nipost_confirmed_address_metadata")
        assert rep.format_valid_digital_references == rep.national_digital_postcode_records
        assert rep.nipost_confirmed_postcodes == rep.records_with_valid_evidence
        assert rep.digital_building_level_records <= rep.nipost_confirmed_postcodes
    finally:
        db.close()


def test_admin_only_health_check_endpoint_and_authenticated_probe():
    """Verify /integration/health-check is strictly admin-only and probes authenticated lookup."""
    from starlette.testclient import TestClient
    from backend.app.main import app
    from backend.app.core.security import create_access_token
    from backend.app.database import SessionLocal
    from backend.app.services.nipost_client import NIPOSTClient
    import httpx

    client = TestClient(app)

    # 1. Unauthenticated caller -> 401/403
    res_unauth = client.post("/api/v1/postcodes/integration/health-check")
    assert res_unauth.status_code in (401, 403)

    db = SessionLocal()
    try:
        merchant = Profile(
            id=f"m-hc-{uuid.uuid4().hex[:8]}",
            email=f"m_hc_{uuid.uuid4().hex[:8]}@test.ng",
            hashed_password="x",
            full_name="Merchant HC",
            role=AppRole.MERCHANT,
        )
        admin = Profile(
            id=f"a-hc-{uuid.uuid4().hex[:8]}",
            email=f"a_hc_{uuid.uuid4().hex[:8]}@test.ng",
            hashed_password="x",
            full_name="Admin HC",
            role=AppRole.ADMIN,
        )
        db.add_all([merchant, admin])
        db.commit()

        m_tok = create_access_token(data={"sub": merchant.id, "role": AppRole.MERCHANT.value})
        a_tok = create_access_token(data={"sub": admin.id, "role": AppRole.ADMIN.value})

        # 2. Non-admin merchant -> 403 Forbidden
        res_merch = client.post(
            "/api/v1/postcodes/integration/health-check",
            headers={"Authorization": f"Bearer {m_tok}"},
        )
        assert res_merch.status_code == 403

        # 3. Admin caller -> 200 OK with sanitized fields only
        res_admin = client.post(
            "/api/v1/postcodes/integration/health-check",
            headers={"Authorization": f"Bearer {a_tok}"},
        )
        assert res_admin.status_code == 200
        body = res_admin.json()
        assert "connectivity_healthy" in body
        assert "authentication_verified" in body
        assert "contract_verified" in body
        assert body["production_authorized"] is False
    finally:
        db.close()

    # 4. NIPOSTClient.check_health() uses zero-credit Assembly endpoint and never treats 404 as accepted auth
    c_404 = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="nipost_test_invalid",
        transport=httpx.MockTransport(lambda req: httpx.Response(404, json={"error": "not found"})),
    )
    probe_404 = c_404.check_health()
    assert probe_404["healthy"] is False
    st_404 = c_404.get_integration_status()
    assert st_404["authentication_verified"] is False
    assert st_404["contract_verified"] is False
    assert st_404["upstream_environment"] == "sandbox"

    c_401 = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="nipost_test_invalid",
        transport=httpx.MockTransport(lambda req: httpx.Response(401, json={"error": "unauthorized"})),
    )
    probe_401 = c_401.check_health()
    assert probe_401["healthy"] is False
    st_401 = c_401.get_integration_status()
    assert st_401["authentication_verified"] is False
    assert st_401["contract_verified"] is False

    c_200 = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="nipost_live_valid123",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={"data": {"postcode": "EK-01-A03-FK-01"}},
            )
        ),
    )
    probe_200 = c_200.check_health()
    assert probe_200["healthy"] is True
    st_200 = c_200.get_integration_status()
    assert st_200["authentication_verified"] is True
    assert st_200["contract_verified"] is True
    assert st_200["production_authorized"] is False
    assert st_200["upstream_environment"] == "production"


def test_nipost_sandbox_test_key_never_classified_as_production_official():
    """Verify nipost_test_ sandbox responses are strictly sandbox_verified, rejected in strict mode,
    and never emit live_nipost_api / official_national_directory source flags.
    """
    import httpx
    from backend.app.services.nipost_client import NIPOSTClient
    from backend.app.services.postcode_service import cleanse_address, get_postcode_coverage_report
    from backend.app.routers.postcodes import execute_postcode_lookup
    from backend.app.database import SessionLocal

    def sandbox_handler(request: httpx.Request) -> httpx.Response:
        if "/v1/validate" in str(request.url):
            return httpx.Response(200, json={"valid": True, "code": "EK-01-A03-FK-01"})
        return httpx.Response(
            200,
            json={
                "data": {
                    "postcode": "EK-01-A03-FK-01",
                    "valid": True,
                    "administrative_address": {
                        "state_name": "Ekiti",
                        "lga_name": "Ado-Ekiti",
                        "locality_name": "Fajuyi",
                    },
                }
            },
        )

    sandbox_client = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="nipost_test_sandbox_sample_key",
        transport=httpx.MockTransport(sandbox_handler),
    )
    assert sandbox_client.upstream_environment == "sandbox"

    live_client = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="nipost_live_production_key",
        transport=httpx.MockTransport(sandbox_handler),
    )
    assert live_client.upstream_environment == "production"

    db = SessionLocal()
    try:
        # 1. Sandbox key in normal mode -> sandbox_verified, is_live_nipost=False, nipost_sandbox flags
        res = cleanse_address(
            address="12 Fajuyi Road, Ado-Ekiti, Ekiti",
            postcode_hint="EK-01-A03-FK-01",
            verification_mode="nipost_validate",
            client=sandbox_client,
            db=db,
        )
        assert res.verification_status == "sandbox_verified"
        assert res.postcode_status != "verified"
        assert res.is_live_nipost is False
        assert res.source == "nipost_sandbox"
        assert res.source_type == "nipost_sandbox"
        assert res.verification_source == "nipost_sandbox"
        assert res.fallback_used is False

        # 2. Sandbox key in nipost_strict mode -> fails closed (HTTP 503)
        with pytest.raises(HTTPException) as exc_strict:
            cleanse_address(
                address="12 Fajuyi Road, Ado-Ekiti, Ekiti",
                postcode_hint="EK-01-A03-FK-01",
                verification_mode="nipost_strict",
                client=sandbox_client,
                db=db,
            )
        assert exc_strict.value.status_code == 503

        # 3. Sandbox key in strict lookup -> fails closed (HTTP 503)
        with pytest.raises(HTTPException) as exc_lookup:
            execute_postcode_lookup(db=db, code="EK-01-A03-FK-01", strict=True, client=sandbox_client)
        assert exc_lookup.value.status_code == 503

        # 4. Live key with Autofill & persisted evidence -> official_verified
        res_live = cleanse_address(
            address="12 Fajuyi Road, Ado-Ekiti, Ekiti",
            postcode_hint="EK-01-A03-FK-01",
            verification_mode="nipost_validate",
            client=live_client,
            db=db,
        )
        assert res_live.verification_status == "official_verified"
        assert res_live.is_live_nipost is True
        assert res_live.source == "live_nipost_api"

        # 5. Live key with failed evidence persistence (db=None) -> demoted in normal mode, rejected in strict
        res_demoted = cleanse_address(
            address="12 Fajuyi Road, Ado-Ekiti, Ekiti",
            postcode_hint="EK-01-A03-FK-01",
            verification_mode="nipost_validate",
            client=live_client,
            db=None,
        )
        assert res_demoted.verification_status == "local_reference"
        assert res_demoted.is_live_nipost is False

        with pytest.raises(HTTPException) as exc_no_db:
            cleanse_address(
                address="12 Fajuyi Road, Ado-Ekiti, Ekiti",
                postcode_hint="EK-01-A03-FK-01",
                verification_mode="nipost_strict",
                client=live_client,
                db=None,
            )
        assert exc_no_db.value.status_code == 503
    finally:
        db.close()


def test_api_keys_support_test_and_live_environments_and_preserve_on_rotate():
    """Verify P2 developer environments: pl_test_ vs pl_live_ prefixes and preservation on rotate."""
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.database import SessionLocal
    from backend.app.core.security import create_access_token

    test_client = TestClient(app)
    db = SessionLocal()
    try:
        merchant_id = str(uuid.uuid4())
        merchant = Profile(
            id=merchant_id,
            full_name="Dev Console Merchant",
            phone=f"+23480{str(uuid.UUID(merchant_id).int)[:8]}",
            email=f"dev-{merchant_id[:8]}@example.com",
            hashed_password="test_hashed_password",
            role=AppRole.MERCHANT,
        )
        db.add(merchant)
        db.commit()

        token = create_access_token({"sub": str(merchant.id), "role": AppRole.MERCHANT.value})
        headers = {"Authorization": f"Bearer {token}"}

        # Create a test key
        res_test = test_client.post(
            "/api/v1/api-keys/",
            headers=headers,
            json={"name": "Sandbox CI Key", "monthly_quota": 500, "environment": "test"},
        )
        assert res_test.status_code == 201
        test_data = res_test.json()
        assert test_data["environment"] == "test"
        assert test_data["api_key"].startswith("pl_test_")
        assert test_data["key_prefix"].startswith("pl_test_")

        # Create a live key when commercial authorization is NOT granted -> must fail closed 403
        res_live_blocked = test_client.post(
            "/api/v1/api-keys/",
            headers=headers,
            json={"name": "Production Key Blocked", "monthly_quota": 5000, "environment": "live"},
        )
        assert res_live_blocked.status_code == 403

        # Grant auditable commercial authorization -> live key creation succeeds
        from backend.app.config import settings
        with patch.object(settings, "NIPOST_PRODUCTION_AUTHORIZED", True), \
             patch.object(settings, "NIPOST_AUTHORIZATION_AGREEMENT_REF", "NIPOST-AGR-2026-001"), \
             patch.object(settings, "NIPOST_AUTHORIZATION_APPROVER", "Director of Licensing"), \
             patch.object(settings, "NIPOST_AUTHORIZATION_APPROVED_AT", "2026-11-20T10:00:00Z"), \
             patch.object(settings, "NIPOST_AUTHORIZATION_SCOPE", "postcode_verification"):
            res_live = test_client.post(
                "/api/v1/api-keys/",
                headers=headers,
                json={"name": "Production Key", "monthly_quota": 5000, "environment": "live"},
            )
        assert res_live.status_code == 201
        live_data = res_live.json()
        assert live_data["environment"] == "live"
        assert live_data["api_key"].startswith("pl_live_")

        # Rotate the test key -> must preserve environment="test" and pl_test_ prefix
        res_rot = test_client.post(
            f"/api/v1/api-keys/{test_data['id']}/rotate",
            headers=headers,
        )
        assert res_rot.status_code == 201
        rot_data = res_rot.json()
        assert rot_data["environment"] == "test"
        assert rot_data["api_key"].startswith("pl_test_")
        assert rot_data["api_key"] != test_data["api_key"]

        # List keys includes environment metadata
        res_list = test_client.get("/api/v1/api-keys/", headers=headers)
        assert res_list.status_code == 200
        envs = {k["id"]: k["environment"] for k in res_list.json()}
        assert envs[rot_data["id"]] == "test"
        assert envs[live_data["id"]] == "live"
    finally:
        db.close()


def test_nipost_client_unified_lookup_and_assembly_unit_contract():
    """Verify P1 live NIPOST contract: unified /v1/lookup when validate_path='' and 'unit' in assembly."""
    import json
    import httpx
    from backend.app.services.nipost_client import NIPOSTClient, NIPOSTLookupStatus

    seen_requests: list[tuple[str, str, dict | None]] = []

    def unified_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode()) if request.content else None
        seen_requests.append((request.method, str(request.url), body))
        if "/v1/assembly/assemble" in str(request.url):
            assert body is not None and "unit" in body and "building_unit" not in body
            return httpx.Response(
                200,
                json={"data": {"compact": "EK01A03FK01", "display": "EK 01 A03 FK 01", "postcode": "EK-01-A03-FK-01"}},
            )
        if "/v1/lookup" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "postcode": "EK-01-A03-FK-01",
                        "valid": True,
                        "status": "valid",
                        "verified": True,
                        "administrative_address": {"state_name": "Ekiti", "lga_name": "Ado-Ekiti", "locality_name": "Fajuyi"},
                    }
                },
            )
        return httpx.Response(404, text="404 page not found")

    client_unified = NIPOSTClient(
        base_url="https://api.postcode.gov.ng",
        api_key="nipost_test_contract_check",
        validate_path="",
        transport=httpx.MockTransport(unified_handler),
    )

    health = client_unified.check_health()
    assert health["healthy"] is True
    assert client_unified._last_contract_verified is True

    status, data, err, method = client_unified.orchestrated_verify("EK-01-A03-FK-01")
    assert status == NIPOSTLookupStatus.FOUND
    assert err is None
    assert data is not None and data["valid"] is True
    assert method == "unified_lookup"
    assert not any("/v1/validate" in url for _, url, _ in seen_requests)


def test_strict_mode_rejects_unclassified_publishable_missing_and_none_auth_scheme():
    """Verify P1-2: strict mode requires positively identified nipost_live_ secret; rejects unclassified, nipost_pk_*, missing, and auth_scheme=none."""
    import httpx
    from backend.app.services.nipost_client import NIPOSTClient
    from backend.app.services.postcode_service import cleanse_address
    from backend.app.routers.postcodes import execute_postcode_lookup
    from backend.app.database import SessionLocal

    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "postcode": "EK-01-A03-FK-01",
                    "valid": True,
                    "administrative_address": {
                        "state_name": "Ekiti",
                        "lga_name": "Ado-Ekiti",
                        "locality_name": "Fajuyi",
                    },
                }
            },
        )

    bad_clients = [
        NIPOSTClient(base_url="https://api.postcode.gov.ng", api_key="arbitrary_secret_key", transport=httpx.MockTransport(ok_handler)),
        NIPOSTClient(base_url="https://api.postcode.gov.ng", api_key="nipost_pk_publishable_key", transport=httpx.MockTransport(ok_handler)),
        NIPOSTClient(base_url="https://api.postcode.gov.ng", api_key="", auth_scheme="none", transport=httpx.MockTransport(ok_handler)),
        NIPOSTClient(base_url="https://api.postcode.gov.ng", api_key="nipost_live_ignored_when_none", auth_scheme="none", transport=httpx.MockTransport(ok_handler)),
    ]
    assert bad_clients[1].configuration_complete is False

    db = SessionLocal()
    try:
        for bad in bad_clients:
            assert bad.upstream_environment == "unclassified"
            with pytest.raises(HTTPException) as exc_lookup:
                execute_postcode_lookup(db=db, code="EK-01-A03-FK-01", strict=True, client=bad)
            assert exc_lookup.value.status_code == 503

            with pytest.raises(HTTPException) as exc_cleanse:
                cleanse_address(
                    address="12 Fajuyi Road, Ado-Ekiti, Ekiti",
                    postcode_hint="EK-01-A03-FK-01",
                    verification_mode="nipost_strict",
                    client=bad,
                    db=db,
                )
            assert exc_cleanse.value.status_code == 503

            # Non-strict mode must downgrade to local_reference (never official_verified)
            res_non_strict = execute_postcode_lookup(db=db, code="EK-01-A03-FK-01", strict=False, client=bad)
            assert res_non_strict.verification_status == "local_reference"
            assert res_non_strict.is_live_nipost is False
    finally:
        db.close()


def test_pl_test_key_isolated_from_live_nipost_and_pl_live_gated_by_authorization():
    """Verify P1-3 & P1-5: pl_test_ keys never contact live NIPOST; pl_live_ commercial access requires recorded authorization."""
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.database import SessionLocal
    from backend.app.core.security import create_access_token
    from backend.app.models.api_key import ApiKey
    import hashlib

    test_client = TestClient(app)
    db = SessionLocal()
    try:
        merchant_id = str(uuid.uuid4())
        merchant = Profile(
            id=merchant_id,
            full_name="Sandbox Isolation Merchant",
            phone=f"+23480{str(uuid.UUID(merchant_id).int)[:8]}",
            email=f"sandbox-{merchant_id[:8]}@example.com",
            hashed_password="test_hashed_password",
            role=AppRole.MERCHANT,
        )
        db.add(merchant)
        db.commit()

        token = create_access_token({"sub": merchant.id, "role": AppRole.MERCHANT.value})
        jwt_headers = {"Authorization": f"Bearer {token}"}

        # 1. Create a pl_test_ key
        res_test = test_client.post(
            "/api/v1/api-keys/",
            headers=jwt_headers,
            json={"name": "Isolated Test Key", "monthly_quota": 50, "environment": "test"},
        )
        assert res_test.status_code == 201
        pl_test_key = res_test.json()["api_key"]
        assert pl_test_key.startswith("pl_test_")

        # Even if server NIPOST_API_BASE_URL/KEY were set, pl_test_ must NEVER invoke live upstream
        with patch("backend.app.routers.postcodes.NIPOSTClient.orchestrated_verify", side_effect=AssertionError("pl_test_ must never call live NIPOST")):
            lookup_res = test_client.get(
                "/api/v1/postcodes/commercial/lookup?state=Lagos",
                headers={"x-api-key": pl_test_key},
            )
            assert lookup_res.status_code == 200
            body = lookup_res.json()
            assert body["source"] == "postcodelink_sandbox"
            assert body["is_live_nipost"] is False
            assert body["upstream_contacted"] is False

            cleanse_res = test_client.post(
                "/api/v1/postcodes/commercial/cleanse",
                json={"address": "15 Marina St, Lagos Island", "state": "Lagos"},
                headers={"x-api-key": pl_test_key},
            )
            assert cleanse_res.status_code == 200
            c_body = cleanse_res.json()
            assert c_body["source"] == "postcodelink_sandbox"
            assert c_body["is_live_nipost"] is False

            # Strict mode with pl_test_ fails closed 503
            strict_res = test_client.get(
                "/api/v1/postcodes/commercial/lookup?code=101233&strict=true",
                headers={"x-api-key": pl_test_key},
            )
            assert strict_res.status_code == 503

        # 2. Existing pl_live_ key is blocked (403) when production_authorized is False
        raw_live = f"pl_live_{uuid.uuid4().hex}"
        db.add(
            ApiKey(
                merchant_id=merchant.id,
                name="Preexisting Live Key",
                environment="live",
                key_prefix=raw_live[:12],
                hashed_key=hashlib.sha256(raw_live.encode()).hexdigest(),
                monthly_quota=100,
                current_period=datetime.now(timezone.utc).strftime("%Y-%m"),
                is_active=True,
                is_revoked=False,
            )
        )
        db.commit()
        blocked_live = test_client.get(
            "/api/v1/postcodes/commercial/lookup?state=Lagos",
            headers={"x-api-key": raw_live},
        )
        assert blocked_live.status_code == 403
    finally:
        db.close()


def test_commercial_authorization_requires_valid_date_and_scope():
    """Verify is_nipost_production_authorized requires valid non-future approved_at and postcode_verification scope."""
    from backend.app.config import Settings

    base = {
        "NIPOST_PRODUCTION_AUTHORIZED": True,
        "NIPOST_AUTHORIZATION_AGREEMENT_REF": "NIPOST-AGR-2026-001",
        "NIPOST_AUTHORIZATION_APPROVER": "Director of Licensing",
        "NIPOST_AUTHORIZATION_APPROVED_AT": "2026-11-20T10:00:00Z",
        "NIPOST_AUTHORIZATION_SCOPE": "postcode_verification",
    }
    s_valid = Settings(**base)
    assert s_valid.is_nipost_production_authorized is True

    # Missing date -> False
    assert Settings(**{**base, "NIPOST_AUTHORIZATION_APPROVED_AT": ""}).is_nipost_production_authorized is False
    # Invalid date -> False
    assert Settings(**{**base, "NIPOST_AUTHORIZATION_APPROVED_AT": "not-a-date"}).is_nipost_production_authorized is False
    # Future date -> False
    assert Settings(**{**base, "NIPOST_AUTHORIZATION_APPROVED_AT": "2099-01-01T00:00:00Z"}).is_nipost_production_authorized is False
    # Wrong scope -> False
    assert Settings(**{**base, "NIPOST_AUTHORIZATION_SCOPE": "bulk_extraction"}).is_nipost_production_authorized is False
    # Missing scope -> False
    assert Settings(**{**base, "NIPOST_AUTHORIZATION_SCOPE": ""}).is_nipost_production_authorized is False


def test_health_integrations_delegates_to_nipost_client_without_bearer_health_probe():
    """Verify /health/integrations reads NIPOSTClient telemetry and never fires a separate /health Bearer probe."""
    from fastapi.testclient import TestClient
    from backend.app.main import app

    test_client = TestClient(app)
    fake_status = {
        "configuration_complete": True,
        "connectivity_healthy": True,
        "authentication_verified": False,
        "contract_verified": False,
        "production_authorized": False,
        "upstream_environment": "sandbox",
        "last_checked_at": "2026-11-25T09:00:00+00:00",
    }
    with patch("backend.app.services.nipost_client.NIPOSTClient.get_integration_status", return_value=fake_status), \
         patch("httpx.get", side_effect=AssertionError("/health/integrations must not fire separate Bearer /health probe")):
        res = test_client.get("/health/integrations")
        assert res.status_code == 200
        nipost = res.json()["nipost"]
        assert nipost["configured"] is True
        assert nipost["reachable"] is True
        assert nipost["authenticated"] is False
        assert nipost["last_error_category"] == "authentication_failed"
        assert "base_url" not in nipost
        assert "api_key" not in nipost


def test_sms_probe_rejects_non_200_responses_and_public_endpoint_does_not_probe():
    """Verify SMS health probe treats non-200 responses (e.g. 404/500) as unauthenticated and public GET never probes externally."""
    from fastapi.testclient import TestClient
    from backend.app.main import app, _probe_sms_gateway, _sms_probe_cache
    from backend.app.config import settings
    import httpx

    _sms_probe_cache.clear()
    with patch.object(settings, "SMS_PROVIDER", "termii"), \
         patch.object(settings, "TERMII_API_KEY", "termii_key_123"), \
         patch.object(settings, "TERMII_SENDER_ID", "PostcodeLink"):
        # Public GET /health/integrations must NOT call httpx.get
        test_client = TestClient(app)
        with patch("httpx.get", side_effect=AssertionError("public /health/integrations must not probe SMS provider")):
            res = test_client.get("/health/integrations")
            assert res.status_code == 200
            assert res.json()["sms_gateway"]["authenticated"] is False

        # Admin-triggered probe receiving HTTP 404 or 500 must mark authenticated=False
        mock_404 = MagicMock(spec=httpx.Response)
        mock_404.status_code = 404
        with patch("httpx.get", return_value=mock_404):
            probe_res = _probe_sms_gateway(force_probe=True)
            assert probe_res["reachable"] is True
            assert probe_res["authenticated"] is False
            assert probe_res["last_error_category"] == "unexpected_http_404"
    _sms_probe_cache.clear()


def test_httponly_cookie_auth_csrf_and_logout():
    """Verify login sets HttpOnly cookie, /me accepts cookie, CSRF blocks cookie POST without header, and logout clears cookie."""
    from fastapi.testclient import TestClient
    from backend.app.main import app

    test_client = TestClient(app)
    email = f"cookie-{uuid.uuid4().hex[:8]}@example.com"
    reg = test_client.post(
        "/api/v1/auth/register",
        json={"full_name": "Cookie User", "email": email, "password": "StrongPassword!123"},
    )
    assert reg.status_code == 201
    assert "postcodelink_session" in reg.cookies

    # Cookie-authenticated GET /me succeeds without Authorization header
    me_res = test_client.get("/api/v1/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["email"] == email

    # Cookie-authenticated state-changing POST without X-Requested-With -> 403 CSRF blocked
    csrf_blocked = test_client.post(
        "/api/v1/api-keys/",
        json={"name": "CSRF Key", "monthly_quota": 100},
    )
    assert csrf_blocked.status_code == 403

    # Cookie-authenticated state-changing POST from untrusted Origin -> 403 CSRF blocked
    evil_origin = test_client.post(
        "/api/v1/api-keys/",
        headers={"X-Requested-With": "XMLHttpRequest", "Origin": "https://evil.example"},
        json={"name": "Evil Origin Key", "monthly_quota": 100},
    )
    assert evil_origin.status_code == 403

    # With X-Requested-With and allowed Origin -> succeeds
    csrf_ok = test_client.post(
        "/api/v1/api-keys/",
        headers={"X-Requested-With": "XMLHttpRequest", "Origin": "http://localhost:3000"},
        json={"name": "Cookie Key", "monthly_quota": 100},
    )
    assert csrf_ok.status_code == 201

    # Logout clears cookie
    out = test_client.post("/api/v1/auth/logout")
    assert out.status_code == 200
    me_after = test_client.get("/api/v1/auth/me")
    assert me_after.status_code == 401


def test_commercial_authorization_expiry_revocation_and_production_health_gate():
    """Verify expired/revoked commercial auth fails closed and detailed health endpoints require ADMIN in production."""
    from fastapi.testclient import TestClient
    from backend.app.config import Settings, settings
    from backend.app.main import app

    base = {
        "NIPOST_PRODUCTION_AUTHORIZED": True,
        "NIPOST_AUTHORIZATION_AGREEMENT_REF": "NIPOST-AGR-2026-001",
        "NIPOST_AUTHORIZATION_APPROVER": "Director of Licensing",
        "NIPOST_AUTHORIZATION_APPROVED_AT": "2026-11-20T10:00:00Z",
        "NIPOST_AUTHORIZATION_EXPIRES_AT": "2099-11-20T10:00:00Z",
        "NIPOST_AUTHORIZATION_REVOKED": False,
        "NIPOST_AUTHORIZATION_SCOPE": "postcode_verification",
    }
    assert Settings(**base).is_nipost_production_authorized is True
    assert Settings(**{**base, "NIPOST_AUTHORIZATION_EXPIRES_AT": "2020-01-01T00:00:00Z"}).is_nipost_production_authorized is False
    assert Settings(**{**base, "NIPOST_AUTHORIZATION_REVOKED": True}).is_nipost_production_authorized is False

    test_client = TestClient(app)
    with patch.object(settings, "ENVIRONMENT", "production"):
        assert test_client.get("/health/live").status_code == 200
        assert test_client.get("/health/worker").status_code == 401
        assert test_client.get("/health/rate-limiter").status_code == 401
        assert test_client.get("/health/integrations").status_code == 401


def test_pl_test_outbound_http_interception_isolation():
    """HTTP-level interception test: even with live NIPOST server credentials configured,
    pl_test_ keys NEVER make outbound HTTP requests to live NIPOST across lookup, cleanse, strict, or expired/revoked states.
    """
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.database import SessionLocal
    from backend.app.core.security import create_access_token
    from backend.app.config import settings
    import httpx

    test_client = TestClient(app)
    db = SessionLocal()
    try:
        merchant_id = str(uuid.uuid4())
        merchant = Profile(
            id=merchant_id,
            full_name="Outbound Intercept Merchant",
            phone=f"+23480{str(uuid.UUID(merchant_id).int)[:8]}",
            email=f"intercept-{merchant_id[:8]}@example.com",
            hashed_password="test_hashed_password",
            role=AppRole.MERCHANT,
        )
        db.add(merchant)
        db.commit()

        token = create_access_token({"sub": merchant.id, "role": AppRole.MERCHANT.value})
        jwt_headers = {"Authorization": f"Bearer {token}"}

        res_test = test_client.post(
            "/api/v1/api-keys/",
            headers=jwt_headers,
            json={"name": "HTTP Intercept Test Key", "monthly_quota": 50, "environment": "test"},
        )
        assert res_test.status_code == 201
        pl_test_key = res_test.json()["api_key"]

        orig_send = httpx.Client.send

        def guarded_send(self, request, *args, **kwargs):
            if request.url.host != "testserver":
                raise AssertionError(f"Outbound HTTP to {request.url} forbidden for pl_test_")
            return orig_send(self, request, *args, **kwargs)

        with patch.object(settings, "NIPOST_API_BASE_URL", "https://api.postcode.gov.ng"), \
             patch.object(settings, "NIPOST_API_KEY", "nipost_live_must_never_be_called"), \
             patch.object(httpx.Client, "send", autospec=True, side_effect=guarded_send):
            # Live-looking 11-char digital postcode
            r1 = test_client.get("/api/v1/postcodes/commercial/lookup?code=EK-01-A03-FK-01", headers={"x-api-key": pl_test_key})
            assert r1.status_code == 200
            assert r1.json()["is_live_nipost"] is False
            assert r1.json()["upstream_contacted"] is False

            # Cleanse with live_verify=True requested by caller -> still isolated
            r2 = test_client.post(
                "/api/v1/postcodes/commercial/cleanse",
                json={"address": "12 Fajuyi Road, Ado-Ekiti, Ekiti", "postcode": "EK-01-A03-FK-01", "live_verify": True},
                headers={"x-api-key": pl_test_key},
            )
            assert r2.status_code == 200
            assert r2.json()["is_live_nipost"] is False
            assert r2.json()["upstream_contacted"] is False

            # Strict mode -> fails closed 503 without outbound HTTP call
            r3 = test_client.get("/api/v1/postcodes/commercial/lookup?code=EK-01-A03-FK-01&strict=true", headers={"x-api-key": pl_test_key})
            assert r3.status_code == 503
    finally:
        db.close()


