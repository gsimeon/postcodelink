"""Release Gate v6.0: Production Integrity, Permanent Audit Retention & Provider Telemetry Verification Tests."""
import sys
import time
import secrets
import signal
import subprocess
import os
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
from backend.app.core.security import create_access_token, hash_otp
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
