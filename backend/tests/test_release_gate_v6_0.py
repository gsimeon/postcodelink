"""Release Gate v6.0: Production Integrity, Permanent Audit Retention & Provider Telemetry Verification Tests."""
import sys
import time
import secrets
import signal
import subprocess
import os
import hashlib
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import text

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.profile import Profile
from backend.app.models.delivery import Delivery
from backend.app.models.delivery_event import DeliveryEvent
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.models.worker_heartbeat import WorkerHeartbeat
from backend.app.models.enums import AppRole, DeliveryStatus
from backend.app.services.notification_service import (
    NotificationDeliveryStatus,
    NotificationDispatchResult,
    get_notification_provider,
    TwilioNotificationProvider,
    TermiiNotificationProvider,
    SimulatedNotificationProvider,
)
from alembic.config import Config
from alembic import command
from backend.app.models.api_key import ApiKey
from backend.app.services.delivery_service import process_notification_outbox
from backend.app.core.security import create_access_token, hash_otp, encrypt_authenticated_pin
from backend.app.core.rate_limiter import (
    check_api_key_rate_limit,
    reset_api_key_rate_limits,
)
from backend.app.config import Settings, settings

client = TestClient(app)


def get_token(role: AppRole, email: str) -> str:
    db = SessionLocal()
    try:
        user = db.query(Profile).filter(Profile.email == email).first()
        if not user:
            user = Profile(
                id=f"v60-{secrets.token_hex(8)}",
                email=email,
                hashed_password="hashed_pw_test",
                full_name="V60 Test Operator",
                role=role,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return create_access_token(data={"sub": user.id, "role": user.role.value, "email": user.email})
    finally:
        db.close()


@pytest.fixture(autouse=True)
def clean_state():
    reset_api_key_rate_limits()
    db = SessionLocal()
    try:
        db.query(NotificationOutbox).delete()
        db.query(WorkerHeartbeat).delete()
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


# ==============================================================================
# 1. P1: Twilio Isolated Mocked Provider Verification Tests
# ==============================================================================
def test_twilio_verification_full_association_valid():
    """Verify Twilio verification succeeds when SID, recipient, sender, delivery fingerprint, and status match."""
    provider = TwilioNotificationProvider(
        account_sid="AC_test_account_sid_12345",
        auth_token="test_auth_token_12345",
        from_number="+15005550006",
    )
    delivery_id = "PL-TWILIO-V60-01"
    msg_id = "SM_valid_twilio_sid_123456"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "sid": msg_id,
        "to": "+2348011223344",
        "from": "+15005550006",
        "body": f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is 849201.",
        "status": "delivered",
    }

    with patch("httpx.get", return_value=mock_resp):
        res = provider.check_message_status(
            idempotency_key="idemp_1",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        )
        assert res is not None
        assert res.status == NotificationDeliveryStatus.SENT
        assert res.message_id == msg_id


def test_twilio_verification_rejects_wrong_recipient():
    """Verify Twilio verification rejects a valid SID if sent to an unrelated recipient."""
    provider = TwilioNotificationProvider(
        account_sid="AC_test_account_sid_12345",
        auth_token="test_auth_token_12345",
        from_number="+15005550006",
    )
    delivery_id = "PL-TWILIO-V60-02"
    msg_id = "SM_unrelated_recipient_sid"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "sid": msg_id,
        "to": "+2348099999999",  # Different recipient
        "from": "+15005550006",
        "body": f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is 123456.",
        "status": "delivered",
    }

    with patch("httpx.get", return_value=mock_resp):
        res = provider.check_message_status(
            idempotency_key="idemp_2",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",  # Expected recipient
            delivery_id=delivery_id,
        )
        assert res is None, "Twilio verification must reject message sent to another recipient!"


def test_twilio_verification_rejects_wrong_delivery_fingerprint():
    """Verify Twilio verification rejects a message belonging to a different delivery order."""
    provider = TwilioNotificationProvider(
        account_sid="AC_test_account_sid_12345",
        auth_token="test_auth_token_12345",
        from_number="+15005550006",
    )
    expected_delivery_id = "PL-TWILIO-EXPECTED-01"
    msg_id = "SM_wrong_delivery_sid"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "sid": msg_id,
        "to": "+2348011223344",
        "from": "+15005550006",
        "body": "Your PostcodeLink delivery confirmation PIN for order PL-OTHER-ORDER-999 is 654321.",
        "status": "delivered",
    }

    with patch("httpx.get", return_value=mock_resp):
        res = provider.check_message_status(
            idempotency_key="idemp_3",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=expected_delivery_id,
        )
        assert res is None, "Twilio verification must reject message referencing a different delivery order!"


def test_twilio_verification_rejects_wrong_sender():
    """Verify Twilio verification rejects a message sent from an unconfigured sender number."""
    provider = TwilioNotificationProvider(
        account_sid="AC_test_account_sid_12345",
        auth_token="test_auth_token_12345",
        from_number="+15005550006",
    )
    delivery_id = "PL-TWILIO-SENDER-01"
    msg_id = "SM_unauthorized_sender_sid"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "sid": msg_id,
        "to": "+2348011223344",
        "from": "+19999999999",  # Unauthorized sender
        "body": f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is 112233.",
        "status": "delivered",
    }

    with patch("httpx.get", return_value=mock_resp):
        res = provider.check_message_status(
            idempotency_key="idemp_4",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        )
        assert res is None, "Twilio verification must reject message dispatched from an unknown sender!"


def test_twilio_verification_reports_failed_status():
    """Verify Twilio verification accurately reports FAILED status for undelivered messages."""
    provider = TwilioNotificationProvider(
        account_sid="AC_test_account_sid_12345",
        auth_token="test_auth_token_12345",
        from_number="+15005550006",
    )
    delivery_id = "PL-TWILIO-FAILED-01"
    msg_id = "SM_undelivered_sid"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "sid": msg_id,
        "to": "+2348011223344",
        "from": "+15005550006",
        "body": f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is 998877.",
        "status": "undelivered",
        "error_message": "Carrier unreachable.",
    }

    with patch("httpx.get", return_value=mock_resp):
        res = provider.check_message_status(
            idempotency_key="idemp_5",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        )
        assert res is not None
        assert res.status == NotificationDeliveryStatus.FAILED
        assert "Carrier unreachable" in res.error_details


# ==============================================================================
# 2. P1: Termii Isolated Mocked Provider Verification Tests
# ==============================================================================
def test_termii_verification_full_association_valid():
    """Verify Termii verification succeeds when message_id, recipient, sender, delivery fingerprint, and status match."""
    provider = TermiiNotificationProvider(
        api_key="valid_termii_key_123",
        sender_id="PostcodeLink",
    )
    delivery_id = "PL-TERMII-V60-01"
    msg_id = "termii_msg_987654"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message_id": msg_id,
        "to": "2348011223344",
        "from": "PostcodeLink",
        "text": f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is 556677.",
        "status": "Delivered",
    }

    with patch("httpx.get", return_value=mock_resp):
        res = provider.check_message_status(
            idempotency_key="t_idemp_1",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        )
        assert res is not None
        assert res.status == NotificationDeliveryStatus.SENT
        assert res.message_id == msg_id


def test_termii_verification_rejects_wrong_recipient():
    """Verify Termii verification rejects a message sent to another recipient."""
    provider = TermiiNotificationProvider(
        api_key="valid_termii_key_123",
        sender_id="PostcodeLink",
    )
    delivery_id = "PL-TERMII-V60-02"
    msg_id = "termii_msg_wrong_recip"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message_id": msg_id,
        "to": "2348099999999",  # Wrong recipient
        "from": "PostcodeLink",
        "text": f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is 556677.",
        "status": "Delivered",
    }

    with patch("httpx.get", return_value=mock_resp):
        res = provider.check_message_status(
            idempotency_key="t_idemp_2",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        )
        assert res is None, "Termii verification must reject when recipient does not match!"


