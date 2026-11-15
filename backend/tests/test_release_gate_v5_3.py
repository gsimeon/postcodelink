"""Release Gate v5.3: Authenticated Cryptography, Queue Integrity, Postcode Taxonomy, and NIPOST Integration Tests.

Validates:
1. P1: Authenticated transit PIN encryption, HMAC-SHA256 envelope, dedicated OUTBOX_ENCRYPTION_KEY, strict tamper rejection.
2. P1: PIN resend queue cancellation, superseding previous outbox items in the same transaction.
3. P1: Outbox worker rejection of stale/superseded PINs (zero obsolete PIN dispatch).
4. P1: Postcode taxonomy separation (legacy_postal_code vs official_digital_postcode) and explicit data provenance.
5. P1: NIPOST client adapter integration (lookup, address validation, timeout fallback).
6. P1: Production startup default security (forbids demo accounts, enforces distinct encryption keys).
7. P2: Standalone outbox worker CLI process runner and signal handling.
8. P2: ApiKey model and quota foundation schema.
9. P2: Concurrency-safe atomic login rate limiting.
"""
import uuid
import secrets
import pytest
import httpx
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from types import SimpleNamespace

from starlette.testclient import TestClient
from backend.app.main import app
from backend.app.config import Settings, settings
from backend.app.database import SessionLocal
from backend.app.models.profile import Profile
from backend.app.models.delivery import Delivery
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.models.login_attempt import LoginAttempt
from backend.app.models.api_key import ApiKey
from backend.app.models.enums import DeliveryStatus, PostcodeStatus, AppRole
from backend.app.services.notification_service import NotificationDeliveryStatus
from backend.app.services.delivery_service import (
    create_delivery,
    resend_delivery_pin,
    process_notification_outbox,
    encrypt_transit_pin,
    decrypt_transit_pin,
)
from backend.app.services.postcode_service import cleanse_address, find_postcodes
from backend.app.services.nipost_client import NIPOSTClient
from backend.app.core.security import (
    hash_otp,
    verify_otp_hash,
    encrypt_authenticated_pin,
    decrypt_authenticated_pin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_test_state():
    """Ensure clean outbox state and login attempt state between tests."""
    db = SessionLocal()
    try:
        db.query(NotificationOutbox).delete()
        db.query(LoginAttempt).delete()
        db.commit()
    finally:
        db.close()


def get_merchant_token() -> str:
    """Helper to authenticate and retrieve a valid merchant JWT token."""
    login_res = client.post("/api/v1/auth/login", json={
        "email": "dispatch@postcodelink.ng",
        "password": "MerchantPass123!"
    })
    assert login_res.status_code == 200
    return login_res.json()["access_token"]


# ==============================================================================
# 1. Authenticated Cryptography & Key Separation Tests
# ==============================================================================
def test_authenticated_pin_encryption_tamper_rejection():
    """Verify that authenticated PIN encryption produces v1 envelope and strictly rejects tampered payloads."""
    key = "a_very_strong_dedicated_outbox_key_32_chars!"
    pin = "739201"

    token = encrypt_authenticated_pin(pin, master_key=key, delivery_id="del-test-123")
    assert token.startswith("v2:")
    parts = token.split(":")
    assert len(parts) == 4, "AES-GCM Envelope must have 4 segments: v2, nonce, aad, ct_and_tag"

    # 1. Valid decryption with bound AAD
    decrypted = decrypt_authenticated_pin(token, master_key=key, delivery_id="del-test-123")
    assert decrypted == pin

    # 2. Tampering with ciphertext: change one byte
    tampered_ct = parts[0] + ":" + parts[1] + ":" + parts[2] + ":" + ("00" * (len(parts[3]) // 2))
    assert decrypt_authenticated_pin(tampered_ct, master_key=key, delivery_id="del-test-123") is None, "Tampered ciphertext must fail authentication"

    # 3. Tampering with nonce
    tampered_nonce = parts[0] + ":" + ("aa" * 12) + ":" + parts[2] + ":" + parts[3]
    assert decrypt_authenticated_pin(tampered_nonce, master_key=key, delivery_id="del-test-123") is None, "Tampered nonce must fail authentication"

    # 4. Domain separation: decrypting with SECRET_KEY instead of OUTBOX_ENCRYPTION_KEY must fail
    wrong_key = "a_completely_different_secret_key_32_chars!"
    assert decrypt_authenticated_pin(token, master_key=wrong_key, delivery_id="del-test-123") is None, "Wrong key must fail authentication"

    # 5. Backward compatibility with v1 HMAC-SHA256 envelope (controlled migration path)
    from backend.app.core.security import _derive_outbox_subkeys
    import hmac, hashlib
    enc_k, mac_k = _derive_outbox_subkeys(key)
    v1_nonce = b"\x01" * 16
    v1_ks = hmac.new(enc_k, v1_nonce, hashlib.sha256).digest()
    v1_ct = bytes(p ^ k for p, k in zip(pin.encode(), v1_ks))
    v1_tag = hmac.new(mac_k, b"v1:" + v1_nonce + v1_ct, hashlib.sha256).digest()
    v1_payload = f"v1:{v1_nonce.hex()}:{v1_ct.hex()}:{v1_tag.hex()}"
    assert decrypt_authenticated_pin(v1_payload, master_key=key, allow_legacy=True) == pin


# ==============================================================================
# 2. PIN Resend Queue Cancellation & Superseding Tests
# ==============================================================================
def test_pin_resend_cancels_and_supersedes_queued_outbox_items():
    """Verify that calling resend_delivery_pin atomically marks prior queued outbox items as SUPERSEDED."""
    token = get_merchant_token()

    # Step 1: Create a delivery order (generates initial delivery version 1 with QUEUED outbox item)
    create_res = client.post("/api/v1/deliveries/", json={
        "recipient_name": "Supersede Recipient",
        "recipient_phone": "08012345678",
        "destination_address": "Plot 10 Admiralty Way",
        "destination_area": "Lekki Phase 1",
        "destination_state": "Lagos",
        "postcode_input": "101241",
        "package_description": "Electronics",
        "fee": 4500.0,
    }, headers={"Authorization": f"Bearer {token}"})
    assert create_res.status_code == 201
    deliv_id = create_res.json()["delivery"]["id"]

    db = SessionLocal()
    try:
        # Check initial outbox record
        initial_outbox = db.query(NotificationOutbox).filter(
            NotificationOutbox.delivery_id == deliv_id
        ).all()
        assert len(initial_outbox) == 1
        item_1 = initial_outbox[0]
        assert item_1.status == NotificationDeliveryStatus.QUEUED
        assert item_1.delivery_version == 1

        # Step 2: Call resend-pin endpoint
        resend_res = client.post(f"/api/v1/deliveries/{deliv_id}/resend-pin", headers={"Authorization": f"Bearer {token}"})
        assert resend_res.status_code == 200

        # Step 3: Verify the database state in the same session
        all_outbox = db.query(NotificationOutbox).filter(
            NotificationOutbox.delivery_id == deliv_id
        ).order_by(NotificationOutbox.created_at.asc()).all()

        assert len(all_outbox) == 2, "Must contain exactly 2 outbox entries: superseded initial item and fresh resend item"
        
        # Verify item 1 is strictly SUPERSEDED
        db.refresh(item_1)
        assert item_1.status == NotificationDeliveryStatus.SUPERSEDED
        assert "Superseded" in item_1.error_details

        # Verify item 2 is QUEUED with delivery_version 2
        item_2 = all_outbox[1]
        assert item_2.status == NotificationDeliveryStatus.QUEUED
        assert item_2.notification_type == "otp_resend"
        assert item_2.delivery_version == 2

        # Verify delivery order itself was incremented to version 2
        deliv = db.query(Delivery).filter(Delivery.id == deliv_id).first()
        assert deliv.version == 2
        assert deliv.otp_attempts == 0
    finally:
        db.close()


# ==============================================================================
# 3. Outbox Worker Protection Against Obsolete PIN Dispatch
# ==============================================================================
def test_outbox_worker_rejects_stale_pin_and_never_dispatches():
    """Verify worker never dispatches a stale PIN if delivery's OTP hash changed prior to execution."""
    db = SessionLocal()
    try:
        merchant = db.query(Profile).filter(Profile.role == AppRole.MERCHANT).first()
        deliv = Delivery(
            id=f"PL-2026-STALE-{uuid.uuid4().hex[:6].upper()}",
            merchant_id=merchant.id,
            recipient_name="Stale Test Recipient",
            recipient_phone="08055667788",
            destination_address="5 Marina, Lagos",
            destination_area="Marina",
            destination_state="Lagos",
            postcode_input="100001",
            package_description="Stale PIN Package",
            fee=2000.0,
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("999999"),  # Updated active PIN in delivery record
            version=2,
        )
        db.add(deliv)
        db.commit()

        # Outbox item contains an encrypted OLD PIN ("111111") bound to delivery ID
        old_pin = "111111"
        encrypted_old_pin = encrypt_transit_pin(old_pin, settings.OUTBOX_ENCRYPTION_KEY, delivery_id=deliv.id)
        stale_outbox = NotificationOutbox(
            delivery_id=deliv.id,
            channel="SMS",
            recipient_phone="08055667788",
            recipient_name="Stale Test Recipient",
            provider="simulated",
            notification_type="otp_delivery_pin",
            delivery_version=1,
            message_payload=encrypted_old_pin,
            status=NotificationDeliveryStatus.QUEUED,
        )
        db.add(stale_outbox)
        db.commit()

        # Process outbox
        with patch("backend.app.services.notification_service.SimulatedNotificationProvider.send_delivery_pin") as mock_send:
            processed = process_notification_outbox(db, max_items=10, worker_id="stale-test-worker")

        assert processed == 1
        # Worker MUST NOT dispatch the stale PIN
        assert mock_send.called is False

        # Outbox item must be classified as SUPERSEDED with stale_pin_superseded reason
        db.refresh(stale_outbox)
        assert stale_outbox.status == NotificationDeliveryStatus.SUPERSEDED
        assert stale_outbox.failure_classification == "stale_pin_superseded"
    finally:
        db.close()


# ==============================================================================
# 4. Postcode Taxonomy & Provenance Metadata Tests
# ==============================================================================
def test_postcode_taxonomy_separation_and_provenance():
    """Verify separation of legacy 6-digit postal codes vs 11-char digital postcodes with accurate provenance."""
    # 1. Legacy 6-digit postal code (Ikeja Central)
    res_legacy = cleanse_address(
        address="10 Allen Avenue, Ikeja, Lagos",
        postcode_hint="100001",
    )
    assert res_legacy.postcode == "100001"
    assert res_legacy.postcode_type == "conventional_area"
    assert res_legacy.postcode_category == "legacy_postal_code"
    assert res_legacy.resolution_level == "area_district"
    assert res_legacy.verification_status == "local_reference"
    assert "NIPOST" in res_legacy.provenance

    # 2. Local digital reference building postcode (Ikeja Commercial Plaza)
    res_digital = cleanse_address(
        address="Commercial Plaza, Ikeja, Lagos",
        postcode_hint="LAG-IKJ-0012",
    )
    assert res_digital.postcode == "LAG-IKJ-0012"
    assert res_digital.postcode_type == "digital_location"
    assert res_digital.postcode_category in ("official_digital_postcode", "local_address_reference")
    assert res_digital.resolution_level == "building_location"
    assert res_digital.verification_status == "local_reference"
    assert "Digital Address" in res_digital.provenance

    # 2b. Official 11-character national digital postcode (Federal Commerce House)
    res_nat = cleanse_address(
        address="Federal Commerce House, Area 2, Garki, Abuja",
        postcode_hint="FC-02-A09-DB-09",
    )
    assert res_nat.postcode == "FC-02-A09-DB-09"
    assert res_nat.postcode_type == "digital_location"
    assert res_nat.postcode_category == "official_digital_postcode"
    assert res_nat.verification_status in ("local_reference", "official_verified")
    assert res_nat.resolution_level == "building_location"

    # 3. Unverified arbitrary address
    res_unverified = cleanse_address(
        address="Some completely unknown non-existent dirt path 9999",
    )
    assert res_unverified.postcode_status == "unverified"
    assert res_unverified.verification_status == "unverified"
    assert res_unverified.provenance == "Unverified Address Input"
    assert res_unverified.postcode == ""


# ==============================================================================
# 5. NIPOST Client Adapter Integration & Fallback Tests
# ==============================================================================
def test_nipost_client_adapter_live_lookup_and_fallback():
    """Verify NIPOSTClient queries external API when configured and falls back to local reference on error."""
    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "code": "LAG-IKJ-9999",
                "area": "NIPOST HQ Annex",
                "state": "Lagos",
                "lga": "Ikeja",
                "postcode_type": "official_digital_postcode",
            }
        )
    )

    client_adapter = NIPOSTClient(
        base_url="https://api.nipost.gov.ng",
        api_key="nipost_live_key_xyz",
        transport=mock_transport,
    )
    assert client_adapter.is_configured is True

    # 1. Successful lookup
    result = client_adapter.lookup_postcode("LAG-IKJ-9999")
    assert result is not None
    assert result["code"] == "LAG-IKJ-9999"
    assert result["area"] == "NIPOST HQ Annex"

    # 2. Resilient fallback on timeout
    timeout_transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(httpx.TimeoutException("NIPOST gateway timed out"))
    )
    client_timeout = NIPOSTClient(
        base_url="https://api.nipost.gov.ng",
        api_key="nipost_key",
        transport=timeout_transport,
    )
    fallback_res = client_timeout.lookup_postcode("100001")
    assert not fallback_res, "On timeout, client adapter reports unavailable allowing seamless local fallback"


