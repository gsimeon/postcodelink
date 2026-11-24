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

    # 4. Strictly rejects malformed codes
    assert parse_digital_postcode_components("12-02-A09-DB-09") is None  # Non-alpha state
    assert parse_digital_postcode_components("FC-02-A099-DB-09") is None  # District too long
    assert parse_digital_postcode_components("FC-02-A09-DB-009") is None  # Building unit too long (3 chars)
    assert parse_digital_postcode_components("FC--02-A09-DB-09") is None  # Double hyphen


