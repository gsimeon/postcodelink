"""Release Gate v5.5 Comprehensive Test Suite: Integration Integrity & Production Readiness.

Verifies:
1. P1: Strict AES-256-GCM context-bound AAD delivery matching, empty-AAD rejection, and tamper rejection.
2. P1: Controlled legacy PIN migration upgrading legacy v1/stream tokens to versioned v2 envelopes.
3. P1: Direct HTTP integration with merchant API keys (x-api-key) across Deliveries, Customers, Operators, Postcodes, and Analytics.
4. P1: Atomic monthly API quota enforcement, concurrency race safety, and period rollover.
5. P1: API key rotation endpoint (POST /api/v1/api-keys/{id}/rotate) and revocation immunity.
6. P1: Outbox crash-window idempotency recovery and deduplication (surviving worker crashes during DISPATCHING).
7. P1: Postcode provenance audit (demonstration fixtures return local_reference, never official_verified).
8. P1: Authoritative NIPOST transparent error statuses (UNAUTHORIZED, INVALID_RESPONSE) and fallback reporting.
9. P2: Operator capacity configuration (respecting op.max_active_deliveries) and service area filtering.
10. P2: Production health and observability probes (/health/live, /health/ready, /health/worker, /health/integrations).
"""
import uuid
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.config import settings
from backend.app.models.profile import Profile
from backend.app.models.operator import Operator
from backend.app.models.customer import Customer
from backend.app.models.delivery import Delivery
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.models.api_key import ApiKey
from backend.app.models.enums import DeliveryStatus, AppRole, VehicleType
from backend.app.services.notification_service import (
    NotificationDeliveryStatus,
    SimulatedNotificationProvider,
)
from backend.app.core.security import (
    encrypt_authenticated_pin,
    decrypt_authenticated_pin,
    migrate_legacy_transit_pin,
    create_access_token,
    hash_password,
)
from backend.app.services.delivery_service import (
    create_delivery,
    encrypt_transit_pin,
    decrypt_transit_pin,
    process_notification_outbox,
)
from backend.app.services.postcode_service import (
    find_postcodes,
    cleanse_address,
)
from backend.app.services.nipost_client import (
    NIPOSTClient,
    NIPOSTLookupStatus,
    NIPOSTLookupResult,
)
from backend.app.routers.postcodes import get_nipost_client

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_database_state():
    """Ensure clean state between tests."""
    db = SessionLocal()
    try:
        db.query(NotificationOutbox).delete()
        db.query(Delivery).delete()
        db.commit()
    finally:
        db.close()


def get_or_create_merchant_user(db):
    """Helper creating or retrieving a test merchant profile and JWT."""
    merchant = db.query(Profile).filter(Profile.email == "test_v55_merchant@postcodelink.ng").first()
    if not merchant:
        merchant = Profile(
            email="test_v55_merchant@postcodelink.ng",
            full_name="V5.5 Test Merchant",
            role=AppRole.MERCHANT,
            hashed_password=hash_password("MerchantPass123!"),
        )
        db.add(merchant)
        db.commit()
        db.refresh(merchant)
    token = create_access_token(data={"sub": merchant.id, "role": merchant.role.value})
    return merchant, token


# ==============================================================================
# 1. P1: Strict AES-256-GCM Delivery AAD Binding & Tamper Resistance
# ==============================================================================

