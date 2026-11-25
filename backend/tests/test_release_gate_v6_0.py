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
            SECRET_KEY="k7J9mP2vL4xR8zN1qT5wY3bC6dF0gH2jM",
            OUTBOX_ENCRYPTION_KEY="wY3bC6dF0gH2jMk7J9mP2vL4xR8zN1qT5",
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

    # 2. Wait up to 10 seconds for heartbeat in database
    db = SessionLocal()
    hb = None
    try:
        for _ in range(50):
            time.sleep(0.2)
            db.rollback()
            hb = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
            if hb:
                break

        assert hb is not None, "Worker subprocess did not write heartbeat to database within 10 seconds!"
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

    tracking_token = secrets.token_urlsafe(24)
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
            environment="test",
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
            environment="test",
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
            environment="test",
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
        mock_client.upstream_environment = "production"

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
        assert res3.is_live_nipost is False
        assert res3.upstream_contacted is True
        assert res3.postcode_exists is False
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
        assert data1["api_key"].startswith(("pl_test_", "pl_live_"))

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
    orch_err_res = (
        NIPOSTLookupStatus.UNAVAILABLE,
        None,
        "The official NIPOST verification gateway is temporarily unavailable.",
        "failed",
    )
    with patch.object(NIPOSTClient, "is_configured", True):
        with patch.object(NIPOSTClient, "lookup_postcode", return_value=res), \
             patch.object(NIPOSTClient, "validate_postcode", return_value=res), \
             patch.object(NIPOSTClient, "orchestrated_verify", return_value=orch_err_res):
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


# ==============================================================================
# 19. Release Gate v6.0.3 Redis Log Sanitization, NIPOST Official Contract & Rate Limiter Health Tests
# ==============================================================================

def test_redis_credential_sanitization_in_success_and_failure_logs():
    """Verify that Redis credentials (username, password) are strictly masked and never appear in application logs under connection success or failure."""
    import logging
    from backend.app.core.rate_limiter import _sanitize_redis_url, _get_redis_client
    import backend.app.core.rate_limiter as rl_mod

    canary_password = "CanarySecretP@ssword123!"
    raw_redis_url = f"redis://app_user:{canary_password}@127.0.0.1:6379/2"

    # 1. Direct unit verification of _sanitize_redis_url
    sanitized = _sanitize_redis_url(raw_redis_url)
    assert canary_password not in sanitized
    assert "app_user" not in sanitized
    assert "***:***@127.0.0.1:6379/2" in sanitized
    assert _sanitize_redis_url(f"redis://:{canary_password}@redis.cluster.local:6379/0") == "redis://***:***@redis.cluster.local:6379/0"
    assert _sanitize_redis_url("redis://localhost:6379/0") == "redis://localhost:6379/0"
    assert _sanitize_redis_url(None) == "unconfigured"

    # 2. Connection success log test
    rl_logger = logging.getLogger("rate_limiter")
    with patch.object(settings, "REDIS_URL", raw_redis_url):
        with patch.object(rl_mod, "_REDIS_CLIENT", None):
            with patch.object(rl_mod, "_LAST_CONNECT_ATTEMPT", 0.0):
                mock_client = MagicMock()
                with patch("redis.from_url", return_value=mock_client):
                    with patch.object(rl_logger, "info") as mock_info:
                        client_res = _get_redis_client()
                        assert client_res is mock_client
                        mock_info.assert_called_once()
                        success_log = str(mock_info.call_args[0][0])
                        assert canary_password not in success_log
                        assert "app_user" not in success_log
                        assert "redis://127.0.0.1:6379" in success_log

    # 3. Connection failure log test
    with patch.object(settings, "REDIS_URL", raw_redis_url):
        with patch.object(rl_mod, "_REDIS_CLIENT", None):
            with patch.object(rl_mod, "_LAST_CONNECT_ATTEMPT", 0.0):
                err_with_secret = Exception(f"Connection refused to {raw_redis_url}")
                with patch("redis.from_url", side_effect=err_with_secret):
                    with patch.object(rl_logger, "warning") as mock_warn:
                        client_fail = _get_redis_client()
                        assert client_fail is None
                        mock_warn.assert_called_once()
                        fail_log = str(mock_warn.call_args[0][0])
                        assert canary_password not in fail_log
                        assert "app_user" not in fail_log
                        assert "Exception" in fail_log


