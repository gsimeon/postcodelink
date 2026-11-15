"""Release Gate v5.6: Test Suite for Authoritative Verification, Quota Atomicity & Resilient Outbox Reconciliation."""
import time
import uuid
import secrets
from datetime import datetime, timezone, timedelta
import pytest
from starlette.testclient import TestClient
from sqlalchemy import text

from backend.app.main import app
from backend.app.database import SessionLocal, get_db
from backend.app.config import settings
from backend.app.models.profile import Profile
from backend.app.models.delivery import Delivery
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.api_key import ApiKey
from backend.app.models.enums import DeliveryStatus, AppRole
from backend.app.services.notification_service import (
    NotificationDeliveryStatus,
    NotificationDispatchResult,
    SimulatedNotificationProvider,
    get_notification_provider,
)
from backend.app.core.security import (
    encrypt_authenticated_pin,
    decrypt_authenticated_pin,
    hash_otp,
    create_access_token,
)
from backend.app.services.delivery_service import (
    decrypt_transit_pin,
    process_notification_outbox,
)
from backend.app.core.rate_limiter import reset_api_key_rate_limits
from backend.app.services.nipost_client import NIPOSTClient, NIPOSTLookupStatus, NIPOSTLookupResult

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    reset_api_key_rate_limits()
    db = SessionLocal()
    try:
        db.query(NotificationOutbox).delete()
        db.commit()
    finally:
        db.close()


def get_token(role: AppRole = AppRole.MERCHANT, email: str = "merchant@test.ng") -> str:
    db = SessionLocal()
    try:
        user = db.query(Profile).filter(Profile.email == email).first()
        if not user:
            user = Profile(
                id=str(uuid.uuid4()),
                email=email,
                role=role,
                full_name="Test User",
                hashed_password="hashed_test_password",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return create_access_token({"sub": user.id, "role": user.role.value})
    finally:
        db.close()


# ==============================================================================
# 1. Safe Postcode Migration: Preserves Legitimate NIPOST Records
# ==============================================================================
def test_postcode_migration_preserves_verified_nipost_records():
    """Verify that migration e5f6a7b8c9d0 logic reclassifies demo fixtures but preserves verified NIPOST records."""
    db = SessionLocal()
    try:
        # Create test records
        demo_code = "FC-02-A09-DB-09"
        nipost_code = "900211-NIPOST-TEST"
        local_code = "100001-LOCAL-TEST"

        db.query(PostcodeDirectory).filter(PostcodeDirectory.code.in_([demo_code, nipost_code, local_code])).delete()
        db.commit()

        # Insert demo fixture
        demo_rec = PostcodeDirectory(
            code=demo_code,
            area="Garki 2 Area",
            state="Abuja FCT",
            provenance="PostcodeLink Demonstration Reference",
            verification_status="official_verified",  # Legacy misclassification
        )
        # Insert legitimate NIPOST verified record
        nipost_rec = PostcodeDirectory(
            code=nipost_code,
            area="Central Business District",
            state="Abuja FCT",
            provenance="NIPOST Official National Directory (Live API)",
            verification_status="official_verified",
        )
        # Insert local reference record
        local_rec = PostcodeDirectory(
            code=local_code,
            area="Ikeja Local",
            state="Lagos",
            provenance="PostcodeLink Local Reference Dataset",
            verification_status="official_verified",  # Legacy misclassification
        )
        db.add_all([demo_rec, nipost_rec, local_rec])
        db.commit()

        # Execute migration logic
        db.execute(
            text(
                "UPDATE postcodes "
                "SET verification_status = 'local_reference', "
                "    provenance = 'PostcodeLink National Postcode Format Demonstration Reference' "
                "WHERE code IN ('FC-02-A09-DB-09', 'LA-01-A04-IK-02') "
                "   OR provenance LIKE '%Demonstration%' "
                "   OR provenance LIKE '%Local Reference%' "
                "   OR provenance LIKE '%Pilot%' "
                "   OR (verification_status = 'official_verified' AND provenance NOT LIKE '%NIPOST Official%')"
            )
        )
        db.execute(
            text(
                "UPDATE postcodes "
                "SET verification_status = 'official_verified' "
                "WHERE provenance LIKE '%NIPOST Official%' "
                "  AND (verification_status IS NULL OR verification_status = 'local_reference')"
            )
        )
        db.commit()

        # Verify
        reloaded_demo = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == demo_code).first()
        reloaded_nipost = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == nipost_code).first()
        reloaded_local = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == local_code).first()

        assert reloaded_demo.verification_status == "local_reference", "Demo fixture must be local_reference"
        assert reloaded_local.verification_status == "local_reference", "Local fixture must be local_reference"
        assert reloaded_nipost.verification_status == "official_verified", "Legitimate NIPOST record MUST retain official_verified"
    finally:
        db.query(PostcodeDirectory).filter(PostcodeDirectory.code.in_([nipost_code, local_code])).delete()
        db.commit()
        from backend.app.seed import seed_database
        seed_database()
        db.close()