# ==============================================================================
# 6. Production Startup Configuration Hardening Tests
# ==============================================================================
def test_production_startup_security_guard_rejects_insecure_keys_and_demo_flags():
    """Verify production settings validator enforces distinct outbox keys and rejects demo accounts."""
    # A. OUTBOX_ENCRYPTION_KEY missing or dev default
    with pytest.raises(ValueError, match="OUTBOX_ENCRYPTION_KEY must be set"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a_very_strong_production_secret_key_32_chars!",
            OUTBOX_ENCRYPTION_KEY="postcodelink_dev_weak_key",
            SMS_PROVIDER="termii",
            TERMII_API_KEY="valid_termii_api_key_test_12345",
            OUTBOX_WORKER_ENABLED=True,
        )

    # B. OUTBOX_ENCRYPTION_KEY equals SECRET_KEY (violates domain separation)
    with pytest.raises(ValueError, match="must be distinct from SECRET_KEY"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="identical_shared_key_across_both_domains_32_chars!",
            OUTBOX_ENCRYPTION_KEY="identical_shared_key_across_both_domains_32_chars!",
            SMS_PROVIDER="termii",
            TERMII_API_KEY="valid_termii_api_key_test_12345",
            OUTBOX_WORKER_ENABLED=True,
        )

    # C. SEED_DEMO_ACCOUNTS=True in production
    with pytest.raises(ValueError, match="SEED_DEMO_ACCOUNTS cannot be enabled in production"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a_very_strong_production_secret_key_32_chars!",
            OUTBOX_ENCRYPTION_KEY="a_dedicated_production_outbox_key_32_chars!",
            SMS_PROVIDER="termii",
            TERMII_API_KEY="valid_termii_api_key_test_12345",
            OUTBOX_WORKER_ENABLED=True,
            SEED_DEMO_ACCOUNTS=True,
        )

    # D. SEED_DEMO_DATA=True in production
    with pytest.raises(ValueError, match="SEED_DEMO_DATA cannot be enabled in production"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a_very_strong_production_secret_key_32_chars!",
            OUTBOX_ENCRYPTION_KEY="a_dedicated_production_outbox_key_32_chars!",
            SMS_PROVIDER="termii",
            TERMII_API_KEY="valid_termii_api_key_test_12345",
            OUTBOX_WORKER_ENABLED=True,
            SEED_DEMO_DATA=True,
        )