def test_termii_verification_rejects_wrong_delivery_fingerprint():
    """Verify Termii verification rejects a message referencing a different delivery order."""
    provider = TermiiNotificationProvider(
        api_key="valid_termii_key_123",
        sender_id="PostcodeLink",
    )
    delivery_id = "PL-TERMII-EXPECTED-01"
    msg_id = "termii_msg_wrong_fingerprint"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message_id": msg_id,
        "to": "2348011223344",
        "from": "PostcodeLink",
        "text": "Your PostcodeLink delivery confirmation PIN for order PL-TERMII-OTHER-999 is 556677.",
        "status": "Delivered",
    }

    with patch("httpx.get", return_value=mock_resp):
        res = provider.check_message_status(
            idempotency_key="t_idemp_3",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        )
        assert res is None, "Termii verification must reject when delivery fingerprint does not match!"


def test_termii_verification_reports_failed_status():
    """Verify Termii verification accurately reports FAILED status for undelivered messages."""
    provider = TermiiNotificationProvider(
        api_key="valid_termii_key_123",
        sender_id="PostcodeLink",
    )
    delivery_id = "PL-TERMII-FAILED-01"
    msg_id = "termii_msg_failed"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message_id": msg_id,
        "to": "2348011223344",
        "from": "PostcodeLink",
        "text": f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is 556677.",
        "status": "Failed",
        "message": "DND active on recipient number.",
    }

    with patch("httpx.get", return_value=mock_resp):
        res = provider.check_message_status(
            idempotency_key="t_idemp_4",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        )
        assert res is not None
        assert res.status == NotificationDeliveryStatus.FAILED


# ==============================================================================
# 3. P2: Simulated Provider Strict Identity Verification
# ==============================================================================
def test_simulated_provider_strict_identity_verification():
    """Verify SimulatedNotificationProvider enforces strict ID, recipient, and delivery fingerprint matching."""
    provider = SimulatedNotificationProvider()
    delivery_id = f"PL-SIM-TEST-{secrets.token_hex(4)}"
    phone = "+2348011223344"
    idemp_key = f"sim_idemp_{secrets.token_hex(4)}"

    # 1. Dispatch PIN
    res = provider.send_delivery_pin(
        recipient_phone=phone,
        recipient_name="Sim Customer",
        delivery_id=delivery_id,
        pin="445566",
        idempotency_key=idemp_key,
    )
    real_msg_id = res.message_id
    assert real_msg_id is not None

    # 2. Fabricated provider message ID must return None even if idempotency_key is passed
    assert provider.check_message_status(
        idempotency_key=idemp_key,
        provider_message_id="FABRICATED_SIM_MSG_ID",
        recipient_phone=phone,
        delivery_id=delivery_id,
    ) is None

    # 3. Real message ID with mismatched recipient must return None
    assert provider.check_message_status(
        idempotency_key=idemp_key,
        provider_message_id=real_msg_id,
        recipient_phone="+2348099999999",
        delivery_id=delivery_id,
    ) is None

    # 4. Real message ID with mismatched delivery must return None
    assert provider.check_message_status(
        idempotency_key=idemp_key,
        provider_message_id=real_msg_id,
        recipient_phone=phone,
        delivery_id="PL-OTHER-UNRELATED-999",
    ) is None

    # 5. Matching all parameters returns the authenticated result
    ok_res = provider.check_message_status(
        idempotency_key=idemp_key,
        provider_message_id=real_msg_id,
        recipient_phone=phone,
        delivery_id=delivery_id,
    )
    assert ok_res is not None
    assert ok_res.message_id == real_msg_id


# ==============================================================================
# 4. P1: Permanent Audit Retention & Soft Deletion
# ==============================================================================
def test_permanent_audit_retention_and_soft_deletion():
    """Verify that delivery records are soft-deleted, direct SQL deletion of audit records is blocked, and audit history is preserved."""
    admin_token = get_token(AppRole.ADMIN, "v60_audit_admin@test.ng")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    db = SessionLocal()
    delivery_id = f"PL-PERM-AUDIT-{secrets.token_hex(4)}"
    try:
        delivery = Delivery(
            id=delivery_id,
            recipient_phone="+2348011223344",
            recipient_name="Permanent Audit Recipient",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="50 Marina St",
            package_description="Compliance Audit Package",
            postcode_input="100271",
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("654321"),
            tracking_token=f"token_{secrets.token_hex(16)}",
            is_deleted=False,
        )
        db.add(delivery)
        db.commit()

        event = DeliveryEvent(
            delivery_id=delivery.id,
            status=DeliveryStatus.PENDING,
            actor_name="Audit Administrator",
            actor_role="admin",
            note="Initial order created for compliance verification.",
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        event_id = event.id

        # 1. Direct raw SQL UPDATE on delivery_events must FAIL at database trigger level
        update_failed = False
        try:
            db.execute(text(f"UPDATE delivery_events SET note = 'Tampered' WHERE id = '{event_id}'"))
            db.commit()
        except Exception:
            update_failed = True
            db.rollback()
        assert update_failed, "Database trigger must prevent direct raw SQL UPDATE on delivery_events!"

        # 2. Direct raw SQL DELETE on delivery_events must FAIL at database trigger level
        delete_failed = False
        try:
            db.execute(text(f"DELETE FROM delivery_events WHERE id = '{event_id}'"))
            db.commit()
        except Exception:
            delete_failed = True
            db.rollback()
        assert delete_failed, "Database trigger must prevent direct raw SQL DELETE on delivery_events!"

        # 3. Direct raw SQL DELETE on deliveries must FAIL (blocked by RESTRICT foreign key constraint or triggers)
        parent_delete_failed = False
        try:
            db.execute(text(f"DELETE FROM deliveries WHERE id = '{delivery_id}'"))
            db.commit()
        except Exception:
            parent_delete_failed = True
            db.rollback()
        assert parent_delete_failed, "Direct SQL DELETE on deliveries must be rejected when audit records exist!"

        # 4. Soft deletion via API endpoint
        del_resp = client.delete(f"/api/v1/deliveries/{delivery_id}", headers=admin_headers)
        assert del_resp.status_code == 204

        # 5. Delivery is marked is_deleted=True, status=CANCELLED
        db.refresh(delivery)
        assert delivery.is_deleted is True
        assert delivery.deleted_at is not None
        assert delivery.status == DeliveryStatus.CANCELLED

        # 6. API list query excludes the soft-deleted delivery
        list_resp = client.get("/api/v1/deliveries/", headers=admin_headers)
        assert list_resp.status_code == 200
        active_ids = [d["id"] for d in list_resp.json()]
        assert delivery_id not in active_ids

        # 7. Audit records remain permanently in delivery_events
        events = db.query(DeliveryEvent).filter(DeliveryEvent.delivery_id == delivery_id).all()
        assert len(events) >= 2  # Initial PENDING + CANCELLED soft-delete log
        assert any("soft-deleted and archived" in (ev.note or "") for ev in events)
    finally:
        db.close()


# ==============================================================================
# 5. P2: Consistent Production Redis Policy Matrix
# ==============================================================================
def test_production_redis_configuration_policy_consistency():
    """Verify consistent behavior across production Redis policies, single-instance opt-outs, and fail-closed handling."""
    # 1. Multi-instance production startup without REDIS_URL and without opt-out fails closed at boot
    with pytest.raises(ValueError, match="Fatal Production Configuration Error: REDIS_URL must be configured"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a" * 35,
            OUTBOX_ENCRYPTION_KEY="b" * 35,
            SMS_PROVIDER="termii",
            TERMII_API_KEY="valid_key",
            OUTBOX_WORKER_ENABLED=True,
            REDIS_URL=None,
            REDIS_REQUIRED_IN_PRODUCTION=True,
            ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION=False,
        )

    # 2. Production with explicit single-instance opt-out permits local in-memory rate limiting (does not fail closed)
    with patch("backend.app.config.settings.ENVIRONMENT", "production"), \
         patch("backend.app.config.settings.RATE_LIMIT_REDIS_FAIL_CLOSED", True), \
         patch("backend.app.config.settings.ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", True), \
         patch("backend.app.core.rate_limiter._get_redis_client", return_value=None):
        test_key = f"v60_optout_{secrets.token_hex(4)}"
        # Allowed under single-instance opt-out: does NOT raise HTTP 503
        check_api_key_rate_limit(test_key, limit_per_minute=10)

    # 3. Production without opt-out strictly fails closed with HTTP 503 when Redis is down
    with patch("backend.app.config.settings.ENVIRONMENT", "production"), \
         patch("backend.app.config.settings.RATE_LIMIT_REDIS_FAIL_CLOSED", True), \
         patch("backend.app.config.settings.ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", False), \
         patch("backend.app.core.rate_limiter._get_redis_client", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            check_api_key_rate_limit("v60_failclosed_key", limit_per_minute=10)
        assert exc_info.value.status_code == 503
        assert "fail-closed" in exc_info.value.detail.lower()

    # 4. Development environment permits local in-memory rate limiting without Redis
    with patch("backend.app.config.settings.ENVIRONMENT", "development"), \
         patch("backend.app.core.rate_limiter._get_redis_client", return_value=None):
        dev_key = f"v60_dev_{secrets.token_hex(4)}"
        check_api_key_rate_limit(dev_key, limit_per_minute=10)


# ==============================================================================
# 6. P2: Subprocess Worker Real Signal Handling & Stale Detection
# ==============================================================================
def test_subprocess_worker_os_signal_shutdown_and_crash_recovery():
    """Verify that launching the worker as an actual OS subprocess cleanly handles termination signals and updates DB."""
    worker_id = f"v60-proc-worker-{secrets.token_hex(4)}"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()

    # 1. Launch real worker process as subprocess
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [sys.executable, "-m", "backend.app.workers.outbox_worker", "--worker-id", worker_id, "--interval", "1"],
        env=env,
        creationflags=creationflags,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # 2. Wait up to 5 seconds for heartbeat in database
    db = SessionLocal()
    hb = None
    try:
        for _ in range(25):
            time.sleep(0.2)
            hb = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
            if hb:
                break

        assert hb is not None, "Worker subprocess did not write heartbeat to database within 5 seconds!"
        assert hb.status in ["active", "idle", "processing"]

        # 3. Send OS termination signal
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGTERM)

        # 4. Wait for process exit
        proc.wait(timeout=5)
        assert proc.returncode in [0, 1, -signal.SIGTERM if hasattr(signal, "SIGTERM") else 0, 15]

        # 5. Verify database records clean shutdown
        db.refresh(hb)
        assert hb.status == "stopped"
        assert hb.stop_reason == "graceful_shutdown"
    finally:
        if proc.poll() is None:
            proc.kill()
        db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).delete()
        db.commit()
        db.close()