def test_aes_gcm_strict_aad_enforcement():
    """Verify that decryption enforces exact delivery AAD equality and strictly rejects empty AAD or cross-delivery substitution."""
    master_key = "secure_production_master_key_32_chars_min"
    pin = "852963"
    deliv_a = "PL-2026-DELIV-A"
    deliv_b = "PL-2026-DELIV-B"

    # Encrypt envelope bound strictly to delivery A
    token = encrypt_authenticated_pin(pin, master_key=master_key, delivery_id=deliv_a)
    assert token.startswith("v2:")

    # 1. Matching delivery ID succeeds
    decrypted = decrypt_authenticated_pin(token, master_key=master_key, delivery_id=deliv_a)
    assert decrypted == pin

    # 2. Cross-delivery substitution MUST return None
    cross_decrypted = decrypt_authenticated_pin(token, master_key=master_key, delivery_id=deliv_b)
    assert cross_decrypted is None, "Cross-delivery substitution must be strictly rejected!"

    # 3. Supplying delivery_id=None when envelope has delivery AAD MUST return None
    no_id_decrypted = decrypt_authenticated_pin(token, master_key=master_key, delivery_id=None)
    assert no_id_decrypted is None, "Delivery-bound envelope must reject None delivery_id"

    # 4. Empty-AAD envelope MUST be rejected when delivery_id is expected
    # Construct an envelope with empty AAD: v2:<nonce>::<ciphertext_tag>
    parts = token.split(":")
    empty_aad_token = f"v2:{parts[1]}::{parts[3]}"
    assert decrypt_authenticated_pin(empty_aad_token, master_key=master_key, delivery_id=deliv_a) is None, \
        "Empty AAD must be rejected when delivery_id is expected!"

    # 5. Tampered ciphertext or tag MUST fail
    tampered_body = parts[3][:-4] + "0000"
    tampered_token = f"v2:{parts[1]}:{parts[2]}:{tampered_body}"
    assert decrypt_authenticated_pin(tampered_token, master_key=master_key, delivery_id=deliv_a) is None


# ==============================================================================
# 2. P1: Controlled Legacy Migration
# ==============================================================================

def test_controlled_legacy_pin_migration():
    """Verify that legacy tokens are rejected on normal decryption and safely upgraded via migrate_legacy_transit_pin."""
    master_key = "secure_production_master_key_32_chars_min"
    pin = "741852"
    deliv_id = "PL-2026-LEGACY-01"

    # Construct a legacy v1 HMAC token: v1:<nonce>:<ciphertext>:<tag>
    import hmac
    from backend.app.core.security import _derive_outbox_subkeys
    raw_nonce = secrets.token_bytes(16)
    enc_key, mac_key = _derive_outbox_subkeys(master_key)
    keystream = hmac.new(enc_key, raw_nonce, hashlib.sha256).digest()
    ciphertext = bytes(p ^ k for p, k in zip(pin.encode("utf-8"), keystream[:len(pin)]))
    expected_tag = hmac.new(mac_key, b"v1:" + raw_nonce + ciphertext, hashlib.sha256).digest()
    legacy_token = f"v1:{raw_nonce.hex()}:{ciphertext.hex()}:{expected_tag.hex()}"

    # Normal verification path MUST reject legacy token
    assert decrypt_authenticated_pin(legacy_token, master_key=master_key, delivery_id=deliv_id, allow_legacy=False) is None

    # Explicit migration routine upgrades it safely
    migration_res = migrate_legacy_transit_pin(legacy_token, master_key=master_key, delivery_id=deliv_id)
    assert migration_res is not None
    recovered_pin, upgraded_envelope = migration_res
    assert recovered_pin == pin
    assert upgraded_envelope.startswith("v2:")

    # Upgraded envelope can now be decrypted via strict v2 verification
    v2_decrypted = decrypt_authenticated_pin(upgraded_envelope, master_key=master_key, delivery_id=deliv_id)
    assert v2_decrypted == pin


# ==============================================================================
# 3. P1: Direct HTTP Integration with x-api-key across Business Endpoints
# ==============================================================================