def test_nipost_official_contract_adapter_and_graded_lookup():
    """Verify that NIPOSTClient correctly adapts the official NIPOST developer lookup schema (/v1/lookup)."""
    import httpx
    from backend.app.services.nipost_client import NIPOSTClient, NIPOSTLookupStatus

    # 1. Official schema: /v1/lookup with valid=True, administrative_address object, recent_house_address
    captured_requests = []
    def official_lookup_handler(req: httpx.Request):
        captured_requests.append(req)
        return httpx.Response(
            200,
            json={
                "postcode": "100001",
                "valid": True,
                "administrative_address": {
                    "state": "Lagos",
                    "lga": "Lagos Island",
                    "district": "Marina",
                    "area": "Marina",
                },
                "recent_house_address": "12 Broad Street, Marina",
                "dataset_version": "2026.1",
            },
            headers={"content-type": "application/json"}
        )

    client_official = NIPOSTClient(
        base_url="https://api.nipost.gov.ng",
        api_key="nipost_official_key",
        lookup_path="/v1/lookup",
        transport=httpx.MockTransport(official_lookup_handler),
    )

    res = client_official.lookup_postcode("100001")
    assert res.status == NIPOSTLookupStatus.FOUND
    assert res.is_found is True
    assert res["code"] == "100001"
    assert res["area"] == "Marina"
    assert res["state"] == "Lagos"
    assert res["lga"] == "Lagos Island"
    assert res["building_reference"] == "12 Broad Street, Marina"
    assert res["recent_house_address"] == "12 Broad Street, Marina"
    assert res["dataset_version"] == "2026.1"

    # Verify request path and query parameters
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.url.path == "/v1/lookup"
    assert "postcode=100001" in str(req.url) or "code=100001" in str(req.url)

    # 2. Official schema: valid=False (authoritative not found)
    def official_invalid_handler(req: httpx.Request):
        return httpx.Response(
            200,
            json={
                "postcode": "999999",
                "valid": False,
                "message": "Postcode not found in national directory",
                "dataset_version": "2026.1",
            },
            headers={"content-type": "application/json"}
        )

    client_invalid = NIPOSTClient(
        base_url="https://api.nipost.gov.ng",
        api_key="nipost_official_key",
        lookup_path="/v1/lookup",
        transport=httpx.MockTransport(official_invalid_handler),
    )
    res_invalid = client_invalid.lookup_postcode("999999")
    assert res_invalid.status == NIPOSTLookupStatus.NOT_FOUND
    assert res_invalid.is_found is False

    # 3. String-based administrative_address parsing fallback
    def flat_admin_handler(req: httpx.Request):
        return httpx.Response(
            200,
            json={
                "postcode": "FC-02-A09-DB-09",
                "valid": True,
                "administrative_address": "Garki Area 2, Municipal, Abuja (FCT)",
                "recent_house_address": "Federal Commerce House",
            },
            headers={"content-type": "application/json"}
        )

    client_flat = NIPOSTClient(
        base_url="https://api.nipost.gov.ng",
        lookup_path="/v1/lookup",
        transport=httpx.MockTransport(flat_admin_handler),
    )
    res_flat = client_flat.lookup_postcode("FC-02-A09-DB-09")
    assert res_flat.status == NIPOSTLookupStatus.FOUND
    assert res_flat["area"] == "Garki Area 2"
    assert res_flat["state"] == "Abuja (FCT)"
    assert res_flat["lga"] == "Municipal"
    assert res_flat["building_reference"] == "Federal Commerce House"