# ==============================================================================
# 7. P2: Manual Requeue Dispatch Attempt Tracking & Idempotency History
# ==============================================================================
def test_manual_requeue_dispatch_attempt_and_idempotency_history():
    """Verify that manual requeue increments dispatch_attempt, updates idempotency_key with attempt suffix, and records history."""
    admin_token = get_token(AppRole.ADMIN, "v60_requeue_admin@test.ng")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    db = SessionLocal()
    delivery_id = f"PL-REQUEUE-V60-{secrets.token_hex(4)}"
    initial_idemp = f"orig_idemp_key_{secrets.token_hex(4)}"
    outbox_id = None
    try:
        delivery = Delivery(
            id=delivery_id,
            recipient_phone="+2348077665544",
            recipient_name="Requeue Test Customer",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="80 Allen Ave",
            package_description="Requeue Tracking Test",
            postcode_input="100271",
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("998877"),
            tracking_token=f"token_{secrets.token_hex(16)}",
            is_deleted=False,
        )
        db.add(delivery)
        db.commit()

        outbox_item = NotificationOutbox(
            delivery_id=delivery.id,
            notification_type="otp_delivery_pin",
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            provider="simulated",
            status=NotificationDeliveryStatus.FAILED,
            retry_count=3,
            max_retries=3,
            error_details="Max retries exhausted.",
            idempotency_key=initial_idemp,
            dispatch_attempt=1,
        )
        db.add(outbox_item)
        db.commit()
        db.refresh(outbox_item)
        outbox_id = outbox_item.id

        # 1. Admin requeues exhausted item
        requeue_resp = client.post(
            f"/api/v1/deliveries/outbox/{outbox_id}/reconcile",
            json={
                "resolution": "requeue",
                "reason": "Carrier network outage resolved; supervisor authorized second dispatch attempt.",
            },
            headers=admin_headers,
        )
        assert requeue_resp.status_code == 200

        db.refresh(outbox_item)
        assert outbox_item.status == NotificationDeliveryStatus.QUEUED
        assert outbox_item.retry_count == 0
        assert outbox_item.dispatch_attempt == 2
        assert outbox_item.original_idempotency_key == initial_idemp
        assert outbox_item.idempotency_key == f"{initial_idemp}_att2"

        # 2. Check DeliveryEvent audit trail records dispatch attempt and original idempotency key
        event = db.query(DeliveryEvent).filter(DeliveryEvent.delivery_id == delivery_id).first()
        assert event is not None
        assert "dispatch_attempt: 2" in outbox_item.error_details
        assert initial_idemp in outbox_item.error_details
    finally:
        deliv = db.query(Delivery).filter(Delivery.id == delivery_id).first()
        if deliv:
            deliv.is_deleted = True
        db.commit()
        db.close()