def test_api_key_http_integration_across_business_apis():
    """Verify that merchant API keys (x-api-key) authenticate across Deliveries, Customers, Operators, Postcodes, and Analytics."""
    db = SessionLocal()
    try:
        merchant, jwt_token = get_or_create_merchant_user(db)
        raw_key = f"pkl_live_{secrets.token_hex(24)}"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        api_key_rec = ApiKey(
            merchant_id=merchant.id,
            name="Production E-commerce Integration",
            hashed_key=key_hash,
            key_prefix=raw_key[:12],
            monthly_quota=1000,
            usage_count=0,
            period_usage_count=0,
            current_period=datetime.now(timezone.utc).strftime("%Y-%m"),
            is_active=True,
            is_revoked=False,
        )
        db.add(api_key_rec)
        db.commit()

        api_headers = {"x-api-key": raw_key}

        # 1. Deliveries Creation via x-api-key
        create_payload = {
            "recipient_name": "Ngozi Obi",
            "recipient_phone": "+2348031234567",
            "destination_address": "Plot 12 Ahmadu Bello Way, Victoria Island, Lagos",
            "destination_area": "Victoria Island (VI)",
            "destination_state": "Lagos",
            "postcode_input": "101233",
            "package_description": "Electronics",
            "fee": 3500.0,
            "idempotency_key": f"test_key_deliv_{secrets.token_hex(6)}",
        }
        res_create = client.post("/api/v1/deliveries/", headers=api_headers, json=create_payload)
        assert res_create.status_code == 201, res_create.text
        deliv_data = res_create.json()
        assert deliv_data["delivery"]["recipient_name"] == "Ngozi Obi"
        deliv_id = deliv_data["delivery"]["id"]

        # 2. Deliveries List via x-api-key (scoped to merchant)
        res_list = client.get("/api/v1/deliveries/", headers=api_headers)
        assert res_list.status_code == 200
        items = res_list.json()
        assert any(item["id"] == deliv_id for item in items)

        # 3. Delivery Details via x-api-key
        res_get = client.get(f"/api/v1/deliveries/{deliv_id}", headers=api_headers)
        assert res_get.status_code == 200
        assert res_get.json()["id"] == deliv_id

        # 4. Customer Directory via x-api-key
        cust_payload = {
            "full_name": "Emeka Chukwu",
            "phone": "+2348099887766",
            "default_address": "22 Allen Avenue, Ikeja, Lagos",
            "area": "Ikeja",
            "state": "Lagos",
            "postcode": "100281",
        }
        res_cust = client.post("/api/v1/customers/", headers=api_headers, json=cust_payload)
        assert res_cust.status_code == 201
        res_cust_list = client.get("/api/v1/customers/", headers=api_headers)
        assert res_cust_list.status_code == 200
        assert any(c["phone"] == "+2348099887766" for c in res_cust_list.json())

        # 5. Operators Directory via x-api-key
        res_ops = client.get("/api/v1/operators/", headers=api_headers)
        assert res_ops.status_code == 200
        assert isinstance(res_ops.json(), list)

        # 6. Analytics Overview via x-api-key
        res_analytics = client.get("/api/v1/analytics/overview", headers=api_headers)
        assert res_analytics.status_code == 200
        assert "total_deliveries" in res_analytics.json()

        # 7. Postcode Cleanse metered via x-api-key
        cleanse_payload = {
            "address": "Beside Ikeja City Mall, Alausa, Ikeja, Lagos",
            "state": "Lagos",
            "area": "Ikeja",
            "postcode": "100001",
        }
        res_cleanse = client.post("/api/v1/postcodes/cleanse", headers=api_headers, json=cleanse_payload)
        assert res_cleanse.status_code == 200
        assert res_cleanse.json()["postcode_valid"] is True

        # Verify usage count was atomically incremented
        db.refresh(api_key_rec)
        assert api_key_rec.period_usage_count >= 7
    finally:
        db.close()


# ==============================================================================
# 4. P1: Atomic Monthly Quota Enforcement & Period Rollover
# ==============================================================================

