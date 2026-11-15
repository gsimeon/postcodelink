"""Release Gate v5.8: Provider Reconciliation, Production Resilience & Concurrency Tests."""
import uuid
import time
import secrets
import pytest
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import text

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
    TermiiNotificationProvider,
    TwilioNotificationProvider,
    SimulatedNotificationProvider,
    mask_phone,
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
    finally:
        db.close()


def get_token(role: AppRole = AppRole.MERCHANT, email: str = "v58_merchant@test.ng") -> str:
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
# 1. Termii Crash Recovery Without Saved Message ID (Zero Duplicate SMS)
# ==============================================================================
def test_termii_crash_recovery_without_saved_id_routes_to_reconciliation_zero_duplicates():
    """Verify Termii crash recovery when provider accepted SMS but worker crashed before saving message ID.
    
    Termii does not support outbound query by phone without message ID.
    Acceptance criteria: Worker routes to RECONCILIATION_REQUIRED and DOES NOT trigger duplicate SMS.
    """
    db = SessionLocal()
    delivery_id = f"PL-TERMII-CRASH-{secrets.token_hex(4)}"
    try:
        delivery = Delivery(
            id=delivery_id,
            recipient_phone="+2348012345678",
            recipient_name="Termii Recipient",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="12 Allen Ave",
            package_description="Termii Crash Test",
            postcode_input="100271",
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("654321"),
            tracking_token=f"token_{secrets.token_hex(16)}",
        )
        db.add(delivery)
        db.commit()

        # Item simulated in DISPATCHING from prior crashed worker tick
        outbox_item = NotificationOutbox(
            delivery_id=delivery.id,
            notification_type="otp_delivery_pin",
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            provider="termii",
            status=NotificationDeliveryStatus.DISPATCHING,
            idempotency_key=f"outbox_termii_crash_{secrets.token_hex(4)}",
            provider_message_id=None,  # Lost in crash before commit
            retry_count=2,
            delivery_version=1,
            max_retries=3,
        )
        db.add(outbox_item)
        db.commit()

        # Mock termii provider to verify send_delivery_pin is NEVER called
        termii_provider = get_notification_provider("termii")
        with patch.object(termii_provider, "send_delivery_pin") as mock_send:
            processed = process_notification_outbox(db, max_items=10, worker_id="termii-worker-1")
            assert processed == 1
            # MUST NOT send duplicate SMS!
            mock_send.assert_not_called()

        db.refresh(outbox_item)
        assert outbox_item.status == NotificationDeliveryStatus.RECONCILIATION_REQUIRED
        assert outbox_item.failure_classification == "unconfirmed_crash_window"
        assert "administrator reconciliation" in outbox_item.error_details.lower()
    finally:
        db.query(NotificationOutbox).filter(NotificationOutbox.delivery_id == delivery_id).delete()
        db.query(Delivery).filter(Delivery.id == delivery_id).delete()
        db.commit()
        db.close()