def test_nipost_route_404_vs_authoritative_not_found_discrimination():
    """Verify that an HTTP 404 from an invalid endpoint route / reverse proxy cannot be mistaken for genuine postcode non-existence."""
    import httpx
    from backend.app.services.nipost_client import NIPOSTClient, NIPOSTLookupStatus
    from backend.app.routers.postcodes import get_nipost_client

    # 1. Reverse proxy / nginx HTML 404 (route error)
    html_404_transport = httpx.MockTransport(
        lambda req: httpx.Response(
            404,
            text="<html><head><title>404 Not Found</title></head><body><h1>404 Not Found</h1>nginx/1.24.0</body></html>",
            headers={"content-type": "text/html"},
        )
    )
    client_route_err = NIPOSTClient(
        base_url="https://misconfigured-nipost.gateway.internal",
        lookup_path="/invalid/route/lookup",
        transport=html_404_transport,
    )

    res_route = client_route_err.lookup_postcode("100001")
    # Must NOT be classified as NOT_FOUND (postcode does not exist)
    assert res_route.status == NIPOSTLookupStatus.UNAVAILABLE
    assert res_route.http_status == 404
    assert "routing error" in res_route.error_message.lower()

    # Route-level verification: in strict mode, routing 404 returns HTTP 503, NOT not_found
    app.dependency_overrides[get_nipost_client] = lambda: client_route_err
    try:
        strict_resp = client.get("/api/v1/postcodes/lookup?code=100001&strict=true")
        assert strict_resp.status_code == 503
        assert "routing error" in strict_resp.json()["detail"].lower()

        # In non-strict mode, falls back to local reference data (provenance indicates fallback)
        non_strict_resp = client.get("/api/v1/postcodes/lookup?code=100001")
        assert non_strict_resp.status_code == 200
        data = non_strict_resp.json()
        assert data["fallback_used"] is True
        assert "routing error" in data["fallback_reason"].lower()
    finally:
        app.dependency_overrides.pop(get_nipost_client, None)

    # 2. Authoritative JSON 404 with confirmed postcode search payload
    confirmed_404_transport = httpx.MockTransport(
        lambda req: httpx.Response(
            404,
            json={"postcode": "999999", "valid": False, "error": "postcode_not_found"},
            headers={"content-type": "application/json"},
        )
    )
    client_confirmed_404 = NIPOSTClient(
        base_url="https://api.nipost.gov.ng",
        transport=confirmed_404_transport,
    )
    res_confirmed = client_confirmed_404.lookup_postcode("999999")
    assert res_confirmed.status == NIPOSTLookupStatus.NOT_FOUND
    assert res_confirmed.http_status == 404


def test_nipost_lookup_logging_omits_response_body_and_raw_exception():
    """Verify that lookup_postcode logs do not expose upstream response bodies, internal exceptions, or full postcodes."""
    import logging
    import httpx
    from backend.app.services.nipost_client import NIPOSTClient

    nipost_logger = logging.getLogger("nipost_client")

    # 1. Non-200 response with sensitive internal payload
    sensitive_body = "Internal Trace: SELECT * FROM sensitive_customer_data WHERE code='100001'"
    bad_resp_transport = httpx.MockTransport(
        lambda req: httpx.Response(
            500,
            text=sensitive_body,
            headers={"content-type": "text/plain"},
        )
    )
    client_500 = NIPOSTClient(
        base_url="https://api.nipost.gov.ng",
        transport=bad_resp_transport,
    )

    with patch.object(nipost_logger, "warning") as mock_warn:
        res = client_500.lookup_postcode("100001")
        assert res.http_status == 500
        mock_warn.assert_called_once()
        log_msg = str(mock_warn.call_args[0][0])
        assert sensitive_body not in log_msg
        assert "sensitive_customer_data" not in log_msg
        assert "non-200 response (500)" in log_msg

    # 2. Connection exception with internal network details
    internal_socket_error = httpx.ConnectError("Socket error connecting to 10.240.12.88:9999 [Errno 111]")
    client_err = NIPOSTClient(base_url="https://internal-nipost.node:9999")
    with patch("httpx.Client.get", side_effect=internal_socket_error):
        with patch.object(nipost_logger, "warning") as mock_warn_conn:
            res_conn = client_err.lookup_postcode("100001")
            assert res_conn.http_status == 503
            mock_warn_conn.assert_called_once()
            conn_log = str(mock_warn_conn.call_args[0][0])
            assert "10.240.12.88" not in conn_log
            assert "Errno 111" not in conn_log
            assert "ConnectError" in conn_log


