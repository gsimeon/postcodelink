"""Comprehensive regression tests for Release Gate v5.1 — Notification Integrity and Postcode Verification.

Verifies:
1. Real notification provider dispatch from outbox worker (Termii & Twilio HTTP calls).
2. Zero-knowledge PIN hash rotation on worker dispatch.
3. Outbox worker expired lease recovery.
4. Digital postcode strict verification vs format recognition (NIPOST building-level directory).
5. Canonical digital postcode format normalization, case tolerance, and resolution levels.
6. Login rate limiting with trusted proxy validation & anti-spoofing defense.
7. Login attempt database retention cleanup policy.
8. Configurable operator fleet capacity.
9. Delivery and bulk import idempotency key deduplication.
10. Background worker loop lifecycle execution.
"""
import uuid
import secrets
import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import pytest
import httpx
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.config import settings
from backend.app.models.profile import Profile
from backend.app.models.delivery import Delivery
from backend.app.models.operator import Operator
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.login_attempt import LoginAttempt
from backend.app.models.enums import DeliveryStatus, PostcodeStatus, AppRole, VehicleType
from backend.app.services.notification_service import (
    NotificationDeliveryStatus,
    TermiiNotificationProvider,
    TwilioNotificationProvider,
    get_notification_provider,
)
from backend.app.services.postcode_service import (
    cleanse_address,
    find_postcodes,
    normalize_digital_postcode,
)
from backend.app.services.delivery_service import (
    process_notification_outbox,
    create_delivery,
    assign_operator,
)
from backend.app.schemas.delivery import DeliveryCreateRequest, DeliveryAssignRequest
from backend.app.routers.auth import (
    get_trusted_client_ip,
    cleanup_expired_login_attempts,
)
from backend.app.workers.outbox_worker import run_outbox_worker_loop

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_db_state():
    """Clean transient attempts and test data between test executions."""
    db = SessionLocal()
    try:
        db.query(LoginAttempt).delete()
        db.query(NotificationOutbox).delete()
        db.commit()
    finally:
        db.close()


def get_token(email: str = "dispatch@postcodelink.ng", password: str = "MerchantPass123!") -> str:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


# ==============================================================================
# 1. Outbox Worker Real Provider Dispatch (Termii & Twilio)
# ==============================================================================
def test_outbox_worker_real_provider_termii_dispatch():
    """Verify that process_notification_outbox executes an actual HTTP request to Termii."""
    db = SessionLocal()
    try:
        merchant = db.query(Profile).filter(Profile.role == AppRole.MERCHANT).first()
        deliv = Delivery(
            id=f"PL-2026-TERMII-{uuid.uuid4().hex[:6].upper()}",
            merchant_id=merchant.id,
            recipient_name="Chioma Okonkwo",
            recipient_phone="08023456789",
            destination_address="14 Victoria Island, Lagos",
            destination_area="Victoria Island (VI)",
            destination_state="Lagos",
            postcode_input="101233",
            package_description="Termii Dispatch Package",
            fee=2500.0,
            status=DeliveryStatus.PENDING,
            otp_hash="OLD_HASH_VALUE",
        )
        db.add(deliv)
        db.commit()

        outbox = NotificationOutbox(
            delivery_id=deliv.id,
            channel="SMS",
            recipient_phone="08023456789",
            recipient_name="Chioma Okonkwo",
            provider="termii",
            notification_type="otp_delivery_pin",
            status=NotificationDeliveryStatus.QUEUED,
        )
        db.add(outbox)
        db.commit()
        db.refresh(outbox)

        resp_ok = SimpleNamespace(
            status_code=200,
            json=lambda: {"code": "ok", "message_id": "msg-termii-884422"},
            raise_for_status=lambda: None,
        )

        with patch("httpx.post", return_value=resp_ok) as mock_post:
            processed = process_notification_outbox(db, max_items=10, worker_id="worker-termii-test")

        assert processed == 1
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        assert "to" in call_kwargs["json"]
        assert call_kwargs["json"]["to"] == "2348023456789"
        assert "api_key" in call_kwargs["json"]

        db.refresh(outbox)
        assert outbox.status == NotificationDeliveryStatus.SENT
        assert outbox.sent_at is not None
        assert outbox.error_details is None
        assert outbox.failure_classification is None
        assert outbox.locked_at is None
    finally:
        db.close()