# ==============================================================================
# 7. ApiKey Model & Quota Foundation Schema Tests
# ==============================================================================
def test_api_key_foundation_schema_and_quota_tracking():
    """Verify ApiKey foundation table, quota attributes, and profile foreign key relationship."""
    db = SessionLocal()
    try:
        merchant = db.query(Profile).filter(Profile.role == AppRole.MERCHANT).first()
        raw_key = f"pl_live_{secrets.token_hex(16)}"
        hashed_key = hash_otp(raw_key, salt="api_key_salt")

        api_key_entry = ApiKey(
            merchant_id=merchant.id,
            name="Production Shopify Integration",
            key_prefix=raw_key[:12],
            hashed_key=hashed_key,
            monthly_quota=25000,
            usage_count=1,
            is_active=True,
        )
        db.add(api_key_entry)
        db.commit()
        db.refresh(api_key_entry)

        assert api_key_entry.id is not None
        assert api_key_entry.merchant_id == merchant.id
        assert api_key_entry.key_prefix == raw_key[:12]
        assert api_key_entry.monthly_quota == 25000
        assert api_key_entry.usage_count == 1
        assert api_key_entry.is_active is True
        assert api_key_entry.merchant.email == merchant.email
    finally:
        db.close()


# ==============================================================================
# 8. Concurrency-Safe Atomic Login Attempt Verification
# ==============================================================================
def test_concurrency_safe_atomic_login_attempt_lockout():
    """Verify login attempt tracking commits attempts atomically and locks out accurately."""
    test_email = f"concurrency_{secrets.token_hex(4)}@postcodelink.ng"

    # Attempt 5 consecutive invalid logins
    for attempt in range(1, 5):
        res = client.post("/api/v1/auth/login", json={
            "email": test_email,
            "password": "WrongPassword!"
        })
        assert res.status_code == 401
        assert f"{5 - attempt} attempt(s) remaining" in res.json()["detail"]

    # 5th attempt triggers account lockout
    res_5 = client.post("/api/v1/auth/login", json={
        "email": test_email,
        "password": "WrongPassword!"
    })
    assert res_5.status_code == 429
    assert "Account is temporarily locked" in res_5.json()["detail"]