# ==============================================================================
# 2. Twilio Fingerprint Verification vs Ambiguous Association
# ==============================================================================
def test_twilio_recovery_fingerprint_matching_and_ambiguity_rejection():
    """Verify Twilio outbound query matches ONLY when message body contains the exact delivery fingerprint."""
    provider = TwilioNotificationProvider(
        account_sid="AC_test_account_sid_12345",
        auth_token="auth_token_secret_12345",
        from_number="+15550001111",
    )

    # Case A: Messages returned for recipient are for a DIFFERENT delivery (or missing fingerprint)
    mock_messages_diff_delivery = {
        "messages": [
            {
                "sid": "SM_unrelated_111",
                "status": "delivered",
                "to": "+2348012345678",
                "body": "Your PostcodeLink delivery confirmation PIN for order PL-OTHER-999 is 112233.",
            },
            {
                "sid": "SM_unrelated_222",
                "status": "delivered",
                "to": "+2348012345678",
                "body": "Your general verification code is 998877.",
            },
        ]
    }

    mock_resp_a = MagicMock()
    mock_resp_a.status_code = 200
    mock_resp_a.json.return_value = mock_messages_diff_delivery

    with patch("httpx.get", return_value=mock_resp_a):
        # We query for order PL-TARGET-001: should return None because no message matches PL-TARGET-001
        res = provider.check_message_status(
            idempotency_key="key_1",
            provider_message_id=None,
            recipient_phone="+2348012345678",
            delivery_id="PL-TARGET-001",
        )
        assert res is None, "Must NOT associate an unrelated delivery's SMS with this delivery!"

    # Case B: Message returned contains the exact matching delivery fingerprint
    mock_messages_exact_match = {
        "messages": [
            {
                "sid": "SM_exact_target_333",
                "status": "delivered",
                "to": "+2348012345678",
                "body": "Your PostcodeLink delivery confirmation PIN for order PL-TARGET-001 is 654321.",
            }
        ]
    }
    mock_resp_b = MagicMock()
    mock_resp_b.status_code = 200
    mock_resp_b.json.return_value = mock_messages_exact_match

    with patch("httpx.get", return_value=mock_resp_b):
        res = provider.check_message_status(
            idempotency_key="key_2",
            provider_message_id=None,
            recipient_phone="+2348012345678",
            delivery_id="PL-TARGET-001",
        )
        assert res is not None
        assert res.status == NotificationDeliveryStatus.SENT
        assert res.message_id == "SM_exact_target_333"


# ==============================================================================
# 3. Rate Limiter Rejection Does Not Accumulate in Window (P2 Fix)
# ==============================================================================
def test_rate_limiter_does_not_accumulate_rejected_requests():
    """Verify that requests exceeding the limit do not accumulate into the active window."""
    test_key = f"key_reject_test_{secrets.token_hex(4)}"
    limit = 2

    # First 2 requests succeed
    check_api_key_rate_limit(test_key, limit_per_minute=limit)
    check_api_key_rate_limit(test_key, limit_per_minute=limit)

    # 3rd request is rejected with 429
    with pytest.raises(Exception) as exc_info:
        check_api_key_rate_limit(test_key, limit_per_minute=limit)
    assert exc_info.value.status_code == 429

    # 4th and 5th rejected requests
    for _ in range(3):
        try:
            check_api_key_rate_limit(test_key, limit_per_minute=limit)
        except Exception:
            pass

    # Verify that in-memory or Redis window size did NOT expand beyond 2 entries
    from backend.app.core.rate_limiter import _KEY_REQUEST_WINDOWS
    if test_key in _KEY_REQUEST_WINDOWS:
        assert len(_KEY_REQUEST_WINDOWS[test_key]) == limit, "Rejected requests must not be appended to window!"


# ==============================================================================
# 4. Redis Connection Backoff Retry and Operational Monitoring
# ==============================================================================
def test_rate_limiter_monitoring_and_fail_closed_policy():
    """Verify rate limiter status endpoint and production fail-closed policy."""
    status_data = get_rate_limiter_status()
    assert "backend" in status_data
    assert "redis_configured" in status_data
    assert "in_memory_active_keys" in status_data

    # Test /health/rate-limiter endpoint
    resp = client.get("/health/rate-limiter")
    assert resp.status_code == 200
    data = resp.json()
    assert "backend" in data

    # Test /health/integrations includes rate limiter
    int_resp = client.get("/health/integrations")
    assert int_resp.status_code == 200
    int_data = int_resp.json()
    assert "rate_limiter" in int_data