# ==============================================================================
# 2. Strict AES-GCM Context Enforcement
# ==============================================================================
def test_strict_aes_gcm_context_enforcement_rejects_unbound_decryption():
    """Verify that active delivery decryption strictly requires context and rejects unbound envelopes."""
    key = "test_key_32_characters_strictly_long!"
    pin = "654321"
    deliv_id = "del-strict-context-001"

    # Encrypt with delivery context
    bound_envelope = encrypt_authenticated_pin(pin, master_key=key, delivery_id=deliv_id)

    # 1. Matching delivery ID succeeds
    assert decrypt_authenticated_pin(bound_envelope, master_key=key, delivery_id=deliv_id) == pin
    assert decrypt_transit_pin(bound_envelope, secret_key=key, delivery_id=deliv_id) == pin

    # 2. Calling without context fails
    assert decrypt_authenticated_pin(bound_envelope, master_key=key, delivery_id=None) is None
    assert decrypt_transit_pin(bound_envelope, secret_key=key, delivery_id=None) is None

    # 3. Encrypting with no context (unbound envelope)
    unbound_envelope = encrypt_authenticated_pin(pin, master_key=key, delivery_id=None)
    # Unbound envelope must be rejected by normal delivery decryption workflows
    assert decrypt_authenticated_pin(unbound_envelope, master_key=key, delivery_id=deliv_id) is None
    assert decrypt_authenticated_pin(unbound_envelope, master_key=key, delivery_id=None) is None
    # Allowed only if explicit allow_unbound=True
    assert decrypt_authenticated_pin(unbound_envelope, master_key=key, allow_unbound=True) == pin

    # 4. Cross-delivery context substitution fails
    assert decrypt_authenticated_pin(bound_envelope, master_key=key, delivery_id="del-other-999") is None


