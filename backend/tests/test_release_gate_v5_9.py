"""Release Gate v5.9: Cryptographic Audit Integrity, Live Provider Telemetry & Distributed Resilience Tests."""
import uuid
import time
import secrets
import asyncio
import threading
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, StatementError

from backend.app.main import app
from backend.app.database import SessionLocal, engine
from backend.app.models.profile import Profile
from backend.app.models.api_key import ApiKey
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
    get_rate_limiter_status,
    _get_redis_client,
)
from backend.app.services.delivery_service import (
    process_notification_outbox,
    record_worker_heartbeat,
    record_worker_shutdown,
)
from backend.app.workers.outbox_worker import run_outbox_worker_loop
from backend.app.config import Settings, settings

client = TestClient(app)


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


def get_token(role: AppRole = AppRole.MERCHANT, email: str = "v59_merchant@test.ng") -> str:
    db = SessionLocal()
    try:
        user = db.query(Profile).filter(Profile.email == email).first()
        if not user:
            user = Profile(
                id=str(uuid.uuid4()),
                email=email,
                role=role,
                full_name=f"Test {role.value}",
                hashed_password="hashed_test_password",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return create_access_token({"sub": user.id, "role": user.role.value})
    finally:
        db.close()


# ==============================================================================
# 1. P1: Provider Telemetry Verification in Reconciliation
# ==============================================================================
def test_provider_verified_reconciliation_validates_actual_provider():
    """Verify that provider_telemetry_verified contacts the provider and rejects fabricated IDs."""
    admin_token = get_token(AppRole.ADMIN, "v59_recon_admin@test.ng")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    db = SessionLocal()
    delivery_id = f"PL-RECON-V59-{secrets.token_hex(4)}"
    outbox_id = None
    try:
        delivery = Delivery(
            id=delivery_id,
            recipient_phone="+2348011223344",
            recipient_name="Recon Test Customer",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="10 Marina St",
            package_description="Telemetry Test",
            postcode_input="100271",
            status=DeliveryStatus.OUT_FOR_DELIVERY,
            otp_hash=hash_otp("123456"),
            tracking_token=f"token_{secrets.token_hex(16)}",
        )
        db.add(delivery)
        db.commit()

        outbox_item = NotificationOutbox(
            delivery_id=delivery.id,
            notification_type="otp_delivery_pin",
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            provider="termii",
            status=NotificationDeliveryStatus.RECONCILIATION_REQUIRED,
            idempotency_key=f"recon_key_v59_{secrets.token_hex(4)}",
            retry_count=2,
        )
        db.add(outbox_item)
        db.commit()
        db.refresh(outbox_item)
        outbox_id = outbox_item.id

        # 1. Fabricated provider message ID must be REJECTED (HTTP 422)
        with patch("httpx.get", return_value=MagicMock(status_code=404, json=lambda: {})):
            fake_resp = client.post(
                f"/api/v1/deliveries/outbox/{outbox_id}/reconcile",
                json={
                    "resolution": "mark_sent",
                    "evidence_type": "provider_telemetry_verified",
                    "provider_message_id": "FABRICATED_MESSAGE_ID_9999",
                    "reason": "Operator claims carrier verified without real record",
                },
                headers=admin_headers,
            )
        assert fake_resp.status_code == 422
        assert "could not be confirmed" in fake_resp.json()["detail"].lower()

        # 2. Authentic provider message ID (confirmed via live carrier telemetry) succeeds
        real_msg_id = f"termii_real_{secrets.token_hex(6)}"
        mock_ok = MagicMock(status_code=200)
        mock_ok.json.return_value = {
            "message_id": real_msg_id,
            "to": "2348011223344",
            "from": settings.TERMII_SENDER_ID or "PostcodeLnk",
            "text": f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is 123456.",
            "status": "Delivered",
        }
        with patch("httpx.get", return_value=mock_ok):
            ok_resp = client.post(
                f"/api/v1/deliveries/outbox/{outbox_id}/reconcile",
                json={
                    "resolution": "mark_sent",
                    "evidence_type": "provider_telemetry_verified",
                    "provider_message_id": real_msg_id,
                    "reason": "Confirmed against provider telemetry logs with verified status.",
                },
                headers=admin_headers,
            )
        assert ok_resp.status_code == 200
        db.refresh(outbox_item)
        assert outbox_item.status == NotificationDeliveryStatus.SENT
        assert outbox_item.failure_classification == "provider_verified_resolution"
        assert outbox_item.provider_message_id == real_msg_id
    finally:
        try:
            if outbox_id:
                db.query(NotificationOutbox).filter(NotificationOutbox.id == outbox_id).delete()
            deliv = db.query(Delivery).filter(Delivery.id == delivery_id).first()
            if deliv:
                deliv.is_deleted = True
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


# ==============================================================================
# 2. P1: Database-Level Audit Immutability (Raw SQL UPDATE & DELETE Triggers)
# ==============================================================================
def test_database_level_audit_immutability_triggers():
    """Verify that raw SQL UPDATE and DELETE on delivery_events are blocked by database triggers."""
    db = SessionLocal()
    delivery_id = f"PL-TRIGGER-{secrets.token_hex(4)}"
    try:
        delivery = Delivery(
            id=delivery_id,
            recipient_phone="+2348011223344",
            recipient_name="Trigger Test",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="10 Marina St",
            package_description="Trigger Immutability Test",
            postcode_input="100271",
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("123456"),
            tracking_token=f"token_{secrets.token_hex(16)}",
        )
        db.add(delivery)
        db.commit()

        event = DeliveryEvent(
            delivery_id=delivery.id,
            status=DeliveryStatus.PENDING,
            actor_name="Audit System",
            actor_role="system",
            note="Initial order created audit event.",
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        event_id = event.id

        # 1. Direct raw SQL UPDATE must fail at database engine trigger level
        update_failed = False
        try:
            db.execute(
                text("UPDATE delivery_events SET note = 'Tampered via Raw SQL' WHERE id = :id"),
                {"id": event_id},
            )
            db.commit()
        except Exception as exc:
            update_failed = True
            db.rollback()
            err_msg = str(exc).lower()
            assert "immutable" in err_msg or "cannot be updated" in err_msg or "abort" in err_msg

        assert update_failed, "Database trigger must prevent direct SQL UPDATE on delivery_events!"

        # 2. Direct raw SQL DELETE must fail at database engine trigger level
        delete_failed = False
        try:
            db.execute(
                text("DELETE FROM delivery_events WHERE id = :id"),
                {"id": event_id},
            )
            db.commit()
        except Exception as exc:
            delete_failed = True
            db.rollback()
            err_msg = str(exc).lower()
            assert "immutable" in err_msg or "cannot be deleted" in err_msg or "abort" in err_msg

        assert delete_failed, "Database trigger must prevent direct SQL DELETE on delivery_events!"

        # 3. Permanent retention: soft-deletion archives delivery while audit events remain permanently intact
        delivery.is_deleted = True
        db.commit()

        # Audit events still exist and are queryable
        preserved_event = db.query(DeliveryEvent).filter(DeliveryEvent.id == event_id).first()
        assert preserved_event is not None
        assert preserved_event.delivery_id == delivery_id
    finally:
        db.close()


# ==============================================================================
# 3. P1: Production Redis Mandatory Policy & Fail-Closed Behavior
# ==============================================================================
def test_production_redis_mandatory_policy_and_fail_closed():
    """Verify that in production, Redis is mandatory by default and distributed rate limiting fails closed."""
    # 1. Production startup without REDIS_URL and without explicit single-instance opt-out raises ValueError
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

    # 2. Explicit opt-out for single-instance staging/dev bypasses the check
    dev_settings = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="a" * 35,
        OUTBOX_ENCRYPTION_KEY="b" * 35,
        SMS_PROVIDER="termii",
        TERMII_API_KEY="valid_key",
        OUTBOX_WORKER_ENABLED=True,
        REDIS_URL=None,
        REDIS_REQUIRED_IN_PRODUCTION=True,
        ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION=True,
    )
    assert dev_settings.ENVIRONMENT == "production"

    # 3. Test fail-closed runtime policy: in production when Redis fails, rate limiter raises HTTP 503
    with patch("backend.app.config.settings.ENVIRONMENT", "production"), \
         patch("backend.app.config.settings.RATE_LIMIT_REDIS_FAIL_CLOSED", True), \
         patch("backend.app.core.rate_limiter._get_redis_client", return_value=None):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            check_api_key_rate_limit("test_key_fail_closed", limit_per_minute=60)
        assert exc_info.value.status_code == 503
        assert "fail-closed" in exc_info.value.detail.lower()


# ==============================================================================
# 4. P2: Redis Real Lua Cardinality Test (No Accumulation of Rejected Requests)
# ==============================================================================
def test_redis_lua_does_not_accumulate_rejected_requests_in_sorted_set():
    """Directly inspect Redis sorted-set to verify rejected requests are never added by Lua script."""
    r_client = _get_redis_client()
    if not r_client:
        pytest.skip("Redis service not configured in this test environment.")

    test_key = f"v59_lua_test_{secrets.token_hex(4)}"
    r_key = f"ratelimit:apikey:{test_key}"
    limit = 3

    try:
        # Clear any prior state
        r_client.delete(r_key)

        # 1. Send 3 permitted requests
        for _ in range(limit):
            check_api_key_rate_limit(test_key, limit_per_minute=limit)

        assert r_client.zcard(r_key) == limit

        # 2. Send 5 rejected requests
        for _ in range(5):
            try:
                check_api_key_rate_limit(test_key, limit_per_minute=limit)
            except Exception:
                pass

        # 3. Verify Redis sorted-set cardinality is STILL exactly limit (3)
        actual_cardinality = r_client.zcard(r_key)
        assert actual_cardinality == limit, f"Expected {limit} items in Redis sorted-set, found {actual_cardinality}!"
    finally:
        r_client.delete(r_key)


# ==============================================================================
# 5. P2: Real Worker Loop Graceful Shutdown & Abrupt Termination
# ==============================================================================
def test_worker_loop_graceful_shutdown_and_abrupt_stale_detection():
    """Verify worker background loop records stopped status on stop_event and detects stale workers on timeout."""
    worker_id = f"test-loop-worker-{secrets.token_hex(4)}"
    stop_event = asyncio.Event()

    # 1. Run worker loop in separate thread until first heartbeat
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_outbox_worker_loop(stop_event, poll_interval=1, worker_id=worker_id))
        finally:
            loop.close()

    worker_thread = threading.Thread(target=_run, daemon=True)
    worker_thread.start()

    # Wait for worker heartbeat to appear in DB
    time.sleep(1.5)
    db = SessionLocal()
    try:
        hb = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
        assert hb is not None
        assert hb.status in ["active", "idle"]

        # Signal graceful shutdown
        stop_event.set()
        worker_thread.join(timeout=3.0)

        # Verify DB records clean stopped state
        db.refresh(hb)
        assert hb.status == "stopped"
        assert hb.stop_reason == "graceful_shutdown"

        # 2. Test abrupt termination: simulate worker with expired heartbeat
        abrupt_worker_id = f"abrupt-worker-{secrets.token_hex(4)}"
        old_time = datetime.now(timezone.utc) - timedelta(seconds=200)
        abrupt_hb = WorkerHeartbeat(
            worker_id=abrupt_worker_id,
            process_id=99999,
            worker_role="outbox_worker",
            last_heartbeat_at=old_time,
            status="active",
            created_at=old_time,
            updated_at=old_time,
        )
        db.add(abrupt_hb)
        db.commit()

        # Check /health/worker categorizes it as stale
        resp = client.get("/health/worker")
        assert resp.status_code == 200
        data = resp.json()
        assert any(w["worker_id"] == abrupt_worker_id for w in data.get("stale_workers", []))
        assert data["status"] == "degraded"
    finally:
        try:
            db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id.in_([worker_id, abrupt_worker_id])).delete()
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