def test_outbox_worker_real_provider_twilio_dispatch():
    """Verify that process_notification_outbox executes an actual HTTP request to Twilio."""
    db = SessionLocal()
    try:
        merchant = db.query(Profile).filter(Profile.role == AppRole.MERCHANT).first()
        deliv = Delivery(
            id=f"PL-2026-TWILIO-{uuid.uuid4().hex[:6].upper()}",
            merchant_id=merchant.id,
            recipient_name="Emeka Eze",
            recipient_phone="08098765432",
            destination_address="20 Admiralty Way, Lekki, Lagos",
            destination_area="Lekki Phase 1",
            destination_state="Lagos",
            postcode_input="101241",
            package_description="Twilio Dispatch Package",
            fee=3000.0,
            status=DeliveryStatus.PENDING,
            otp_hash="OLD_TWILIO_HASH",
        )
        db.add(deliv)
        db.commit()

        outbox = NotificationOutbox(
            delivery_id=deliv.id,
            channel="SMS",
            recipient_phone="08098765432",
            recipient_name="Emeka Eze",
            provider="twilio",
            notification_type="otp_delivery_pin",
            status=NotificationDeliveryStatus.QUEUED,
        )
        db.add(outbox)
        db.commit()

        resp_ok = SimpleNamespace(
            status_code=200,
            json=lambda: {"sid": "SM998877665544332211"},
            raise_for_status=lambda: None,
        )

        with patch("httpx.post", return_value=resp_ok) as mock_post:
            processed = process_notification_outbox(db, max_items=10, worker_id="worker-twilio-test")

        assert processed == 1
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        assert "To" in call_kwargs["data"]
        assert call_kwargs["data"]["To"] == "+2348098765432"

        db.refresh(outbox)
        assert outbox.status == NotificationDeliveryStatus.SENT
        assert outbox.sent_at is not None
        assert outbox.locked_at is None
    finally:
        db.close()


# ==============================================================================
# 2. Zero-Knowledge PIN Hash Rotation on Outbox Worker Dispatch
# ==============================================================================
def test_outbox_worker_zero_knowledge_pin_rotation_on_dispatch():
    """Verify that worker dispatch generates a fresh PIN and securely updates delivery.otp_hash without persisting plaintext."""
    db = SessionLocal()
    try:
        merchant = db.query(Profile).filter(Profile.role == AppRole.MERCHANT).first()
        initial_hash = "ORIGINAL_HASH_STALE"

        deliv = Delivery(
            id=f"PL-2026-PINROT-{uuid.uuid4().hex[:6].upper()}",
            merchant_id=merchant.id,
            recipient_name="Tunde Bakare",
            recipient_phone="08033331111",
            destination_address="5 Allen Avenue, Ikeja, Lagos",
            destination_area="Opebi / Allen Avenue",
            destination_state="Lagos",
            postcode_input="100281",
            package_description="Secure PIN Package",
            fee=2500.0,
            status=DeliveryStatus.PENDING,
            otp_hash=initial_hash,
        )
        db.add(deliv)
        db.commit()

        outbox = NotificationOutbox(
            delivery_id=deliv.id,
            channel="SMS",
            recipient_phone="08033331111",
            recipient_name="Tunde Bakare",
            provider="simulated",
            notification_type="otp_delivery_pin",
            status=NotificationDeliveryStatus.QUEUED,
        )
        db.add(outbox)
        db.commit()

        # Execute worker
        process_notification_outbox(db, max_items=10, worker_id="worker-pinrot-test")

        db.refresh(deliv)
        # 1. PIN hash was rotated to a new cryptographically secure hash
        assert deliv.otp_hash != initial_hash
        assert len(deliv.otp_hash) >= 20
        # 2. Delivery record does not have any plaintext field
        assert not hasattr(deliv, "raw_pin")
        assert not hasattr(deliv, "otp")
    finally:
        db.close()