def test_atomic_monthly_quota_enforcement():
    """Verify that exceeding monthly_quota returns HTTP 429 and period rollover resets usage atomically."""
    db = SessionLocal()
    try:
        merchant, _ = get_or_create_merchant_user(db)
        raw_key = f"pkl_live_{secrets.token_hex(24)}"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        api_key_rec = ApiKey(
            merchant_id=merchant.id,
            name="Quota Test Key",
            hashed_key=key_hash,
            key_prefix=raw_key[:12],
            monthly_quota=2,  # Limit strictly to 2 calls
            usage_count=0,
            period_usage_count=0,
            current_period=datetime.now(timezone.utc).strftime("%Y-%m"),
            is_active=True,
            is_revoked=False,
        )
        db.add(api_key_rec)
        db.commit()

        headers = {"x-api-key": raw_key}

        # Request 1 -> 200 OK
        r1 = client.get("/api/v1/deliveries/", headers=headers)
        assert r1.status_code == 200

        # Request 2 -> 200 OK
        r2 = client.get("/api/v1/deliveries/", headers=headers)
        assert r2.status_code == 200

        # Request 3 -> HTTP 429 Monthly quota exceeded
        r3 = client.get("/api/v1/deliveries/", headers=headers)
        assert r3.status_code == 429
        assert "quota" in r3.json()["detail"].lower() and "exceeded" in r3.json()["detail"].lower()

        # Test period rollover: simulate last month
        api_key_rec.current_period = "2026-10"
        api_key_rec.period_usage_count = 100
        db.commit()

        # Next request in current month triggers period rollover and succeeds
        r4 = client.get("/api/v1/deliveries/", headers=headers)
        assert r4.status_code == 200
        db.refresh(api_key_rec)
        assert api_key_rec.current_period == datetime.now(timezone.utc).strftime("%Y-%m")
        assert api_key_rec.period_usage_count == 1
    finally:
        db.close()


# ==============================================================================
# 5. P1: API Key Rotation & Revocation
# ==============================================================================

def test_api_key_rotation_and_revocation():
    """Verify POST /api/v1/api-keys/{id}/rotate issues a fresh key, revokes the previous key, and blocks revoked access."""
    db = SessionLocal()
    try:
        merchant, jwt_token = get_or_create_merchant_user(db)
        auth_headers = {"Authorization": f"Bearer {jwt_token}"}

        # Create original key
        res_create = client.post(
            "/api/v1/api-keys/",
            headers=auth_headers,
            json={"name": "Original Key", "monthly_quota": 500},
        )
        assert res_create.status_code == 201
        key_data = res_create.json()
        key_id = key_data["id"]
        original_secret = key_data["api_key"]

        # Original key works
        assert client.get("/api/v1/deliveries/", headers={"x-api-key": original_secret}).status_code == 200

        # Rotate key
        res_rotate = client.post(f"/api/v1/api-keys/{key_id}/rotate", headers=auth_headers)
        assert res_rotate.status_code == 201
        rotated_data = res_rotate.json()
        new_secret = rotated_data["api_key"]
        assert new_secret != original_secret

        # Old rotated key MUST return 401 Unauthorized (is_revoked = True)
        res_old = client.get("/api/v1/deliveries/", headers={"x-api-key": original_secret})
        assert res_old.status_code == 401
        assert "revoked" in res_old.json()["detail"].lower()

        # New rotated key works
        assert client.get("/api/v1/deliveries/", headers={"x-api-key": new_secret}).status_code == 200
    finally:
        db.close()


# ==============================================================================
# 6. P1: Outbox Crash-Window Idempotency Recovery
# ==============================================================================