def test_in_memory_public_ip_rate_limiter_cleans_expired_entries():
    """Verify that in-memory fallback rate limiting cleans up expired IP entries and enforces bounded memory."""
    import backend.app.core.rate_limiter as rl_mod
    from backend.app.core.rate_limiter import (
        check_client_ip_rate_limit,
        get_rate_limiter_status,
        reset_api_key_rate_limits,
    )

    reset_api_key_rate_limits()

    # Simulate 50 unique client IPs calling the endpoint at t = 1000.0
    simulated_now = 1000.0
    with patch.object(rl_mod, "_get_redis_client", return_value=None):
        with patch("time.time", return_value=simulated_now):
            for i in range(50):
                check_client_ip_rate_limit(f"192.0.2.{i}", limit_per_minute=10)

        status_initial = get_rate_limiter_status()
        assert status_initial["in_memory_active_ip_buckets"] == 50

        # Advance time by 65 seconds (all timestamps in window are now expired)
        future_time = simulated_now + 65.0
        with patch("time.time", return_value=future_time):
            with rl_mod._LOCK:
                rl_mod._cleanup_expired_in_memory_windows(future_time, window_seconds=60.0, force=True)

            status_cleaned = get_rate_limiter_status()
            assert status_cleaned["in_memory_active_ip_buckets"] == 0
            assert status_cleaned["in_memory_active_keys"] == 0


def test_rate_limiter_health_status_distinguishes_fail_closed_from_in_memory():
    """Verify that get_rate_limiter_status and /health/rate-limiter accurately distinguish redis, unavailable_fail_closed, and in_memory_fallback."""
    import backend.app.core.rate_limiter as rl_mod
    from backend.app.core.rate_limiter import get_rate_limiter_status

    # 1. Connected to Redis
    mock_redis = MagicMock()
    with patch.object(rl_mod, "_get_redis_client", return_value=mock_redis):
        status_redis = get_rate_limiter_status()
        assert status_redis["backend"] == "redis"
        assert status_redis["redis_connected"] is True
        assert status_redis["alert_fail_closed"] is False

    # 2. Production with Redis unavailable & fail-closed enabled -> unavailable_fail_closed
    with patch.object(settings, "ENVIRONMENT", "production"):
        with patch.object(settings, "RATE_LIMIT_REDIS_FAIL_CLOSED", True):
            with patch.object(settings, "ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", False):
                with patch.object(rl_mod, "_get_redis_client", return_value=None):
                    status_fc = get_rate_limiter_status()
                    assert status_fc["backend"] == "unavailable_fail_closed"
                    assert status_fc["redis_connected"] is False
                    assert status_fc["alert_fail_closed"] is True
                    assert status_fc["alert_in_memory_fallback"] is False

                    # Endpoint verification
                    resp = client.get("/health/rate-limiter")
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["backend"] == "unavailable_fail_closed"
                    assert data["alert_fail_closed"] is True

    # 3. Development with Redis unavailable -> in_memory_fallback
    with patch.object(settings, "ENVIRONMENT", "development"):
        with patch.object(rl_mod, "_get_redis_client", return_value=None):
            status_dev = get_rate_limiter_status()
            assert status_dev["backend"] == "in_memory_fallback"
            assert status_dev["alert_fail_closed"] is False