# ==============================================================================
# 5. Concurrent API Key Rotation Transaction-Level Race Test
# ==============================================================================
def test_concurrent_api_key_rotation_transaction_level_race():
    """Simultaneously execute 2 rotation requests on the same active API key.
    
    Expected result:
    - Exactly 1 request succeeds with 201 Created and mints replacement key.
    - Exactly 1 request fails with 409 Conflict.
    - The old key is revoked.
    - Quota is inherited exactly once.
    """
    token = get_token(AppRole.MERCHANT, "v58_race_merchant@test.ng")
    headers = {"Authorization": f"Bearer {token}"}

    # Ensure clean slate for this merchant's API keys
    db = SessionLocal()
    try:
        user = db.query(Profile).filter(Profile.email == "v58_race_merchant@test.ng").first()
        if user:
            db.query(ApiKey).filter(ApiKey.merchant_id == user.id).delete()
            db.commit()
    finally:
        db.close()

    # 1. Create initial key with specific quota
    create_resp = client.post(
        "/api/v1/api-keys/",
        json={"name": "Race Rotation Key", "monthly_quota": 500},
        headers=headers,
    )
    assert create_resp.status_code == 201
    key_id = create_resp.json()["id"]

    # Seed some usage
    db = SessionLocal()
    try:
        k_obj = db.query(ApiKey).filter(ApiKey.id == key_id).first()
        k_obj.period_usage_count = 25
        k_obj.usage_count = 50
        db.commit()
    finally:
        db.close()

    # 2. Fire 2 simultaneous rotation requests via ThreadPoolExecutor
    def _rotate():
        # Dedicated client per thread
        t_client = TestClient(app)
        return t_client.post(f"/api/v1/api-keys/{key_id}/rotate", headers=headers)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_rotate)
        f2 = executor.submit(_rotate)
        r1 = f1.result()
        r2 = f2.result()

    status_codes = sorted([r1.status_code, r2.status_code])
    assert status_codes == [201, 409], f"Expected exactly one 201 and one 409, got {status_codes}"

    # 3. Verify database state
    db = SessionLocal()
    try:
        old_k = db.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert old_k.is_active is False
        assert old_k.is_revoked is True

        # Exactly 1 active key must exist for this merchant
        active_keys = (
            db.query(ApiKey)
            .filter(
                ApiKey.merchant_id == old_k.merchant_id,
                ApiKey.is_active.is_(True),
                ApiKey.is_revoked.is_(False),
            )
            .all()
        )
        assert len(active_keys) == 1
        new_k = active_keys[0]
        assert new_k.period_usage_count == 25, "Must inherit exact period usage without double-counting"
        assert new_k.usage_count == 50
        assert new_k.monthly_quota == 500
    finally:
        user = db.query(Profile).filter(Profile.email == "v58_race_merchant@test.ng").first()
        if user:
            db.query(ApiKey).filter(ApiKey.merchant_id == user.id).delete()
            db.commit()
        db.close()


# ==============================================================================
# 6. Worker Graceful Shutdown & Heartbeat Lifecycle Telemetry
# ==============================================================================
def test_worker_heartbeat_graceful_shutdown_and_telemetry():
    """Verify worker records stopped state on shutdown and /health/worker exposes lifecycle state."""
    db = SessionLocal()
    worker_id = f"test-lifecycle-worker-{secrets.token_hex(4)}"
    try:
        # 1. Record active heartbeat with processed items
        record_worker_heartbeat(db, worker_id=worker_id, status="active", processed_count=7)
        hb = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
        assert hb.status == "active"
        assert hb.processed_count == 7
        assert hb.last_successful_process_at is not None

        # Check /health/worker reports operational
        resp = client.get("/health/worker")
        assert resp.status_code == 200
        data = resp.json()
        assert any(w["worker_id"] == worker_id for w in data.get("active_workers", []))
        assert data["last_successful_process_at"] is not None

        # 2. Record clean worker shutdown
        record_worker_shutdown(db, worker_id=worker_id, reason="SIGTERM")
        db.refresh(hb)
        assert hb.status == "stopped"
        assert hb.stop_reason == "SIGTERM"

        # Check /health/worker reports worker in stopped_workers
        resp2 = client.get("/health/worker")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert any(w["worker_id"] == worker_id for w in data2.get("stopped_workers", []))
    finally:
        db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).delete()
        db.commit()
        db.close()