# ==============================================================================
# 3. Outbox Worker Expired Lease Recovery
# ==============================================================================
def test_outbox_worker_expired_lease_recovery():
    """Verify that an abandoned or expired lease from a crashed worker is recovered and processed by another worker."""
    db = SessionLocal()
    try:
        merchant = db.query(Profile).filter(Profile.role == AppRole.MERCHANT).first()
        deliv = Delivery(
            id=f"PL-2026-LEASE-{uuid.uuid4().hex[:6].upper()}",
            merchant_id=merchant.id,
            recipient_name="Fatima Aliyu",
            recipient_phone="08077778888",
            destination_address="12 Marina, Lagos",
            destination_area="Ikeja Central / Alausa",
            destination_state="Lagos",
            postcode_input="100001",
            package_description="Lease Recovery Package",
            fee=2500.0,
            status=DeliveryStatus.PENDING,
            otp_hash="HASHED_PIN",
        )
        db.add(deliv)
        db.commit()

        # Simulate crashed worker: lease locked 10 minutes ago
        crashed_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        outbox = NotificationOutbox(
            delivery_id=deliv.id,
            channel="SMS",
            recipient_phone="08077778888",
            recipient_name="Fatima Aliyu",
            provider="simulated",
            notification_type="otp_delivery_pin",
            status=NotificationDeliveryStatus.QUEUED,
            locked_at=crashed_time,
            locked_by="crashed-worker-pod-xyz",
            retry_count=1,
            max_retries=3,
        )
        db.add(outbox)
        db.commit()
        db.refresh(outbox)

        # New live worker acquires batch
        new_worker_id = "live-worker-pod-001"
        processed = process_notification_outbox(db, max_items=10, worker_id=new_worker_id)
        assert processed == 1

        db.refresh(outbox)
        assert outbox.status == NotificationDeliveryStatus.SIMULATED
        assert outbox.sent_at is not None
        assert outbox.locked_at is None
        assert outbox.locked_by is None
    finally:
        db.close()


# ==============================================================================
# 4. Digital Postcode Strict Directory Verification vs Format Recognition
# ==============================================================================
def test_digital_postcode_strict_directory_verification():
    """Verify that digital postcodes are verified ONLY when an exact record exists in the authoritative directory."""
    # 1. Registered building code -> VERIFIED with building reference
    res_registered = cleanse_address(
        address="Suite 4, Commercial Plaza, Ikeja, Lagos",
        postcode_hint="LAG-IKJ-0012",
    )
    assert res_registered.postcode_type == "digital_location"
    assert res_registered.resolution_level == "building_location"
    assert res_registered.postcode_status == "verified"
    assert res_registered.postcode == "LAG-IKJ-0012"
    assert res_registered.confidence >= 0.90
    assert res_registered.matched_record is not None
    assert res_registered.matched_record.building_reference == "Plot 4 Ikeja Commercial Plaza"

    # 2. Valid syntax, but UNREGISTERED in directory -> UNVERIFIED (format recognized, but zero false claim)
    res_unregistered = cleanse_address(
        address="House 8, Some Unknown Street, Lagos",
        postcode_hint="LAG-IKJ-9999",
    )
    assert res_unregistered.postcode_type == "digital_location"
    assert res_unregistered.resolution_level == "building_location"
    assert res_unregistered.postcode_status == "unverified"
    assert res_unregistered.postcode == "LAG-IKJ-9999"
    assert res_unregistered.confidence == 0.0
    assert res_unregistered.matched_record is None
    assert any("not found in the verified building directory" in c for c in res_unregistered.changes_made)

    # 3. Canonical Format Normalization: lowercase and space-delimited codes normalize cleanly
    res_normalized = cleanse_address(
        address="Suite 4, Commercial Plaza, Ikeja, Lagos",
        postcode_hint="lag ikj 0012",
    )
    assert res_normalized.postcode == "LAG-IKJ-0012"
    assert res_normalized.postcode_status == "verified"

    # 4. Conventional 6-digit area postcode maintains area_district resolution
    res_conventional = cleanse_address(
        address="10 Ahmadu Bello Way, Victoria Island, Lagos",
        postcode_hint="101233",
    )
    assert res_conventional.postcode_type == "conventional_area"
    assert res_conventional.resolution_level == "area_district"
    assert res_conventional.postcode_status == "verified"