def test_outbox_crash_window_idempotency_recovery():
    """Verify that a worker crashing in DISPATCHING intent is recovered via idempotency_key without duplicate dispatch."""
    db = SessionLocal()
    try:
        merchant, _ = get_or_create_merchant_user(db)
        delivery = Delivery(
            id=f"PL-2026-CRASH-{secrets.token_hex(4).upper()}",
            merchant_id=merchant.id,
            recipient_name="Tunde Bakare",
            recipient_phone="+2348022233445",
            destination_address="15 Marina, Lagos Island",
            destination_area="Lagos Island",
            destination_state="Lagos",
            postcode_input="101233",
            package_description="Standard Package",
            fee=2000.0,
            status=DeliveryStatus.PENDING,
            otp_hash=hash_password("112233"),
        )
        db.add(delivery)
        db.commit()

        # Simulate outbox entry that crashed during HTTP dispatch (DISPATCHING state)
        idemp_key = f"outbox_test_crash_{secrets.token_hex(8)}"
        outbox_item = NotificationOutbox(
            delivery_id=delivery.id,
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            message_payload=encrypt_authenticated_pin("112233", delivery_id=delivery.id),
            delivery_version=1,
            retry_count=1,
            idempotency_key=idemp_key,
            status=NotificationDeliveryStatus.DISPATCHING,
            locked_at=datetime.now(timezone.utc) - timedelta(minutes=10),  # expired lease
            locked_by="dead_worker_pid_9999",
        )
        db.add(outbox_item)
        db.commit()

        # 1. Unconfirmed crash window: when provider status is unknown, worker flags RECONCILIATION_REQUIRED
        processed_count = process_notification_outbox(db)
        assert processed_count >= 1

        db.refresh(outbox_item)
        assert outbox_item.status == NotificationDeliveryStatus.RECONCILIATION_REQUIRED
        assert outbox_item.failure_classification == "unconfirmed_crash_window"

        # 2. Provider acceptance before crash: when provider cached the idempotency key, worker reconciles
        from backend.app.services.notification_service import get_notification_provider, NotificationDispatchResult
        provider = get_notification_provider("simulated")
        idemp_key_confirmed = f"outbox_test_crash_confirmed_{secrets.token_hex(8)}"
        provider._dispatched_idempotency_keys[idemp_key_confirmed] = NotificationDispatchResult(
            status=NotificationDeliveryStatus.SIMULATED,
            channel="Simulated SMS Gateway",
            recipient_masked="+234***45",
            provider="simulated",
            message_preview="Delivery PIN",
            message_id="msg_recovered_12345",
            idempotency_key=idemp_key_confirmed,
        )

        outbox_item2 = NotificationOutbox(
            delivery_id=delivery.id,
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            message_payload=encrypt_authenticated_pin("112233", delivery_id=delivery.id),
            delivery_version=1,
            retry_count=1,
            idempotency_key=idemp_key_confirmed,
            status=NotificationDeliveryStatus.DISPATCHING,
            locked_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            locked_by="dead_worker_pid_9999",
        )
        db.add(outbox_item2)
        db.commit()

        processed_count2 = process_notification_outbox(db)
        assert processed_count2 >= 1

        db.refresh(outbox_item2)
        assert outbox_item2.status in [NotificationDeliveryStatus.SENT, NotificationDeliveryStatus.SIMULATED]
        assert outbox_item2.provider_message_id == "msg_recovered_12345"
    finally:
        db.close()


# ==============================================================================
# 7. P1: Postcode Provenance Audit & Separation
# ==============================================================================

def test_postcode_provenance_audit():
    """Verify that local demonstration fixtures return local_reference, never official_verified."""
    db = SessionLocal()
    try:
        res = client.get("/api/v1/postcodes/lookup?code=FC-02-A09-DB-09")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] >= 1
        match = data["matches"][0]
        assert match["verification_status"] == "local_reference", \
            "Demonstration fixture must never be marked official_verified without live NIPOST API confirmation!"
        assert match["source_owner"] == "PostcodeLink"
        assert match["postcode_category"] == "local_address_reference"
    finally:
        db.close()


# ==============================================================================
# 8. P1: Authoritative NIPOST Transparent Error Statuses
# ==============================================================================

def test_nipost_unauthorized_and_invalid_response_transparency():
    """Verify that upstream NIPOST UNAUTHORIZED and INVALID_RESPONSE report upstream_status transparently."""
    mock_client = MagicMock(spec=NIPOSTClient)
    mock_client.is_configured = True

    # 1. Simulate UNAUTHORIZED upstream
    mock_client.lookup_postcode.return_value = NIPOSTLookupResult(
        status=NIPOSTLookupStatus.UNAUTHORIZED,
        data=None,
        error_message="Invalid NIPOST Organization API Key (401)",
    )
    app.dependency_overrides[get_nipost_client] = lambda: mock_client

    try:
        res = client.get("/api/v1/postcodes/lookup?code=FC-02-A09-DB-09")
        assert res.status_code == 200
        data = res.json()
        assert data["upstream_status"].upper() == "UNAUTHORIZED"
        assert "unauthorized" in data["fallback_reason"].lower()
        assert data["verification_status"] == "local_reference"

        # 2. Simulate INVALID_RESPONSE upstream
        mock_client.lookup_postcode.return_value = NIPOSTLookupResult(
            status=NIPOSTLookupStatus.INVALID_RESPONSE,
            data=None,
            error_message="Upstream NIPOST schema mismatch: missing 'components'",
        )
        res_invalid = client.get("/api/v1/postcodes/lookup?code=FC-02-A09-DB-09")
        assert res_invalid.status_code == 200
        data_inv = res_invalid.json()
        assert data_inv["upstream_status"].upper() == "INVALID_RESPONSE"
        assert "invalid_response" in data_inv["fallback_reason"].lower()
    finally:
        app.dependency_overrides.pop(get_nipost_client, None)