def test_redis_runtime_lua_operations_sanitize_exceptions():
    """Verify that runtime Redis Lua failures in API-key and public-IP rate limiters log only error categories without credentials."""
    import logging
    from backend.app.core.rate_limiter import check_api_key_rate_limit, check_client_ip_rate_limit
    import backend.app.core.rate_limiter as rl_mod

    rl_logger = logging.getLogger("rate_limiter")
    sensitive_detail = "AUTH failed on redis://admin:SecretPass123!@cache.internal:6379"

    # 1. API key rate limiter Lua exception
    mock_redis = MagicMock()
    mock_redis.eval.side_effect = RuntimeError(sensitive_detail)
    with patch.object(rl_mod, "_get_redis_client", return_value=mock_redis):
        with patch.object(rl_logger, "warning") as mock_warn:
            # dev environment to allow fallback after redis failure
            with patch.object(settings, "ENVIRONMENT", "development"):
                check_api_key_rate_limit("test_key_1", limit_per_minute=60)
            mock_warn.assert_called()
            log_str = " ".join([str(call[0][0]) % call[0][1:] if len(call[0]) > 1 else str(call[0][0]) for call in mock_warn.call_args_list])
            assert "RuntimeError" in log_str
            assert "SecretPass123!" not in log_str
            assert "cache.internal" not in log_str

    # 2. Public IP rate limiter Lua exception
    mock_redis_ip = MagicMock()
    mock_redis_ip.eval.side_effect = RuntimeError(sensitive_detail)
    with patch.object(rl_mod, "_get_redis_client", return_value=mock_redis_ip):
        with patch.object(rl_logger, "warning") as mock_warn_ip:
            with patch.object(settings, "ENVIRONMENT", "development"):
                check_client_ip_rate_limit("198.51.100.88", limit_per_minute=15)
            mock_warn_ip.assert_called()
            log_str_ip = " ".join([str(call[0][0]) % call[0][1:] if len(call[0]) > 1 else str(call[0][0]) for call in mock_warn_ip.call_args_list])
            assert "RuntimeError" in log_str_ip
            assert "SecretPass123!" not in log_str_ip
            assert "cache.internal" not in log_str_ip


def test_in_memory_rate_limiter_hard_bounded_capacity():
    """Verify that in-memory storage strictly enforces MAX_IN_MEMORY_KEYS under high cardinality traffic."""
    import backend.app.core.rate_limiter as rl_mod
    from backend.app.core.rate_limiter import (
        check_client_ip_rate_limit,
        reset_api_key_rate_limits,
        MAX_IN_MEMORY_KEYS,
    )

    reset_api_key_rate_limits()

    # Test with patched small limit to verify eviction boundary
    test_cap = 50
    with patch.object(rl_mod, "MAX_IN_MEMORY_KEYS", test_cap):
        with patch.object(rl_mod, "_get_redis_client", return_value=None):
            with patch.object(settings, "ENVIRONMENT", "development"):
                # Insert 120 unique IPs
                for i in range(120):
                    check_client_ip_rate_limit(f"198.51.100.{i}", limit_per_minute=10)

                with rl_mod._LOCK:
                    assert len(rl_mod._KEY_REQUEST_WINDOWS) <= test_cap

    reset_api_key_rate_limits()