# ==============================================================================
# 5. Trusted Proxy & Rate Limiting Anti-Spoofing Defense
# ==============================================================================
def test_login_rate_limiting_trusted_proxy_and_anti_spoofing():
    """Verify that user-supplied X-Forwarded-For headers from untrusted connections are rejected to defeat rate limit bypass."""
    # Dummy mock requests
    # Case A: Untrusted peer -> X-Forwarded-For is completely ignored
    untrusted_req = MagicMock()
    untrusted_req.client.host = "198.51.100.25"  # Public untrusted client IP
    untrusted_req.headers = {"x-forwarded-for": "203.0.113.195"}

    ip_extracted = get_trusted_client_ip(untrusted_req)
    assert ip_extracted == "198.51.100.25"  # Spoofed 203.0.113.195 was rejected!

    # Case B: Trusted proxy peer -> X-Forwarded-For is respected
    trusted_req = MagicMock()
    trusted_req.client.host = "127.0.0.1"  # Local trusted reverse proxy / load balancer
    trusted_req.headers = {"x-forwarded-for": "203.0.113.195"}

    ip_trusted = get_trusted_client_ip(trusted_req)
    assert ip_trusted == "203.0.113.195"

    # Case C: Multiple chained proxies -> first untrusted client IP from the right is selected
    chained_req = MagicMock()
    chained_req.client.host = "127.0.0.1"
    chained_req.headers = {"x-forwarded-for": "10.0.0.5, 198.51.100.44, 127.0.0.1"}

    ip_chained = get_trusted_client_ip(chained_req)
    assert ip_chained == "198.51.100.44"