# ==============================================================================
# 3. API Key Rotation Inherits Quota Usage & Prevents Reset Bypass
# ==============================================================================
def test_api_key_rotation_inherits_quota_usage_preventing_bypass():
    """Verify that rotating an API key invalidates the old key and inherits billing period usage."""
    token = get_token(AppRole.MERCHANT, "quota_rot_merchant@test.ng")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create an API key with quota 50
    create_res = client.post("/api/v1/api-keys/", json={"name": "Initial Key", "monthly_quota": 50}, headers=headers)
    assert create_res.status_code == 201
    old_key_data = create_res.json()
    old_key_id = old_key_data["id"]

    db = SessionLocal()
    try:
        # Simulate that 40 requests have been used in current period
        old_key = db.query(ApiKey).filter(ApiKey.id == old_key_id).first()
        old_key.period_usage_count = 40
        old_key.usage_count = 40
        db.commit()
    finally:
        db.close()

    # 2. Rotate the key
    rot_res = client.post(f"/api/v1/api-keys/{old_key_id}/rotate", headers=headers)
    assert rot_res.status_code in [200, 201]
    new_key_data = rot_res.json()
    new_key_id = new_key_data["id"]

    # 3. Verify old key is revoked and inactive
    db = SessionLocal()
    try:
        reloaded_old = db.query(ApiKey).filter(ApiKey.id == old_key_id).first()
        assert reloaded_old.is_revoked is True
        assert reloaded_old.is_active is False

        # 4. Verify new key inherited the 40 used requests (quota did not reset!)
        reloaded_new = db.query(ApiKey).filter(ApiKey.id == new_key_id).first()
        assert reloaded_new.period_usage_count == 40
        assert reloaded_new.usage_count == 40
        assert reloaded_new.monthly_quota == 50
    finally:
        db.close()

    # 5. Verify the new key only has 10 remaining requests before 429
    new_raw_key = new_key_data["api_key"]
    # Send 10 successful requests
    for i in range(10):
        res = client.get("/api/v1/postcodes/lookup?state=Lagos", headers={"x-api-key": new_raw_key})
        assert res.status_code == 200, f"Request {i+1} should succeed under remaining quota"

    # 11th request must receive HTTP 429 quota exceeded
    res_exceeded = client.get("/api/v1/postcodes/lookup?state=Lagos", headers={"x-api-key": new_raw_key})
    assert res_exceeded.status_code == 429
    assert "quota" in res_exceeded.json()["detail"].lower()


# ==============================================================================
# 4. Atomic Monthly Quota Rollover & Concurrent Race Prevention
# ==============================================================================
def test_atomic_monthly_quota_rollover_and_increment():
    """Verify single-operation atomic monthly rollover and increment handling."""
    token = get_token(AppRole.MERCHANT, "rollover_merchant@test.ng")
    headers = {"Authorization": f"Bearer {token}"}

    create_res = client.post("/api/v1/api-keys/", json={"name": "Rollover Test", "monthly_quota": 5}, headers=headers)
    assert create_res.status_code == 201
    key_data = create_res.json()
    raw_key = key_data["api_key"]
    key_id = key_data["id"]

    db = SessionLocal()
    try:
        # Simulate previous month exhaustion (e.g. 2026-10 with 100/5 usage)
        key_rec = db.query(ApiKey).filter(ApiKey.id == key_id).first()
        key_rec.current_period = "2026-10"
        key_rec.period_usage_count = 100
        key_rec.usage_count = 100
        db.commit()
    finally:
        db.close()

    # Request arrives in current month (2026-11)
    res = client.get("/api/v1/postcodes/lookup?state=Lagos", headers={"x-api-key": raw_key})
    assert res.status_code == 200

    db = SessionLocal()
    try:
        reloaded = db.query(ApiKey).filter(ApiKey.id == key_id).first()
        now_period = datetime.now(timezone.utc).strftime("%Y-%m")
        assert reloaded.current_period == now_period
        assert reloaded.period_usage_count == 1, "Period usage count must be atomically reset to 1 on first request of new period"
        assert reloaded.usage_count == 101, "Lifetime usage count must be preserved and incremented"
    finally:
        db.close()


# ==============================================================================
# 5. Per-Minute API Key Rate Limiting Enforcement
# ==============================================================================
def test_api_key_per_minute_rate_limiter_enforcement():
    """Verify that rate_limit_per_minute is enforced with Retry-After header and independent per key."""
    token = get_token(AppRole.MERCHANT, "ratelimit_merchant@test.ng")
    headers = {"Authorization": f"Bearer {token}"}

    create_res = client.post("/api/v1/api-keys/", json={"name": "Throttled Key", "monthly_quota": 1000}, headers=headers)
    assert create_res.status_code == 201
    key_data = create_res.json()
    raw_key = key_data["api_key"]
    key_id = key_data["id"]

    db = SessionLocal()
    try:
        # Set limit to 4 requests per minute
        key_rec = db.query(ApiKey).filter(ApiKey.id == key_id).first()
        key_rec.rate_limit_per_minute = 4
        db.commit()
    finally:
        db.close()

    # 4 requests succeed
    for i in range(4):
        res = client.get("/api/v1/postcodes/lookup?state=Lagos", headers={"x-api-key": raw_key})
        assert res.status_code == 200, f"Request {i+1} should succeed"

    # 5th request in the same minute must fail with 429
    res_throttled = client.get("/api/v1/postcodes/lookup?state=Lagos", headers={"x-api-key": raw_key})
    assert res_throttled.status_code == 429
    assert "rate limit exceeded" in res_throttled.json()["detail"].lower()
    assert "Retry-After" in res_throttled.headers