def test_nipost_404_generic_json_and_html_classified_as_unavailable():
    """Verify that generic 404 responses (JSON {"detail": "Not Found"} or HTML) are strictly classified as UNAVAILABLE route errors, never falsely rejecting valid postcodes as non-existent."""
    import httpx
    from backend.app.services.nipost_client import NIPOSTClient, NIPOSTLookupStatus

    # 1. Standard FastAPI / Starlette generic 404: {"detail": "Not Found"}
    fastapi_404 = httpx.MockTransport(
        lambda req: httpx.Response(404, json={"detail": "Not Found"}, headers={"content-type": "application/json"})
    )
    client_fastapi = NIPOSTClient(base_url="https://api.nipost.test", transport=fastapi_404)
    res_fastapi = client_fastapi.lookup_postcode("100001")
    assert res_fastapi.status == NIPOSTLookupStatus.UNAVAILABLE
    assert res_fastapi.http_status == 404
    assert "routing error" in res_fastapi.error_message.lower()

    # 2. Generic API gateway message: {"message": "Not Found"}
    gw_404 = httpx.MockTransport(
        lambda req: httpx.Response(404, json={"message": "Not Found"}, headers={"content-type": "application/json"})
    )
    client_gw = NIPOSTClient(base_url="https://api.nipost.test", transport=gw_404)
    res_gw = client_gw.lookup_postcode("100001")
    assert res_gw.status == NIPOSTLookupStatus.UNAVAILABLE

    # 3. Generic resource not found: {"error": "Resource not found"}
    res_err_404 = httpx.MockTransport(
        lambda req: httpx.Response(404, json={"error": "Resource not found"}, headers={"content-type": "application/json"})
    )
    client_res_err = NIPOSTClient(base_url="https://api.nipost.test", transport=res_err_404)
    res_rerr = client_res_err.lookup_postcode("100001")
    assert res_rerr.status == NIPOSTLookupStatus.UNAVAILABLE

    # 4. Empty body 404
    empty_404 = httpx.MockTransport(
        lambda req: httpx.Response(404, text="", headers={"content-type": "application/json"})
    )
    client_empty = NIPOSTClient(base_url="https://api.nipost.test", transport=empty_404)
    res_empty = client_empty.lookup_postcode("100001")
    assert res_empty.status == NIPOSTLookupStatus.UNAVAILABLE

    # 5. Documented NIPOST explicit postcode-not-found schema
    doc_404 = httpx.MockTransport(
        lambda req: httpx.Response(
            404,
            json={
                "postcode": "100001",
                "valid": False,
                "error_code": "POSTCODE_NOT_FOUND",
                "message": "Postcode not found in national directory",
            },
            headers={"content-type": "application/json"},
        )
    )
    client_doc = NIPOSTClient(base_url="https://api.nipost.test", transport=doc_404)
    res_doc = client_doc.lookup_postcode("100001")
    assert res_doc.status == NIPOSTLookupStatus.NOT_FOUND
    assert res_doc.http_status == 404


def test_nipost_invalid_input_separated_from_not_found():
    """Verify that formatting/syntax errors are classified as INVALID_INPUT, strictly distinct from directory NOT_FOUND."""
    import httpx
    from backend.app.services.nipost_client import NIPOSTClient, NIPOSTLookupStatus
    from backend.app.routers.postcodes import get_nipost_client

    # 1. 200 payload with INVALID_FORMAT status
    inv_format_transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json={"status": "INVALID_FORMAT", "message": "Invalid postcode format: must be 6 numeric digits"},
            headers={"content-type": "application/json"},
        )
    )
    client_inv = NIPOSTClient(base_url="https://api.nipost.test", transport=inv_format_transport)
    res_inv = client_inv.lookup_postcode("12-ABC")
    assert res_inv.status == NIPOSTLookupStatus.INVALID_INPUT
    assert res_inv.status != NIPOSTLookupStatus.NOT_FOUND

    # 2. Upstream 400 Bad Request / 422 Unprocessable Content returns INVALID_INPUT
    val_err_transport = httpx.MockTransport(
        lambda req: httpx.Response(422, json={"detail": "Invalid postcode syntax"}, headers={"content-type": "application/json"})
    )
    client_val_err = NIPOSTClient(base_url="https://api.nipost.test", transport=val_err_transport)
    res_val_err = client_val_err.lookup_postcode("INVALID_LEN_999999999")
    assert res_val_err.status == NIPOSTLookupStatus.INVALID_INPUT

    # 3. Route integration: strict mode raises HTTP 422 Unprocessable Content / 400 on INVALID_INPUT
    app.dependency_overrides[get_nipost_client] = lambda: client_val_err
    try:
        strict_resp = client.get("/api/v1/postcodes/lookup?code=INVALID_LEN_999999999&strict=true")
        assert strict_resp.status_code in (400, 422)
        detail_msg = strict_resp.json()["detail"].lower()
        assert any(k in detail_msg for k in ("invalid", "validation error", "invalid_input"))
    finally:
        app.dependency_overrides.pop(get_nipost_client, None)