# ==============================================================================
# 6. P2: Requeue Policy for Exhausted Outbox Items
# ==============================================================================
def test_manual_requeue_resets_retry_counter_and_enables_processing():
    """Verify that an exhausted outbox notification (retry_count == max_retries) is processed after admin requeue."""
    admin_token = get_token(AppRole.ADMIN, "v59_requeue_admin@test.ng")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    db = SessionLocal()
    delivery_id = f"PL-EXHAUSTED-{secrets.token_hex(4)}"
    outbox_id = None
    try:
        delivery = Delivery(
            id=delivery_id,
            recipient_phone="+2348055667788",
            recipient_name="Exhausted Recipient",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="20 Allen Ave",
            package_description="Exhausted Item Test",
            postcode_input="100271",
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("112233"),
            tracking_token=f"token_{secrets.token_hex(16)}",
        )
        db.add(delivery)
        db.commit()

        # Item has exhausted all retries and failed
        item = NotificationOutbox(
            delivery_id=delivery.id,
            notification_type="otp_delivery_pin",
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            provider="simulated",
            status=NotificationDeliveryStatus.FAILED,
            retry_count=3,
            max_retries=3,
            error_details="Max retries exhausted.",
            idempotency_key=f"exhausted_key_{secrets.token_hex(4)}",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        outbox_id = item.id

        # 1. Admin requeues the exhausted item
        requeue_resp = client.post(
            f"/api/v1/deliveries/outbox/{outbox_id}/reconcile",
            json={
                "resolution": "requeue",
                "reason": "Customer corrected their mobile network coverage; supervisor approved requeue.",
            },
            headers=admin_headers,
        )
        assert requeue_resp.status_code == 200

        db.refresh(item)
        assert item.status == NotificationDeliveryStatus.QUEUED
        assert item.retry_count == 0, "Retry counter must be reset to 0 to enable worker dispatch"

        # 2. Worker tick processes the requeued item
        processed = process_notification_outbox(db, max_items=10, worker_id="requeue-worker-1")
        assert processed >= 1

        db.refresh(item)
        assert item.status in [NotificationDeliveryStatus.SENT, NotificationDeliveryStatus.SIMULATED]
    finally:
        try:
            if outbox_id:
                db.query(NotificationOutbox).filter(NotificationOutbox.id == outbox_id).delete()
            deliv = db.query(Delivery).filter(Delivery.id == delivery_id).first()
            if deliv:
                deliv.is_deleted = True
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