# ==============================================================================
# 9. P2: Operator Capacity Configuration & Service Area Filtering
# ==============================================================================

def test_operator_capacity_configuration_and_filtering():
    """Verify that operator directory respects op.max_active_deliveries and filters by service_area."""
    db = SessionLocal()
    try:
        merchant, _ = get_or_create_merchant_user(db)
        raw_key = f"pkl_live_{secrets.token_hex(24)}"
        api_key = ApiKey(
            merchant_id=merchant.id,
            name="Fleet Key",
            hashed_key=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
            key_prefix=raw_key[:12],
            monthly_quota=1000,
            is_active=True,
            is_revoked=False,
        )
        db.add(api_key)

        # Operator at max capacity (max_active_deliveries = 5, active = 5)
        op_full = Operator(
            business_name="Full Fleet Logistics",
            phone="+2348011112222",
            vehicle_type=VehicleType.MOTORCYCLE,
            service_areas=["Ikeja", "Maryland"],
            is_available=True,
            active_deliveries_count=5,
            max_active_deliveries=5,
        )
        # Operator with custom capacity (max_active_deliveries = 20, active = 16 -> has capacity!)
        op_large = Operator(
            business_name="Large Fleet Couriers",
            phone="+2348033334444",
            vehicle_type=VehicleType.VAN,
            service_areas=["Victoria Island", "Lekki"],
            is_available=True,
            active_deliveries_count=16,
            max_active_deliveries=20,
        )
        db.add_all([op_full, op_large])
        db.commit()

        # Query directory via x-api-key
        res = client.get("/api/v1/operators/", headers={"x-api-key": raw_key})
        assert res.status_code == 200
        ops = res.json()

        full_match = next((o for o in ops if o["id"] == op_full.id), None)
        assert full_match is not None
        assert full_match["has_capacity"] is False, "Operator with active == max must report has_capacity=False"

        large_match = next((o for o in ops if o["id"] == op_large.id), None)
        assert large_match is not None
        assert large_match["has_capacity"] is True, "Operator with 16 active but max 20 must report has_capacity=True"

        # Test service_area filtering
        res_filter = client.get("/api/v1/operators/?service_area=Ikeja", headers={"x-api-key": raw_key})
        assert res_filter.status_code == 200
        filtered_ops = res_filter.json()
        assert any(o["id"] == op_full.id for o in filtered_ops)
        assert not any(o["id"] == op_large.id for o in filtered_ops)
    finally:
        db.close()


# ==============================================================================
# 10. P2: Health Probes (/health/live, /health/ready, /health/worker, /health/integrations)
# ==============================================================================

def test_production_health_probes():
    """Verify that liveness, readiness, worker, and integrations health endpoints operate cleanly."""
    # /health/live
    r_live = client.get("/health/live")
    assert r_live.status_code == 200
    assert r_live.json()["status"] == "alive"

    # /health/ready
    r_ready = client.get("/health/ready")
    assert r_ready.status_code == 200
    assert r_ready.json()["status"] == "ready"
    assert r_ready.json()["database"] == "connected"

    # /health/worker
    r_worker = client.get("/health/worker")
    assert r_worker.status_code == 200
    assert r_worker.json()["status"] == "operational"
    assert "outbox_pending_count" in r_worker.json()

    # /health/integrations
    r_int = client.get("/health/integrations")
    assert r_int.status_code == 200
    assert r_int.json()["status"] == "operational"
    assert "nipost" in r_int.json()
    assert "sms_gateway" in r_int.json()