def test_nipost_request_contract_parameter_and_authentication_headers():
    """Verify that NIPOST client requests use verified contract parameters without spraying dual headers or duplicate keys by default."""
    import httpx
    from backend.app.services.nipost_client import NIPOSTClient

    captured_requests = []
    def spy_transport(req: httpx.Request):
        captured_requests.append(req)
        return httpx.Response(
            200,
            json={
                "code": "100001",
                "area": "Marina",
                "state": "Lagos",
                "valid": True,
            },
            headers={"content-type": "application/json"},
        )

    # Default contract: Bearer auth and single 'code' parameter
    client_default = NIPOSTClient(
        base_url="https://api.nipost.test",
        api_key="secret-bearer-token",
        auth_scheme="bearer",
        query_param="code",
        transport=httpx.MockTransport(spy_transport),
    )
    client_default.lookup_postcode("100001")
    assert len(captured_requests) == 1
    req = captured_requests[0]

    # Verify headers: Bearer authorization only, no redundant x-api-key
    assert req.headers["Authorization"] == "Bearer secret-bearer-token"
    assert "x-api-key" not in req.headers

    # Verify query parameters: exact 'code' parameter only, no duplicate 'postcode'
    query_str = str(req.url.query, "utf-8") if isinstance(req.url.query, bytes) else str(req.url.query)
    assert "code=100001" in query_str
    assert "postcode=" not in query_str

    # Alternative contract: 'postcode' param and 'x-api-key' header
    captured_requests.clear()
    client_alt = NIPOSTClient(
        base_url="https://api.nipost.test",
        api_key="api-key-value",
        auth_scheme="api_key",
        query_param="postcode",
        transport=httpx.MockTransport(spy_transport),
    )
    client_alt.lookup_postcode("100001")
    assert len(captured_requests) == 1
    req_alt = captured_requests[0]
    assert req_alt.headers.get("x-api-key") == "api-key-value"
    assert "Authorization" not in req_alt.headers
    params_alt = dict(req_alt.url.params)
    assert "postcode" in params_alt and params_alt["postcode"] == "100001"
    assert "code" not in params_alt


def test_redis_username_never_exposed_in_diagnostics():
    """Verify that Redis ACL usernames are strictly omitted from logs, safe endpoint representations, and health telemetry."""
    import logging
    import backend.app.core.rate_limiter as rl_mod
    from backend.app.core.rate_limiter import _safe_redis_endpoint, _get_redis_client, get_rate_limiter_status

    sensitive_user = "infra_sec_admin"
    sensitive_pass = "P@ssw0rd999!SuperSecret"
    acl_redis_url = f"rediss://{sensitive_user}:{sensitive_pass}@cache-primary.internal.vpc:6380/3?ssl_cert_reqs=required"

    # 1. Verify safe endpoint helper
    endpoint = _safe_redis_endpoint(acl_redis_url)
    assert endpoint == "rediss://cache-primary.internal.vpc:6380"
    assert sensitive_user not in endpoint
    assert sensitive_pass not in endpoint
    assert "/3" not in endpoint

    # 2. Verify health telemetry endpoint field
    with patch.object(settings, "REDIS_URL", acl_redis_url):
        with patch.object(rl_mod, "_get_redis_client", return_value=MagicMock()):
            health_status = get_rate_limiter_status()
            assert health_status["redis_endpoint"] == "rediss://cache-primary.internal.vpc:6380"
            assert sensitive_user not in str(health_status)
            assert sensitive_pass not in str(health_status)

    # 3. Verify connection log
    rl_logger = logging.getLogger("rate_limiter")
    with patch.object(settings, "REDIS_URL", acl_redis_url):
        with patch.object(rl_mod, "_REDIS_CLIENT", None):
            with patch.object(rl_mod, "_LAST_CONNECT_ATTEMPT", 0.0):
                mock_redis_client = MagicMock()
                with patch("redis.from_url", return_value=mock_redis_client):
                    with patch.object(rl_logger, "info") as mock_info:
                        _get_redis_client()
                        mock_info.assert_called_once()
                        success_log = str(mock_info.call_args[0][0])
                        assert sensitive_user not in success_log
                        assert sensitive_pass not in success_log
                        assert "rediss://cache-primary.internal.vpc:6380" in success_log