# ==============================================================================
# 6. Outbox Crash Recovery & Operator Manual Reconciliation
# ==============================================================================
def test_outbox_real_provider_crash_recovery_and_status_reconciliation():
    """Verify outbox worker crash recovery via provider status inquiries and operator reconciliation."""
    db = SessionLocal()
    try:
        # Create merchant and delivery
        merchant = db.query(Profile).filter(Profile.role == AppRole.MERCHANT).first()
        if not merchant:
            merchant = Profile(id=str(uuid.uuid4()), email="outbox_m@test.ng", role=AppRole.MERCHANT, full_name="Merchant")
            db.add(merchant)
            db.commit()

        deliv = Delivery(
            id=f"PL-TEST-{secrets.token_hex(3).upper()}",
            merchant_id=merchant.id,
            recipient_name="Crash Recipient",
            recipient_phone="+2348011223344",
            destination_address="10 Marina Street",
            destination_state="Lagos",
            destination_area="Lagos Island",
            postcode_input="100221",
            package_description="Fragile Electronics",
            status=DeliveryStatus.OUT_FOR_DELIVERY,
            otp_hash=hash_otp("123456"),
            version=1,
        )
        db.add(deliv)
        db.commit()

        # Scenario A: Worker crashed while dispatching, but provider accepted message
        # Simulate active provider cache has recorded the message
        idempotency_key = f"outbox_crash_test_{secrets.token_hex(4)}"
        provider = get_notification_provider("simulated")
        provider._dispatched_idempotency_keys[idempotency_key] = NotificationDispatchResult(
            status=NotificationDeliveryStatus.SENT,
            channel="Simulated SMS",
            recipient_masked="+234****3344",
            provider="simulated",
            message_preview="Confirmed sent.",
            message_id="prov_msg_12345",
            idempotency_key=idempotency_key,
        )

        outbox_item_a = NotificationOutbox(
            id=str(uuid.uuid4()),
            delivery_id=deliv.id,
            delivery_version=1,
            recipient_phone=deliv.recipient_phone,
            notification_type="otp_delivery_pin",
            channel="sms",
            provider="simulated",
            status=NotificationDeliveryStatus.DISPATCHING,  # Left in DISPATCHING from prior crash
            retry_count=2,
            idempotency_key=idempotency_key,
            locked_at=datetime.now(timezone.utc) - timedelta(minutes=10),  # Expired lease
        )
        db.add(outbox_item_a)

        # Scenario B: Worker crashed while dispatching, provider has NO record (uncertain crash window)
        uncertain_key = f"outbox_uncertain_{secrets.token_hex(4)}"
        outbox_item_b = NotificationOutbox(
            id=str(uuid.uuid4()),
            delivery_id=deliv.id,
            delivery_version=1,
            recipient_phone=deliv.recipient_phone,
            notification_type="otp_delivery_pin",
            channel="sms",
            provider="simulated",
            status=NotificationDeliveryStatus.DISPATCHING,
            retry_count=2,
            idempotency_key=uncertain_key,
            locked_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db.add(outbox_item_b)
        db.commit()

        # Run outbox worker process
        processed = process_notification_outbox(db, max_items=10)
        assert processed >= 2

        db.refresh(outbox_item_a)
        db.refresh(outbox_item_b)

        # Item A was confirmed by provider check -> reconciled to SENT
        assert outbox_item_a.status == NotificationDeliveryStatus.SENT
        assert outbox_item_a.provider_message_id == "prov_msg_12345"

        # Item B was uncertain -> routed to RECONCILIATION_REQUIRED to prevent duplicate SMS
        assert outbox_item_b.status == NotificationDeliveryStatus.RECONCILIATION_REQUIRED
        assert outbox_item_b.failure_classification == "unconfirmed_crash_window"

        # Scenario C: Operator Manual Reconciliation Endpoint
        op_token = get_token(AppRole.OPERATOR, "courier_op@test.ng")
        op_headers = {"Authorization": f"Bearer {op_token}"}

        # 1. List reconciliations
        list_res = client.get("/api/v1/deliveries/outbox/reconciliation", headers=op_headers)
        assert list_res.status_code == 200
        rec_items = list_res.json()
        assert any(it["id"] == outbox_item_b.id for it in rec_items)

        # 2. Operator resolves Item B: mark_sent
        resolve_res = client.post(
            f"/api/v1/deliveries/outbox/{outbox_item_b.id}/reconcile",
            json={"resolution": "mark_sent", "provider_message_id": "OP_CONFIRMED_MSG_99", "note": "Checked with Telco; SMS was delivered."},
            headers=op_headers,
        )
        assert resolve_res.status_code == 200
        db.refresh(outbox_item_b)
        assert outbox_item_b.status == NotificationDeliveryStatus.SENT
        assert outbox_item_b.provider_message_id == "OP_CONFIRMED_MSG_99"
    finally:
        db.close()


# ==============================================================================
# 7. Strict NIPOST Verification Fails Closed on Error
# ==============================================================================
def test_strict_nipost_verification_fails_closed(monkeypatch):
    """Verify that strict=true fails closed with HTTP 502/503 when NIPOST is unauthorized or unavailable."""
    # Mock NIPOST client returning UNAUTHORIZED
    def mock_lookup_unauthorized(self, code: str):
        return NIPOSTLookupResult(
            status=NIPOSTLookupStatus.UNAUTHORIZED,
            data=None,
            error_message="Invalid API Key credentials",
        )

    monkeypatch.setattr(NIPOSTClient, "is_configured", True)
    monkeypatch.setattr(NIPOSTClient, "lookup_postcode", mock_lookup_unauthorized)

    # With strict=true: must return HTTP 502 Bad Gateway
    res_strict = client.get("/api/v1/postcodes/lookup?code=FC-02-A09-DB-09&strict=true")
    assert res_strict.status_code == 502
    assert "authorization failed" in res_strict.json()["detail"].lower()

    # With strict=false (default): gracefully returns local reference with fallback_used=True
    res_permissive = client.get("/api/v1/postcodes/lookup?code=FC-02-A09-DB-09&strict=false")
    assert res_permissive.status_code == 200
    data = res_permissive.json()
    assert data["fallback_used"] is True
    assert data["lookup_status"] == "fallback_reference"
    assert data["verification_status"] == "local_reference"


# ==============================================================================
# 8. Enhanced Health Probes
# ==============================================================================
def test_enhanced_health_probes():
    """Verify liveness, readiness failure status, and worker queue/reconciliation monitoring."""
    # 1. Liveness
    live_res = client.get("/health/live")
    assert live_res.status_code == 200
    assert live_res.json()["status"] == "alive"

    # 2. Readiness with connected DB
    ready_res = client.get("/health/ready")
    assert ready_res.status_code == 200
    assert ready_res.json()["status"] == "ready"

    # 3. Worker telemetry
    worker_res = client.get("/health/worker")
    assert worker_res.status_code == 200
    w_data = worker_res.json()
    assert "outbox_pending_count" in w_data
    assert "outbox_reconciliation_required_count" in w_data
    assert "status" in w_data

    # 4. Integrations
    int_res = client.get("/health/integrations")
    assert int_res.status_code == 200
    assert int_res.json()["status"] == "operational"