# ==============================================================================
# 8. P1: Provider Verification Rejects Simulated Evidence
# ==============================================================================
def test_provider_telemetry_verified_strictly_rejects_simulated_provider():
    """Verify that provider_telemetry_verified strictly rejects simulated provider records with HTTP 422."""
    admin_token = get_token(AppRole.ADMIN, "v60_sim_reject_admin@test.ng")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    delivery_id = f"PL-SIM-REJECT-{secrets.token_hex(4)}"
    db = SessionLocal()
    try:
        delivery = Delivery(
            id=delivery_id,
            recipient_phone="+2348011223344",
            recipient_name="Sim Reject Recipient",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="45 Sim St",
            package_description="Sim Reject Package",
            postcode_input="100271",
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("112233"),
            tracking_token=f"token_{secrets.token_hex(16)}",
            is_deleted=False,
        )
        db.add(delivery)
        db.commit()

        outbox_item = NotificationOutbox(
            delivery_id=delivery.id,
            notification_type="otp_delivery_pin",
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            provider="simulated",
            status=NotificationDeliveryStatus.RECONCILIATION_REQUIRED,
            retry_count=3,
            max_retries=3,
            idempotency_key=f"idemp_sim_rej_{secrets.token_hex(4)}",
            dispatch_attempt=1,
        )
        db.add(outbox_item)
        db.commit()
        db.refresh(outbox_item)
        outbox_id = outbox_item.id

        # Attempt provider_telemetry_verified on simulated item -> Must receive HTTP 422!
        resp = client.post(
            f"/api/v1/deliveries/outbox/{outbox_id}/reconcile",
            json={
                "resolution": "mark_sent",
                "evidence_type": "provider_telemetry_verified",
                "provider_message_id": "sim_fabricated_999",
                "reason": "Operator asserting simulated gateway response.",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 422
        assert "simulated notifications cannot be used" in resp.json()["detail"].lower()
    finally:
        deliv = db.query(Delivery).filter(Delivery.id == delivery_id).first()
        if deliv:
            deliv.is_deleted = True
        db.commit()
        db.close()


# ==============================================================================
# 9. P1: Twilio Verification Fail-Closed on Missing Upstream Fields
# ==============================================================================
def test_twilio_verification_fail_closed_missing_fields():
    """Verify Twilio check_message_status fails closed (returns None) when sender, body, or recipient is missing."""
    provider = TwilioNotificationProvider(
        account_sid="AC_test_account_sid_12345",
        auth_token="test_auth_token_12345",
        from_number="+15005550006",
    )
    delivery_id = "PL-TWILIO-MISSING-01"
    msg_id = "SM_twilio_missing_fields"

    # 1. Missing sender 'from' in provider response -> returns None
    resp_missing_from = MagicMock(status_code=200, json=lambda: {
        "sid": msg_id,
        "to": "+2348011223344",
        "body": f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is 849201.",
        "status": "delivered",
    })
    with patch("httpx.get", return_value=resp_missing_from):
        assert provider.check_message_status(
            idempotency_key="key",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        ) is None

    # 2. Missing 'body' in provider response -> returns None
    resp_missing_body = MagicMock(status_code=200, json=lambda: {
        "sid": msg_id,
        "to": "+2348011223344",
        "from": "+15005550006",
        "status": "delivered",
    })
    with patch("httpx.get", return_value=resp_missing_body):
        assert provider.check_message_status(
            idempotency_key="key",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        ) is None

    # 3. Missing 'to' in provider response -> returns None
    resp_missing_to = MagicMock(status_code=200, json=lambda: {
        "sid": msg_id,
        "from": "+15005550006",
        "body": f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is 849201.",
        "status": "delivered",
    })
    with patch("httpx.get", return_value=resp_missing_to):
        assert provider.check_message_status(
            idempotency_key="key",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        ) is None


# ==============================================================================
# 10. P1: Termii Verification Fail-Closed & No Fallback to Inbox
# ==============================================================================
def test_termii_verification_fail_closed_missing_fields_and_no_inbox_fallback():
    """Verify Termii check_message_status fails closed on missing fields and rejects non-200 without inbox fallback."""
    provider = TermiiNotificationProvider(
        api_key="test_termii_api_key_12345",
        sender_id="PostcodeLink",
    )
    delivery_id = "PL-TERMII-MISSING-01"
    msg_id = "MSG_termii_missing_fields"

    # 1. Non-200 status -> returns None immediately without querying inbox
    resp_error = MagicMock(status_code=404, json=lambda: {"message": "Not found"})
    with patch("httpx.get", return_value=resp_error) as mock_get:
        res = provider.check_message_status(
            idempotency_key="key",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        )
        assert res is None
        # Assert httpx.get was called strictly once (no fallback to inbox!)
        assert mock_get.call_count == 1
        assert "inbox" not in mock_get.call_args[0][0]

    # 2. Missing sender in response -> returns None
    resp_missing_sender = MagicMock(status_code=200, json=lambda: {
        "message_id": msg_id,
        "to": "2348011223344",
        "text": f"Your delivery PIN for order {delivery_id} is 123456.",
        "status": "delivered",
    })
    with patch("httpx.get", return_value=resp_missing_sender):
        assert provider.check_message_status(
            idempotency_key="key",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        ) is None

    # 3. Missing text in response -> returns None
    resp_missing_text = MagicMock(status_code=200, json=lambda: {
        "message_id": msg_id,
        "to": "2348011223344",
        "from": "PostcodeLink",
        "status": "delivered",
    })
    with patch("httpx.get", return_value=resp_missing_text):
        assert provider.check_message_status(
            idempotency_key="key",
            provider_message_id=msg_id,
            recipient_phone="+2348011223344",
            delivery_id=delivery_id,
        ) is None


# ==============================================================================
# 11. P1: Manual Requeue Clears Active Provider Message ID
# ==============================================================================
def test_manual_requeue_clears_active_provider_message_id_and_prevents_stale_sent():
    """Verify that manual requeue clears active provider_message_id, records last_failed_provider_message_id, and causes the worker to dispatch anew."""
    admin_token = get_token(AppRole.ADMIN, "v60_requeue_stale_admin@test.ng")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    delivery_id = f"PL-REQUEUE-STALE-{secrets.token_hex(4)}"
    stale_msg_id = "old_stale_provider_message_998877"
    db = SessionLocal()
    try:
        delivery = Delivery(
            id=delivery_id,
            recipient_phone="+2348011223344",
            recipient_name="Requeue Recipient",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="10 Marina St",
            package_description="Requeue Test Package",
            postcode_input="100271",
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("112233"),
            tracking_token=f"token_{secrets.token_hex(16)}",
            is_deleted=False,
        )
        db.add(delivery)
        db.commit()

        outbox_item = NotificationOutbox(
            delivery_id=delivery.id,
            notification_type="otp_delivery_pin",
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            message_payload=encrypt_authenticated_pin("112233", delivery_id=delivery.id),
            provider="simulated",
            status=NotificationDeliveryStatus.FAILED,
            retry_count=3,
            max_retries=3,
            provider_message_id=stale_msg_id,
            idempotency_key=f"idemp_stale_{secrets.token_hex(4)}",
            dispatch_attempt=1,
        )
        db.add(outbox_item)
        db.commit()
        db.refresh(outbox_item)
        outbox_id = outbox_item.id

        # 1. Requeue item
        req_res = client.post(
            f"/api/v1/deliveries/outbox/{outbox_id}/reconcile",
            json={
                "resolution": "requeue",
                "reason": "Previous dispatch confirmed failed; operator authorized attempt 2.",
            },
            headers=admin_headers,
        )
        assert req_res.status_code == 200

        db.refresh(outbox_item)
        # Verify active provider_message_id is CLEARED (None), and stale ID preserved in last_failed_provider_message_id
        assert outbox_item.provider_message_id is None
        assert outbox_item.last_failed_provider_message_id == stale_msg_id
        assert outbox_item.status == NotificationDeliveryStatus.QUEUED
        assert outbox_item.dispatch_attempt == 2
        assert "_att2" in outbox_item.idempotency_key

        # 2. Process outbox with worker: worker must perform fresh dispatch, NOT falsely mark SENT with stale ID!
        processed = process_notification_outbox(db, max_items=10)
        assert processed >= 1

        db.refresh(outbox_item)
        assert outbox_item.status in [NotificationDeliveryStatus.SENT, NotificationDeliveryStatus.SIMULATED]
        # Verify fresh message ID generated, distinct from stale ID
        assert outbox_item.provider_message_id is not None
        assert outbox_item.provider_message_id != stale_msg_id
        assert outbox_item.provider_message_id.startswith("sim_")

        # 3. Requeuing an already sent item must be REJECTED (HTTP 422)
        rej_res = client.post(
            f"/api/v1/deliveries/outbox/{outbox_id}/reconcile",
            json={"resolution": "requeue", "reason": "Attempting invalid requeue of sent item"},
            headers=admin_headers,
        )
        assert rej_res.status_code == 422
    finally:
        deliv = db.query(Delivery).filter(Delivery.id == delivery_id).first()
        if deliv:
            deliv.is_deleted = True
        db.commit()
        db.close()


# ==============================================================================
# 12. P1: Commercial Postcode API Authentication & Metering
# ==============================================================================
def test_commercial_postcode_api_key_mandatory_authentication():
    """Verify commercial postcode endpoints strictly require active API keys and meter quota."""
    merchant_token = get_token(AppRole.MERCHANT, "v60_comm_merchant@test.ng")
    merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

    # 1. Create a commercial API key with quota 5
    key_resp = client.post("/api/v1/api-keys/", json={"name": "Commercial Key", "monthly_quota": 5}, headers=merchant_headers)
    assert key_resp.status_code == 201
    key_data = key_resp.json()
    raw_api_key = key_data["api_key"]

    # 2. Missing x-api-key on commercial endpoint -> HTTP 401
    unauth_res = client.get("/api/v1/postcodes/commercial/lookup?state=Lagos")
    assert unauth_res.status_code == 401
    assert "missing 'x-api-key'" in unauth_res.json()["detail"].lower()

    # 3. Invalid x-api-key -> HTTP 401
    invalid_res = client.get("/api/v1/postcodes/commercial/lookup?state=Lagos", headers={"x-api-key": "invalid_key_999999"})
    assert invalid_res.status_code == 401
    assert "invalid or revoked" in invalid_res.json()["detail"].lower()

    # 4. Valid x-api-key -> HTTP 200 and meters quota
    valid_res = client.get("/api/v1/postcodes/commercial/lookup?state=Lagos", headers={"x-api-key": raw_api_key})
    assert valid_res.status_code == 200
    assert valid_res.json()["count"] > 0

    # 5. Cleanse endpoint with valid x-api-key -> HTTP 200
    cleanse_res = client.post(
        "/api/v1/postcodes/commercial/cleanse",
        json={"address": "15 Marina St, Lagos Island", "state": "Lagos"},
        headers={"x-api-key": raw_api_key},
    )
    assert cleanse_res.status_code == 200


# ==============================================================================
# 13. P1: Public Postcode Demo IP Rate Limiting
# ==============================================================================
def test_public_postcode_demo_client_ip_rate_limiting():
    """Verify that unauthenticated callers on public demo endpoints are restricted by IP rate limiting."""
    reset_api_key_rate_limits()
    test_ip = f"192.168.{secrets.randbelow(200) + 10}.{secrets.randbelow(200) + 10}"
    headers = {"x-forwarded-for": test_ip}

    # First 15 requests succeed (within limit of 15/min)
    for _ in range(15):
        res = client.get("/api/v1/postcodes/lookup?state=Lagos", headers=headers)
        assert res.status_code == 200

    # 16th request must be rate-limited (HTTP 429)
    limited_res = client.get("/api/v1/postcodes/lookup?state=Lagos", headers=headers)
    assert limited_res.status_code == 429
    assert "public demo rate limit exceeded" in limited_res.json()["detail"].lower()
    assert "retry-after" in limited_res.headers


# ==============================================================================
# 14. P2: Soft-Deleted Deliveries Excluded From Public Tracking
# ==============================================================================
def test_soft_deleted_deliveries_excluded_from_public_tracking():
    """Verify that soft-deleted deliveries are excluded from public tracking and their tracking tokens are revoked."""
    merchant_token = get_token(AppRole.MERCHANT, "v60_track_merchant@test.ng")
    merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

    tracking_token = f"token_track_test_{secrets.token_hex(16)}"
    delivery_id = f"PL-TRACK-TEST-{secrets.token_hex(4)}"
    db = SessionLocal()
    merchant = db.query(Profile).filter(Profile.email == "v60_track_merchant@test.ng").first()
    try:
        deliv = Delivery(
            id=delivery_id,
            merchant_id=merchant.id,
            recipient_phone="+2348011223344",
            recipient_name="Tracking Test Recipient",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="12 Track Ave",
            package_description="Tracking Package",
            postcode_input="100271",
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("123456"),
            tracking_token=tracking_token,
            is_deleted=False,
        )
        db.add(deliv)
        db.commit()

        # 1. Public tracking before deletion -> HTTP 200
        pub_res = client.get(f"/api/v1/deliveries/track/{tracking_token}")
        assert pub_res.status_code == 200
        assert pub_res.json()["status"] == DeliveryStatus.PENDING.value

        # 2. Soft-delete the delivery
        del_res = client.delete(f"/api/v1/deliveries/{delivery_id}", headers=merchant_headers)
        assert del_res.status_code == 204

        # 3. Public tracking with original tracking token must return HTTP 404!
        after_del_res = client.get(f"/api/v1/deliveries/track/{tracking_token}")
        assert after_del_res.status_code == 404
        assert "not found" in after_del_res.json()["detail"].lower()
    finally:
        deliv_obj = db.query(Delivery).filter(Delivery.id == delivery_id).first()
        if deliv_obj:
            deliv_obj.is_deleted = True
        db.commit()
        db.close()


# ==============================================================================
# 15. P2: Migration Downgrade Restores Audit Triggers & Upgrade Lifecycle
# ==============================================================================
def test_migration_downgrade_restores_audit_triggers_and_upgrade_lifecycle():
    """Verify that downgrade to v5.9 restores audit triggers without error, and upgrade back to v6.0 succeeds."""
    alembic_cfg = Config("alembic.ini")

    try:
        # 1. Downgrade to Release Gate v5.9 revision (b2c3d4e5f6a7)
        command.downgrade(alembic_cfg, "b2c3d4e5f6a7")

        # Verify v5.9 audit trigger works: raw update on delivery_events must fail
        db = SessionLocal()
        deliv_id = f"PL-MIGR-TEST-{secrets.token_hex(4)}"
        tok_id = f"tok_migr_{secrets.token_hex(8)}"
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            # Insert using raw SQL because v5.9 schema does not have v6.0 columns (is_deleted, deleted_at)
            db.execute(
                text("""
                INSERT INTO deliveries (
                    id, tracking_token, recipient_name, recipient_phone,
                    destination_address, destination_area, destination_state,
                    postcode_input, postcode_status, package_description,
                    fee, status, otp_hash, otp_attempts, otp_max_attempts,
                    pod_verified, version, created_at, updated_at
                )
                VALUES (
                    :id, :tracking_token, :recipient_name, :recipient_phone,
                    :destination_address, :destination_area, :destination_state,
                    :postcode_input, :postcode_status, :package_description,
                    :fee, :status, :otp_hash, :otp_attempts, :otp_max_attempts,
                    :pod_verified, :version, :created_at, :updated_at
                )
                """),
                {
                    "id": deliv_id,
                    "tracking_token": tok_id,
                    "recipient_name": "Migr Recipient",
                    "recipient_phone": "+2348011223344",
                    "destination_address": "55 Migr St",
                    "destination_area": "Ikeja",
                    "destination_state": "Lagos",
                    "postcode_input": "100271",
                    "postcode_status": "UNVERIFIED",
                    "package_description": "Migr Package",
                    "fee": 2500.0,
                    "status": "PENDING",
                    "otp_hash": "hash123",
                    "otp_attempts": 0,
                    "otp_max_attempts": 3,
                    "pod_verified": False,
                    "version": 1,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            db.execute(
                text("""
                INSERT INTO delivery_events (
                    id, delivery_id, status, actor_name, actor_role, note, occurred_at
                )
                VALUES (
                    :id, :delivery_id, :status, :actor_name, :actor_role, :note, :occurred_at
                )
                """),
                {
                    "id": f"evt_{deliv_id}",
                    "delivery_id": deliv_id,
                    "status": "PENDING",
                    "actor_name": "Migration Tester",
                    "actor_role": "admin",
                    "note": "Testing v5.9 audit trigger",
                    "occurred_at": datetime.now(timezone.utc),
                },
            )
            db.commit()

            # Direct SQL UPDATE must still be blocked by restored v5.9 trigger
            update_blocked = False
            try:
                db.execute(text(f"UPDATE delivery_events SET note = 'Tampered' WHERE id = 'evt_{deliv_id}'"))
                db.commit()
            except Exception:
                update_blocked = True
                db.rollback()
            assert update_blocked, "Restored v5.9 trigger must block direct raw SQL UPDATE on delivery_events!"
        finally:
            db.close()
    finally:
        # 2. Upgrade back to Release Gate v6.0 revision (c3d4e5f6a7b8)
        command.upgrade(alembic_cfg, "head")


# ==============================================================================
# 16. Commercial API Quota Metering & Anti-Spoofing IP Rate Limiting Tests
# ==============================================================================

def test_commercial_lookup_increments_monthly_quota_by_exactly_one():
    """Verify commercial postcode lookup meters monthly quota exactly once (eliminating double-metering)."""
    reset_api_key_rate_limits()
    db = SessionLocal()
    try:
        email = f"comm_lookup_{secrets.token_hex(6)}@example.com"
        merchant = Profile(
            id=f"prof_{secrets.token_hex(8)}",
            email=email,
            hashed_password="pw",
            full_name="Commercial Merchant 1",
            role=AppRole.MERCHANT,
        )
        db.add(merchant)
        db.commit()

        raw_key = f"pkl_live_{secrets.token_hex(20)}"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        now_period = datetime.now(timezone.utc).strftime("%Y-%m")
        api_key = ApiKey(
            id=f"key_{secrets.token_hex(8)}",
            merchant_id=merchant.id,
            name="Commercial Lookup Key",
            key_prefix=raw_key[:12],
            hashed_key=key_hash,
            monthly_quota=100,
            current_period=now_period,
            period_usage_count=0,
            usage_count=0,
            is_active=True,
            is_revoked=False,
        )
        db.add(api_key)
        db.commit()

        # Call commercial lookup endpoint
        res = client.get(
            "/api/v1/postcodes/commercial/lookup?state=Lagos",
            headers={"x-api-key": raw_key},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["count"] > 0
        assert data["api_integration_version"] == "2026.1"

        # Verify quota incremented by EXACTLY 1 in database
        db.expire_all()
        updated_key = db.query(ApiKey).filter(ApiKey.id == api_key.id).first()
        assert updated_key.period_usage_count == 1, f"Expected period_usage_count=1, got {updated_key.period_usage_count} (double metering bug!)"
        assert updated_key.usage_count == 1
    finally:
        db.close()


def test_commercial_cleanse_increments_monthly_quota_by_exactly_one():
    """Verify commercial address cleanse meters monthly quota exactly once (eliminating double-metering)."""
    reset_api_key_rate_limits()
    db = SessionLocal()
    try:
        email = f"comm_cleanse_{secrets.token_hex(6)}@example.com"
        merchant = Profile(
            id=f"prof_{secrets.token_hex(8)}",
            email=email,
            hashed_password="pw",
            full_name="Commercial Merchant 2",
            role=AppRole.MERCHANT,
        )
        db.add(merchant)
        db.commit()

        raw_key = f"pkl_live_{secrets.token_hex(20)}"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        now_period = datetime.now(timezone.utc).strftime("%Y-%m")
        api_key = ApiKey(
            id=f"key_{secrets.token_hex(8)}",
            merchant_id=merchant.id,
            name="Commercial Cleanse Key",
            key_prefix=raw_key[:12],
            hashed_key=key_hash,
            monthly_quota=100,
            current_period=now_period,
            period_usage_count=0,
            usage_count=0,
            is_active=True,
            is_revoked=False,
        )
        db.add(api_key)
        db.commit()

        # Call commercial cleanse endpoint
        res = client.post(
            "/api/v1/postcodes/commercial/cleanse",
            headers={"x-api-key": raw_key},
            json={
                "address": "12 Broad Street, Marina, Lagos",
                "state": "Lagos",
                "area": "Marina",
                "postcode": "100221",
            },
        )
        assert res.status_code == 200

        # Verify quota incremented by EXACTLY 1 in database
        db.expire_all()
        updated_key = db.query(ApiKey).filter(ApiKey.id == api_key.id).first()
        assert updated_key.period_usage_count == 1, f"Expected period_usage_count=1, got {updated_key.period_usage_count} (double metering bug!)"
        assert updated_key.usage_count == 1
    finally:
        db.close()


def test_commercial_quota_boundary_permits_one_and_rejects_second():
    """Verify that an API key with monthly_quota=1 succeeds on 1st call and is blocked with HTTP 429 on 2nd call."""
    reset_api_key_rate_limits()
    db = SessionLocal()
    try:
        email = f"comm_quota_{secrets.token_hex(6)}@example.com"
        merchant = Profile(
            id=f"prof_{secrets.token_hex(8)}",
            email=email,
            hashed_password="pw",
            full_name="Commercial Merchant Quota Boundary",
            role=AppRole.MERCHANT,
        )
        db.add(merchant)
        db.commit()

        raw_key = f"pkl_live_{secrets.token_hex(20)}"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        now_period = datetime.now(timezone.utc).strftime("%Y-%m")
        api_key = ApiKey(
            id=f"key_{secrets.token_hex(8)}",
            merchant_id=merchant.id,
            name="Strict 1-Quota Key",
            key_prefix=raw_key[:12],
            hashed_key=key_hash,
            monthly_quota=1,
            current_period=now_period,
            period_usage_count=0,
            usage_count=0,
            is_active=True,
            is_revoked=False,
        )
        db.add(api_key)
        db.commit()

        # 1st request should succeed (using 1 of 1 quota)
        res1 = client.get(
            "/api/v1/postcodes/commercial/lookup?state=Lagos",
            headers={"x-api-key": raw_key},
        )
        assert res1.status_code == 200

        # 2nd request must fail with HTTP 429
        res2 = client.get(
            "/api/v1/postcodes/commercial/lookup?state=Lagos",
            headers={"x-api-key": raw_key},
        )
        assert res2.status_code == 429
        assert "exceeded" in res2.json()["detail"].lower() and "quota" in res2.json()["detail"].lower()

        # Check DB count remains 1
        db.expire_all()
        updated_key = db.query(ApiKey).filter(ApiKey.id == api_key.id).first()
        assert updated_key.period_usage_count == 1
    finally:
        db.close()


def test_public_demo_ip_rate_limiting_rejects_spoofed_x_forwarded_for():
    """Verify that untrusted direct peer cannot bypass IP rate limiting by spoofing X-Forwarded-For."""
    from backend.app.core.network import get_trusted_client_ip
    from starlette.requests import Request

    reset_api_key_rate_limits()

    # 1. Direct unit test of get_trusted_client_ip
    scope_untrusted = {
        "type": "http",
        "client": ("198.51.100.25", 54321),
        "headers": [(b"x-forwarded-for", b"203.0.113.50, 1.1.1.1")],
    }
    req_untrusted = Request(scope_untrusted)
    # Untrusted proxy origin must return direct peer IP, ignoring X-Forwarded-For
    trusted_proxies = ["10.0.0.1", "127.0.0.1"]
    assert get_trusted_client_ip(req_untrusted, trusted_proxies=trusted_proxies) == "198.51.100.25"

    # 2. Trusted proxy origin extracts real client IP
    scope_trusted = {
        "type": "http",
        "client": ("10.0.0.1", 54321),
        "headers": [(b"x-forwarded-for", b"203.0.113.50, 10.0.0.1")],
    }
    req_trusted = Request(scope_trusted)
    assert get_trusted_client_ip(req_trusted, trusted_proxies=trusted_proxies) == "203.0.113.50"

    # 3. HTTP endpoint test: direct host cannot bypass rate limit by rotating spoofed XFF
    untrusted_host = f"198.51.{secrets.randbelow(200) + 10}.{secrets.randbelow(200) + 10}"
    with patch("backend.app.routers.postcodes.get_trusted_client_ip", return_value=untrusted_host):
        for i in range(15):
            spoofed_xff = f"100.{i}.{secrets.randbelow(200)}.{secrets.randbelow(200)}"
            res = client.get(
                "/api/v1/postcodes/lookup?state=Lagos",
                headers={"x-forwarded-for": spoofed_xff},
            )
            assert res.status_code == 200

        # 16th request from same direct host with yet another spoofed XFF must be rate-limited (HTTP 429)
        new_spoofed_xff = "8.8.8.8"
        res_blocked = client.get(
            "/api/v1/postcodes/lookup?state=Lagos",
            headers={"x-forwarded-for": new_spoofed_xff},
        )
        assert res_blocked.status_code == 429
        assert "public demo rate limit exceeded" in res_blocked.json()["detail"].lower()


def test_termii_status_verification_uses_configured_account_base_url():
    """Verify TermiiNotificationProvider uses custom account base URL for status check and dispatch."""
    custom_base = "https://custom-termii.enterprise.ng"
    provider = TermiiNotificationProvider(
        api_key="secret_termii_key",
        sender_id="CustomTermii",
        base_url=custom_base,
    )
    assert provider.account_base_url == custom_base
    assert provider.send_url == f"{custom_base}/api/sms/send"
    assert provider.status_url == f"{custom_base}/api/sms/status"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message_id": "msg_cust_999",
        "to": "+2348012345678",
        "from": "CustomTermii",
        "text": "Your delivery confirmation PIN for order PL-8888 is 123456.",
        "status": "delivered",
    }

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        result = provider.check_message_status(
            idempotency_key="idemp_cust",
            provider_message_id="msg_cust_999",
            recipient_phone="+2348012345678",
            delivery_id="PL-8888",
        )
        assert result is not None
        assert result.status == NotificationDeliveryStatus.SENT
        assert result.message_id == "msg_cust_999"

        # Verify that httpx.get was called using the custom account status URL
        mock_get.assert_called_once()
        call_url = mock_get.call_args[0][0]
        assert call_url == f"{custom_base}/api/sms/status"
        params = mock_get.call_args[1].get("params", {})
        assert params.get("message_id") == "msg_cust_999"
        assert params.get("api_key") == "secret_termii_key"


def test_nipost_provenance_preserves_upstream_version_or_returns_null():
    """Verify NIPOST provenance preserves upstream dataset_version when present, returns None when omitted/not found, and sets api_integration_version to 2026.1."""
    from backend.app.services.nipost_client import NIPOSTClient, NIPOSTLookupResult, NIPOSTLookupStatus
    from backend.app.routers.postcodes import execute_postcode_lookup

    db = SessionLocal()
    try:
        mock_client = MagicMock(spec=NIPOSTClient)
        mock_client.is_configured = True

        # Scenario 1: Upstream NIPOST provides dataset_version "2026.3"
        mock_client.lookup_postcode.return_value = NIPOSTLookupResult(
            status=NIPOSTLookupStatus.FOUND,
            data={
                "code": "100001",
                "state": "Lagos",
                "area": "Marina",
                "dataset_version": "2026.3",
            },
        )
        res1 = execute_postcode_lookup(db=db, code="100001", client=mock_client)
        assert res1.is_live_nipost is True
        assert res1.dataset_version == "2026.3"
        assert res1.api_integration_version == "2026.1"

        # Scenario 2: Upstream NIPOST omits dataset_version
        mock_client.lookup_postcode.return_value = NIPOSTLookupResult(
            status=NIPOSTLookupStatus.FOUND,
            data={
                "code": "100001",
                "state": "Lagos",
                "area": "Marina",
            },
        )
        res2 = execute_postcode_lookup(db=db, code="100001", client=mock_client)
        assert res2.is_live_nipost is True
        assert res2.dataset_version is None
        assert res2.api_integration_version == "2026.1"

        # Scenario 3: Upstream NIPOST returns NOT_FOUND
        mock_client.lookup_postcode.return_value = NIPOSTLookupResult(
            status=NIPOSTLookupStatus.NOT_FOUND,
            error_message="Code not in registry",
            data=None,
        )
        res3 = execute_postcode_lookup(db=db, code="999999", client=mock_client)
        assert res3.is_live_nipost is True
        assert res3.count == 0
        assert res3.dataset_version is None
        assert res3.api_integration_version == "2026.1"

        # Scenario 4: Local fallback reference has dataset_version "2024.2"
        mock_client.lookup_postcode.return_value = NIPOSTLookupResult(
            status=NIPOSTLookupStatus.UNAVAILABLE,
            error_message="Gateway timeout",
        )
        res4 = execute_postcode_lookup(db=db, state="Lagos", strict=False, client=mock_client)
        assert res4.is_live_nipost is False
        assert res4.dataset_version == "2024.2"
        assert res4.api_integration_version == "2026.1"
    finally:
        db.close()


# ==============================================================================
# 17. Release Gate v6.0.1 Corrective Hardening & Scalability Tests
# ==============================================================================

def test_api_key_creation_with_and_without_expiry_and_expiration_enforcement():
    """Verify API-key creation with/without expires_in_days (fixing missing timedelta) and expiration enforcement."""
    db = SessionLocal()
    try:
        merchant_email = f"merchant_exp_{secrets.token_hex(6)}@example.com"
        token = get_token(AppRole.MERCHANT, merchant_email)
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create a key without expiry — HTTP 201
        res1 = client.post(
            "/api/v1/api-keys/",
            json={"name": "Non-Expiring Key", "monthly_quota": 5000},
            headers=headers,
        )
        assert res1.status_code == 201
        data1 = res1.json()
        assert data1["name"] == "Non-Expiring Key"
        assert data1["expires_at"] is None
        assert data1["api_key"].startswith("pl_live_")

        # 2. Create a key with 30-day expiry — HTTP 201 (previously raised NameError: timedelta)
        res2 = client.post(
            "/api/v1/api-keys/",
            json={"name": "30-Day Expiring Key", "monthly_quota": 5000, "expires_in_days": 30},
            headers=headers,
        )
        assert res2.status_code == 201
        data2 = res2.json()
        assert data2["name"] == "30-Day Expiring Key"
        assert data2["expires_at"] is not None
        # Check expires_at is roughly 30 days ahead
        exp_dt = datetime.fromisoformat(data2["expires_at"].replace("Z", "+00:00"))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        diff = (exp_dt - now_dt).total_seconds() / 86400
        assert 29 <= diff <= 31

        # 3. Authenticate with valid expiring key -> succeeds
        auth_res = client.get(
            "/api/v1/postcodes/commercial/lookup?state=Lagos",
            headers={"x-api-key": data2["api_key"]},
        )
        assert auth_res.status_code == 200

        # 4. Authenticate with expired key -> HTTP 401
        db.query(ApiKey).filter(ApiKey.id == data2["id"]).update(
            {"expires_at": datetime.now(timezone.utc) - timedelta(days=1)}
        )
        db.commit()

        expired_res = client.get(
            "/api/v1/postcodes/commercial/lookup?state=Lagos",
            headers={"x-api-key": data2["api_key"]},
        )
        assert expired_res.status_code == 401
        assert "expired" in expired_res.json()["detail"].lower()
    finally:
        db.close()


def test_api_key_creation_input_validation():
    """Verify input validation rejecting blank names, negative/zero/excessive quotas, and negative/excessive expiries."""
    merchant_email = f"merchant_val_{secrets.token_hex(6)}@example.com"
    token = get_token(AppRole.MERCHANT, merchant_email)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Blank or whitespace name -> HTTP 422
    res_blank = client.post(
        "/api/v1/api-keys/",
        json={"name": "   ", "monthly_quota": 1000},
        headers=headers,
    )
    assert res_blank.status_code == 422

    # 2. Empty name -> HTTP 422
    res_empty = client.post(
        "/api/v1/api-keys/",
        json={"name": "", "monthly_quota": 1000},
        headers=headers,
    )
    assert res_empty.status_code == 422

    # 3. Zero or negative monthly quota -> HTTP 422
    res_zero_quota = client.post(
        "/api/v1/api-keys/",
        json={"name": "Zero Quota Key", "monthly_quota": 0},
        headers=headers,
    )
    assert res_zero_quota.status_code == 422

    res_neg_quota = client.post(
        "/api/v1/api-keys/",
        json={"name": "Negative Quota Key", "monthly_quota": -500},
        headers=headers,
    )
    assert res_neg_quota.status_code == 422

    # 4. Excessive monthly quota (> 10,000,000) -> HTTP 422
    res_excess_quota = client.post(
        "/api/v1/api-keys/",
        json={"name": "Excess Quota Key", "monthly_quota": 20_000_000},
        headers=headers,
    )
    assert res_excess_quota.status_code == 422

    # 5. Negative or zero expires_in_days -> HTTP 422
    res_neg_exp = client.post(
        "/api/v1/api-keys/",
        json={"name": "Negative Expiry Key", "monthly_quota": 1000, "expires_in_days": -1},
        headers=headers,
    )
    assert res_neg_exp.status_code == 422

    res_zero_exp = client.post(
        "/api/v1/api-keys/",
        json={"name": "Zero Expiry Key", "monthly_quota": 1000, "expires_in_days": 0},
        headers=headers,
    )
    assert res_zero_exp.status_code == 422

    # 6. Excessive expires_in_days (> 365) -> HTTP 422
    res_excess_exp = client.post(
        "/api/v1/api-keys/",
        json={"name": "Excess Expiry Key", "monthly_quota": 1000, "expires_in_days": 400},
        headers=headers,
    )
    assert res_excess_exp.status_code == 422


def test_trusted_proxy_narrowing_and_spoofing_defense():
    """Verify that private network peers are not trusted by default and only explicitly configured proxies are trusted."""
    from backend.app.core.network import get_trusted_client_ip
    from starlette.requests import Request

    # 1. Untrusted private-network peer (e.g. 10.0.0.5 or 192.168.1.100) connecting directly
    # With default empty/narrow trusted proxies, private network peers cannot spoof IP
    scope_private = {
        "type": "http",
        "client": ("10.0.0.5", 48201),
        "headers": [(b"x-forwarded-for", b"203.0.113.195")],
    }
    req_private = Request(scope_private)
    assert get_trusted_client_ip(req_private, trusted_proxies=[]) == "10.0.0.5"

    # Also with default production policy (no broad private ranges)
    scope_192 = {
        "type": "http",
        "client": ("192.168.1.100", 48201),
        "headers": [(b"x-forwarded-for", b"1.1.1.1")],
    }
    assert get_trusted_client_ip(Request(scope_192), trusted_proxies=[]) == "192.168.1.100"

    # 2. Configured specific reverse proxy IP (e.g. dedicated ALB or Nginx reverse proxy at 10.0.1.50)
    scope_configured = {
        "type": "http",
        "client": ("10.0.1.50", 48201),
        "headers": [(b"x-forwarded-for", b"203.0.113.195, 10.0.1.50")],
    }
    req_configured = Request(scope_configured)
    assert get_trusted_client_ip(req_configured, trusted_proxies=["10.0.1.50"]) == "203.0.113.195"

    # 3. Multi-hop chain through configured proxies
    scope_multi = {
        "type": "http",
        "client": ("10.0.1.50", 48201),
        "headers": [(b"x-forwarded-for", b"198.51.100.77, 10.0.1.99, 10.0.1.50")],
    }
    assert get_trusted_client_ip(Request(scope_multi), trusted_proxies=["10.0.1.50", "10.0.1.99"]) == "198.51.100.77"

    # 4. Malformed / injection forwarding headers are safely ignored
    scope_malformed = {
        "type": "http",
        "client": ("10.0.1.50", 48201),
        "headers": [(b"x-forwarded-for", b"malformed_ip_string, <script>alert(1)</script>, 10.0.1.50")],
    }
    assert get_trusted_client_ip(Request(scope_malformed), trusted_proxies=["10.0.1.50"]) == "10.0.1.50"


def test_nipost_upstream_error_sanitization_prevents_leakage():
    """Verify that upstream NIPOST connection exceptions (DNS, timeout, socket) do not leak internal hostnames or details in API responses."""
    from backend.app.services.nipost_client import NIPOSTClient, NIPOSTLookupStatus
    import httpx

    # 1. Direct NIPOSTClient test with connection error containing internal hostname
    client_instance = NIPOSTClient(base_url="https://internal-nipost-cluster.infra.local:9090", timeout=2.0)
    internal_dns_exc = httpx.ConnectError("[Errno 11001] getaddrinfo failed for internal-nipost-cluster.infra.local:9090")

    with patch("httpx.Client.get", side_effect=internal_dns_exc):
        res = client_instance.lookup_postcode("100001")
        assert res.status == NIPOSTLookupStatus.UNAVAILABLE
        assert res.http_status == 503
        # Must NOT contain internal hostname or raw exception details
        assert "internal-nipost-cluster" not in res.error_message
        assert "infra.local" not in res.error_message
        assert "Errno" not in res.error_message
        assert "The official NIPOST verification gateway is temporarily unavailable." in res.error_message

    # 2. Direct NIPOSTClient test with timeout error
    timeout_exc = httpx.TimeoutException("The read operation timed out on socket 10.0.0.99:9090")
    with patch("httpx.Client.get", side_effect=timeout_exc):
        res_timeout = client_instance.lookup_postcode("100001")
        assert res_timeout.status == NIPOSTLookupStatus.UNAVAILABLE
        assert res_timeout.http_status == 504
        assert "10.0.0.99" not in res_timeout.error_message
        assert "The official NIPOST verification gateway timed out." in res_timeout.error_message

    # 3. API endpoint integration test: ensure public JSON response does not leak internal info
    with patch.object(NIPOSTClient, "is_configured", True):
        with patch.object(NIPOSTClient, "lookup_postcode", return_value=res):
            # Normal lookup endpoint (with fallback)
            resp = client.get("/api/v1/postcodes/lookup?code=100001")
            assert resp.status_code == 200
            data = resp.json()
            assert data["fallback_used"] is True
            assert "internal-nipost" not in str(data)
            assert "infra.local" not in str(data)
            assert "Errno" not in str(data)
            assert data["upstream_error"] == "The official NIPOST verification gateway is temporarily unavailable."

            # Strict lookup endpoint (fails closed)
            strict_resp = client.get("/api/v1/postcodes/lookup?code=100001&strict=true")
            assert strict_resp.status_code == 503
            err_detail = strict_resp.json()["detail"]
            assert "internal-nipost" not in err_detail
            assert "infra.local" not in err_detail
            assert "Errno" not in err_detail
            assert "The official NIPOST verification gateway is temporarily unavailable." in err_detail


# ==============================================================================
# 18. Release Gate v6.0.2 Public IP Rate Limiter & Proxy Hardening Tests
# ==============================================================================

def test_client_ip_rate_limiter_production_fail_closed_and_recovery():
    """Verify that check_client_ip_rate_limit enforces fail-closed HTTP 503 in production when Redis fails, allows dev/single-instance fallback, and recovers."""
    from backend.app.core.rate_limiter import check_client_ip_rate_limit
    from fastapi import HTTPException
    import backend.app.core.rate_limiter as rl_mod

    # 1. Production with Redis unavailable & fail-closed enabled -> HTTP 503
    with patch.object(settings, "ENVIRONMENT", "production"):
        with patch.object(settings, "RATE_LIMIT_REDIS_FAIL_CLOSED", True):
            with patch.object(settings, "ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", False):
                with patch.object(rl_mod, "_get_redis_client", return_value=None):
                    with pytest.raises(HTTPException) as exc_info:
                        check_client_ip_rate_limit("198.51.100.99", limit_per_minute=10)
                    assert exc_info.value.status_code == 503
                    assert "temporarily unavailable" in exc_info.value.detail.lower()

    # 2. Production with explicit single-instance opt-out (ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION=True) -> succeeds with in-memory fallback
    with patch.object(settings, "ENVIRONMENT", "production"):
        with patch.object(settings, "RATE_LIMIT_REDIS_FAIL_CLOSED", True):
            with patch.object(settings, "ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", True):
                with patch.object(rl_mod, "_get_redis_client", return_value=None):
                    check_client_ip_rate_limit("198.51.100.99", limit_per_minute=10)

    # 3. Development environment with Redis unavailable -> succeeds with in-memory fallback
    with patch.object(settings, "ENVIRONMENT", "development"):
        with patch.object(rl_mod, "_get_redis_client", return_value=None):
            check_client_ip_rate_limit("198.51.100.99", limit_per_minute=10)

    # 4. Redis recovery: when Redis is available, shared Redis limiting resumes
    mock_redis = MagicMock()
    mock_redis.eval.return_value = [1, 1, 0]
    with patch.object(settings, "ENVIRONMENT", "production"):
        with patch.object(rl_mod, "_get_redis_client", return_value=mock_redis):
            check_client_ip_rate_limit("198.51.100.99", limit_per_minute=10)
            mock_redis.eval.assert_called_once()


def test_proxy_chain_all_trusted_falls_back_to_direct_peer():
    """Verify that when every address in X-Forwarded-For is a trusted proxy, get_trusted_client_ip falls back to direct_ip."""
    from backend.app.core.network import get_trusted_client_ip
    from starlette.requests import Request

    trusted_proxies = ["10.0.1.50", "10.0.1.99"]

    # Direct peer is a trusted proxy, and X-Forwarded-For contains only trusted proxies
    scope_all_trusted = {
        "type": "http",
        "client": ("10.0.1.50", 48201),
        "headers": [(b"x-forwarded-for", b"10.0.1.99, 10.0.1.50")],
    }
    req = Request(scope_all_trusted)
    # Must NOT return 10.0.1.99; must fall back to direct peer 10.0.1.50
    assert get_trusted_client_ip(req, trusted_proxies=trusted_proxies) == "10.0.1.50"


def test_nipost_address_and_autofill_logging_masks_sensitive_data():
    """Verify that address validation and autofill methods do not log customer addresses or raw exceptions when timeouts or errors occur."""
    from backend.app.services.nipost_client import NIPOSTClient
    import logging

    client_instance = NIPOSTClient(base_url="https://nipost-test.ng", api_key="test_key", timeout=1.0)

    with patch("httpx.Client.post", side_effect=Exception("Internal upstream exception details")):
        with patch.object(logging.getLogger("nipost_client"), "warning") as mock_warn:
            res = client_instance.validate_address("Plot 99 Sensitive Street, Victoria Island, Lagos", "Lagos", "Victoria Island")
            assert res is None
            mock_warn.assert_called_once()
            log_msg = str(mock_warn.call_args[0][0])
            assert "Plot 99" not in log_msg
            assert "Sensitive Street" not in log_msg
            assert "Internal upstream exception details" not in log_msg
            assert "connection error during address validation" in log_msg.lower()

    with patch("httpx.Client.get", side_effect=Exception("Internal autofill socket failure")):
        with patch.object(logging.getLogger("nipost_client"), "warning") as mock_warn_autofill:
            res_auto = client_instance.autofill_postcode("Victoria Island", "Lagos")
            assert res_auto is None
            mock_warn_autofill.assert_called_once()
            log_msg_auto = str(mock_warn_autofill.call_args[0][0])
            assert "Internal autofill socket failure" not in log_msg_auto
            assert "postcode autofill query" in log_msg_auto.lower()