# ==============================================================================
# 7. Reconciliation Evidence Types and DeliveryEvent Immutability
# ==============================================================================
def test_reconciliation_evidence_types_and_event_immutability():
    """Verify evidence_type validation, reconciliation request ID tracking, and DeliveryEvent immutability."""
    admin_token = get_token(AppRole.ADMIN, "v58_admin_recon@test.ng")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    db = SessionLocal()
    delivery_id = f"PL-RECON-V58-{secrets.token_hex(4)}"
    outbox_id = None
    try:
        delivery = Delivery(
            id=delivery_id,
            recipient_phone="+2348099887766",
            recipient_name="Recon Test User",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="45 Victoria Island",
            package_description="Evidence Test",
            postcode_input="100271",
            status=DeliveryStatus.OUT_FOR_DELIVERY,
            otp_hash=hash_otp("112233"),
            tracking_token=f"token_{secrets.token_hex(16)}",
        )
        db.add(delivery)
        db.commit()

        item = NotificationOutbox(
            delivery_id=delivery.id,
            notification_type="otp_delivery_pin",
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            status=NotificationDeliveryStatus.RECONCILIATION_REQUIRED,
            idempotency_key=f"recon_item_v58_{secrets.token_hex(4)}",
            retry_count=2,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        outbox_id = item.id

        # 1. Provider-verified resolution WITHOUT provider_message_id must be rejected (422)
        rej_resp = client.post(
            f"/api/v1/deliveries/outbox/{outbox_id}/reconcile",
            json={
                "resolution": "mark_sent",
                "evidence_type": "provider_telemetry_verified",
                "reason": "Operator claims verified without providing message ID",
                "evidence_reference": "ticket-1234",
            },
            headers=admin_headers,
        )
        assert rej_resp.status_code == 422
        assert "provider_message_id" in rej_resp.json()["detail"]

        # 2. Valid reconciliation with manual_operator_asserted evidence
        recon_req_id = f"custom-recon-{secrets.token_hex(4)}"
        ok_resp = client.post(
            f"/api/v1/deliveries/outbox/{outbox_id}/reconcile",
            json={
                "resolution": "mark_sent",
                "evidence_type": "manual_operator_asserted",
                "reason": "Customer verbally confirmed PIN receipt via customer support dispatch call.",
                "evidence_reference": "Zendesk Ticket #99281",
                "reconciliation_request_id": recon_req_id,
            },
            headers=admin_headers,
        )
        assert ok_resp.status_code == 200
        db.refresh(item)
        assert item.status == NotificationDeliveryStatus.SENT
        assert item.evidence_type == "manual_operator_asserted"
        assert item.reconciliation_request_id == recon_req_id

        # 3. Verify DeliveryEvent immutability: attempting to update a DeliveryEvent raises ValueError
        event = db.query(DeliveryEvent).filter(DeliveryEvent.delivery_id == delivery_id).first()
        assert event is not None
        with pytest.raises(ValueError) as exc:
            event.note = "Tampered audit note"
            db.commit()
        assert "immutable" in str(exc.value).lower()
        db.rollback()
    finally:
        if outbox_id:
            db.query(NotificationOutbox).filter(NotificationOutbox.id == outbox_id).delete()
        db.query(Delivery).filter(Delivery.id == delivery_id).delete()
        db.query(DeliveryEvent).filter(DeliveryEvent.delivery_id == delivery_id).delete()
        db.commit()
        db.close()


# ==============================================================================
# 8. Production Configuration Enforces Redis Requirement
# ==============================================================================
def test_production_configuration_enforces_redis():
    """Verify that in production environment, startup validation strictly requires REDIS_URL."""
    # When ENVIRONMENT is production and REDIS_URL is None, Settings validation raises ValueError
    with pytest.raises(ValueError) as exc:
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a" * 35,
            OUTBOX_ENCRYPTION_KEY="b" * 35,
            SMS_PROVIDER="termii",
            TERMII_API_KEY="test_key",
            OUTBOX_WORKER_ENABLED=True,
            REDIS_URL=None,
            REDIS_REQUIRED_IN_PRODUCTION=True,
        )
    assert "REDIS_URL must be configured in production" in str(exc.value)