def test_in_memory_rate_limiter_concurrency_at_capacity_boundary():
    """Verify thread-safety and bounded capacity when multiple threads concurrently insert unique keys at the MAX_IN_MEMORY_KEYS limit."""
    import threading
    import backend.app.core.rate_limiter as rl_mod
    from backend.app.core.rate_limiter import check_client_ip_rate_limit, reset_api_key_rate_limits

    reset_api_key_rate_limits()
    test_capacity = 40
    thread_count = 10
    requests_per_thread = 25
    exceptions = []

    def worker_task(thread_id: int):
        try:
            for req_idx in range(requests_per_thread):
                unique_ip = f"192.0.2.{thread_id}_{req_idx}"
                check_client_ip_rate_limit(unique_ip, limit_per_minute=20)
        except Exception as exc:
            exceptions.append(exc)

    with patch.object(rl_mod, "MAX_IN_MEMORY_KEYS", test_capacity):
        with patch.object(rl_mod, "_get_redis_client", return_value=None):
            with patch.object(settings, "ENVIRONMENT", "development"):
                threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(thread_count)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

    assert exceptions == [], f"Concurrent rate limit operations raised unexpected exceptions: {exceptions}"
    with rl_mod._LOCK:
        assert len(rl_mod._KEY_REQUEST_WINDOWS) <= test_capacity

    reset_api_key_rate_limits()


def test_commercial_api_quota_atomic_concurrency_reconciliation():
    """Verify that concurrent requests with an active commercial API key atomically debit quota without double-metering or race-condition over-subscription."""
    import threading
    from backend.app.database import SessionLocal
    from backend.app.models.api_key import ApiKey
    from backend.app.routers.api_keys import get_api_key_merchant

    # 1. Create merchant and an API key with exactly 5 quota units
    merchant_email = f"merchant_reconcile_{secrets.token_hex(6)}@example.com"
    token = get_token(AppRole.MERCHANT, merchant_email)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post(
        "/api/v1/api-keys/",
        json={"name": "Concurrency Test Key", "monthly_quota": 5},
        headers=headers,
    )
    assert res.status_code == 201
    key_data = res.json()
    raw_key = key_data["api_key"]
    key_id = key_data["id"]

    success_count = 0
    quota_exhausted_count = 0
    other_errors = []
    lock = threading.Lock()

    def concurrent_caller():
        nonlocal success_count, quota_exhausted_count
        try:
            worker_db = SessionLocal()
            try:
                get_api_key_merchant(x_api_key=raw_key, db=worker_db)
                with lock:
                    success_count += 1
            except HTTPException as http_exc:
                if http_exc.status_code == 429:
                    with lock:
                        quota_exhausted_count += 1
                else:
                    with lock:
                        other_errors.append(f"HTTP_{http_exc.status_code}_{http_exc.detail}")
            except Exception as e:
                with lock:
                    other_errors.append(str(e))
            finally:
                worker_db.close()
        except Exception as outer_e:
            with lock:
                other_errors.append(str(outer_e))

    # Spawn 12 concurrent requests for a quota of 5
    threads = [threading.Thread(target=concurrent_caller) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert other_errors == [], f"Unexpected errors during concurrent quota calls: {other_errors}"
    assert success_count == 5, f"Expected exactly 5 successful quota debits, got {success_count}"
    assert quota_exhausted_count == 7, f"Expected exactly 7 rejected requests (HTTP 429), got {quota_exhausted_count}"

    # Verify database state has exact period_usage_count == 5
    verify_db = SessionLocal()
    try:
        saved_key = verify_db.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert saved_key.period_usage_count == 5
    finally:
        verify_db.close()