def test_login_attempt_retention_policy_cleanup():
    """Verify that cleanup_expired_login_attempts purges stale records older than 30 days."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        # 1. Insert stale attempt 45 days ago
        old_attempt = LoginAttempt(
            email="stale_user@postcodelink.ng",
            ip_address="192.168.1.1",
            attempted_at=now - timedelta(days=45),
            is_successful=False,
        )
        # 2. Insert recent attempt 5 days ago
        recent_attempt = LoginAttempt(
            email="recent_user@postcodelink.ng",
            ip_address="192.168.1.2",
            attempted_at=now - timedelta(days=5),
            is_successful=False,
        )
        db.add_all([old_attempt, recent_attempt])
        db.commit()

        # Run retention cleanup (retention_days=30)
        deleted_count = cleanup_expired_login_attempts(db, retention_days=30)
        assert deleted_count >= 1

        # Check in DB
        assert db.query(LoginAttempt).filter(LoginAttempt.email == "stale_user@postcodelink.ng").first() is None
        assert db.query(LoginAttempt).filter(LoginAttempt.email == "recent_user@postcodelink.ng").first() is not None
    finally:
        db.close()


# ==============================================================================
# 6. Configurable Operator Fleet Capacity
# ==============================================================================
def test_operator_configurable_capacity():
    """Verify that operators enforce configurable max_active_deliveries instead of hardcoded constants."""
    db = SessionLocal()
    try:
        # Create an operator with max_active_deliveries = 2
        op_profile = Profile(
            full_name="Low Capacity Operator",
            email=f"lowcap_{secrets.token_hex(4)}@postcodelink.ng",
            hashed_password="SecurePassword123!",
            role=AppRole.OPERATOR,
        )
        db.add(op_profile)
        db.commit()

        op = Operator(
            profile_id=op_profile.id,
            business_name="Bicycle Express Fleet",
            phone="08012344321",
            vehicle_type=VehicleType.BICYCLE,
            service_areas=["Ikeja"],
            is_available=True,
            active_deliveries_count=2,  # Already at max capacity!
            max_active_deliveries=2,
        )
        db.add(op)
        db.commit()
        db.refresh(op)

        merchant = db.query(Profile).filter(Profile.role == AppRole.MERCHANT).first()
        deliv = Delivery(
            id=f"PL-2026-CAP-{uuid.uuid4().hex[:6].upper()}",
            merchant_id=merchant.id,
            recipient_name="Cap Test",
            recipient_phone="08011119999",
            destination_address="10 Ikeja Road, Lagos",
            destination_area="Ikeja",
            destination_state="Lagos",
            postcode_input="100001",
            package_description="Capacity Test Goods",
            fee=2500.0,
            status=DeliveryStatus.PENDING,
            otp_hash="HASHED_PIN",
        )
        db.add(deliv)
        db.commit()

        # Assigning to operator at capacity (2/2) MUST fail with 400
        req = DeliveryAssignRequest(operator_id=op.id)
        with pytest.raises(Exception) as excinfo:
            assign_operator(db, deliv.id, req, merchant)
        assert "maximum dispatch capacity" in str(excinfo.value.detail).lower()

        # Increase capacity to 5 -> Assignment succeeds
        op.max_active_deliveries = 5
        db.commit()

        assigned_deliv = assign_operator(db, deliv.id, req, merchant)
        assert assigned_deliv.operator_id == op.id
    finally:
        db.close()


# ==============================================================================
# 7. Delivery & Bulk Import Idempotency Key Deduplication
# ==============================================================================
def test_delivery_bulk_import_idempotency():
    """Verify that submitting orders with an idempotency_key prevents duplicate order generation."""
    token = get_token("dispatch@postcodelink.ng", "MerchantPass123!")
    idem_key = f"bulk-key-{uuid.uuid4().hex[:12]}"

    payload = {
        "recipient_name": "Idempotency Recipient",
        "recipient_phone": "08012345678",
        "destination_address": "45 Marina, Lagos",
        "destination_area": "Marina",
        "destination_state": "Lagos",
        "postcode": "100001",
        "package_description": "Idempotent Goods",
        "fee": 3500.0,
        "idempotency_key": idem_key,
    }

    # First request: Creates the order
    res1 = client.post("/api/v1/deliveries/", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res1.status_code == 201
    order_id_1 = res1.json()["delivery"]["id"]

    # Second request with identical idempotency_key: Replays existing order
    res2 = client.post("/api/v1/deliveries/", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res2.status_code == 201
    order_id_2 = res2.json()["delivery"]["id"]

    assert order_id_1 == order_id_2
    assert res2.json()["notification_dispatch"]["status"] == "IDEMPOTENT_REPLAY"


# ==============================================================================
# 8. Background Outbox Worker Loop Lifecycle Execution
# ==============================================================================
def test_background_worker_loop_execution():
    """Verify that run_outbox_worker_loop starts, executes periodic ticks, and shuts down on signal."""
    async def _run():
        stop_event = asyncio.Event()
        task = asyncio.create_task(run_outbox_worker_loop(stop_event, poll_interval=1, worker_id="test-lifecycle-worker"))
        await asyncio.sleep(1.2)
        stop_event.set()
        await asyncio.wait_for(task, timeout=3.0)
        assert task.done()

    asyncio.run(_run())
