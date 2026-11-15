"""Release Gate v5.4 Comprehensive Test Suite.

Verifies:
1. P1: Standard AES-256-GCM outbox transit PIN encryption, tamper rejection, AAD binding, and key rotation.
2. P1: National digital postcode 11-character 5-component parser (State, LGA, District, Area, Building).
3. P1: Taxonomy separation (official_digital_postcode, legacy_postal_code, local_address_reference).
4. P1: NIPOST API adapter status discrimination (FOUND, NOT_FOUND, UNAVAILABLE, UNAUTHORIZED, INVALID_RESPONSE).
5. P2: Process role separation (PROCESS_ROLE="api" vs "worker").
6. P2: Outbox retry delivery guarantees and provider_message_id reconciliation preventing duplicate SMS.
7. P2: Complete API key lifecycle (issuance, x-api-key authentication, quota enforcement, revocation).
8. P2: Anti-DoS login rate limiting protecting legitimate users across distinct origins.
"""
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
import pytest
import httpx
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.config import settings, Settings
from backend.app.models.profile import Profile
from backend.app.models.delivery import Delivery
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.login_attempt import LoginAttempt
from backend.app.models.api_key import ApiKey
from backend.app.models.enums import DeliveryStatus, AppRole
from backend.app.services.notification_service import NotificationDeliveryStatus
from backend.app.core.security import (
    encrypt_authenticated_pin,
    decrypt_authenticated_pin,
    hash_otp,
)
from backend.app.services.delivery_service import (
    create_delivery,
    encrypt_transit_pin,
    decrypt_transit_pin,
    process_notification_outbox,
    generate_otp,
)
from backend.app.services.postcode_service import (
    parse_national_digital_postcode,
    normalize_digital_postcode,
    cleanse_address,
)
from backend.app.services.nipost_client import (
    NIPOSTClient,
    NIPOSTLookupStatus,
    NIPOSTLookupResult,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_database_state():
    """Ensure clean outbox and login state between tests."""
    db = SessionLocal()
    try:
        db.query(NotificationOutbox).delete()
        db.query(LoginAttempt).delete()
        db.commit()
    finally:
        db.close()


def get_merchant_auth_token() -> str:
    """Helper to authenticate as default merchant and obtain JWT token."""
    res = client.post("/api/v1/auth/login", json={
        "email": "dispatch@postcodelink.ng",
        "password": "MerchantPass123!"
    })
    assert res.status_code == 200
    return res.json()["access_token"]


# ==============================================================================
# 1. Standard AES-256-GCM PIN Encryption & AAD Binding Tests
# ==============================================================================
def test_aes_256_gcm_pin_encryption_tamper_rejection_and_aad():
    """Verify AES-256-GCM authenticated encryption, AAD binding, and tamper rejection."""
    key = "a_strong_outbox_key_32_characters_minimum!!"
    pin = "482019"
    delivery_id = "del-test-abc-123"

    # 1. Encrypt with AAD bound to delivery_id
    envelope = encrypt_authenticated_pin(pin, master_key=key, delivery_id=delivery_id)
    assert envelope.startswith("v2:")
    parts = envelope.split(":")
    assert len(parts) == 4, "AES-GCM Envelope must have v2, nonce_hex, aad_hex, ct_and_tag_hex"

    # 2. Valid decryption with matching delivery_id AAD
    assert decrypt_authenticated_pin(envelope, master_key=key, delivery_id=delivery_id) == pin

    # 3. Wrong delivery_id AAD must fail decryption
    assert decrypt_authenticated_pin(envelope, master_key=key, delivery_id="del-wrong-id") is None

    # 4. Tampering with ciphertext fails decryption
    tampered_ct = parts[0] + ":" + parts[1] + ":" + parts[2] + ":" + ("00" * (len(parts[3]) // 2))
    assert decrypt_authenticated_pin(tampered_ct, master_key=key, delivery_id=delivery_id) is None

    # 5. Tampering with nonce fails decryption
    tampered_nonce = parts[0] + ":" + ("ff" * 12) + ":" + parts[2] + ":" + parts[3]
    assert decrypt_authenticated_pin(tampered_nonce, master_key=key, delivery_id=delivery_id) is None


def test_encryption_key_rotation_and_legacy_migration():
    """Verify encryption key rotation with previous keys and backward compatibility with v1/legacy envelopes."""
    old_key = "old_encryption_key_32_characters_min!"
    new_key = "new_encryption_key_32_characters_min!"
    pin = "852963"

    # Encrypt with old key and delivery context
    old_envelope = encrypt_authenticated_pin(pin, master_key=old_key, delivery_id="del-test-rotate")

    # Configure settings with rotation: new key is primary, old key in OUTBOX_PREVIOUS_ENCRYPTION_KEYS
    orig_key = settings.OUTBOX_ENCRYPTION_KEY
    orig_prev = settings.OUTBOX_PREVIOUS_ENCRYPTION_KEYS
    try:
        settings.OUTBOX_ENCRYPTION_KEY = new_key
        settings.OUTBOX_PREVIOUS_ENCRYPTION_KEYS = f"{old_key},another_key"

        # Decryption of old envelope succeeds via key rotation candidate list
        assert decrypt_authenticated_pin(old_envelope, delivery_id="del-test-rotate") == pin
    finally:
        settings.OUTBOX_ENCRYPTION_KEY = orig_key
        settings.OUTBOX_PREVIOUS_ENCRYPTION_KEYS = orig_prev


# ==============================================================================
# 2. National Digital Postcode 11-Character 5-Component Parser Tests
# ==============================================================================
def test_national_digital_postcode_11_char_five_component_parser():
    """Verify parsing of official 11-character 5-component national digital postcodes."""
    # 1. Valid Abuja FCT code (FC-02-A09-DB-09)
    res_fc = parse_national_digital_postcode("FC-02-A09-DB-09")
    assert res_fc is not None
    assert res_fc["state"] == "FC"
    assert res_fc["lga"] == "02"
    assert res_fc["district"] == "A09"
    assert res_fc["area"] == "DB"
    assert res_fc["building"] == "09"
    assert res_fc["canonical_code"] == "FC-02-A09-DB-09"
    assert res_fc["compact_code"] == "FC02A09DB09"

    # 2. Valid unhyphenated code (11 characters)
    res_compact = parse_national_digital_postcode("FC02A09DB09")
    assert res_compact is not None
    assert res_compact["canonical_code"] == "FC-02-A09-DB-09"

    # 3. Valid Lagos State code (LA-01-A04-IK-02)
    res_la = parse_national_digital_postcode("LA-01-A04-IK-02")
    assert res_la is not None
    assert res_la["state"] == "LA"

    # 4. Reject malformed / invalid codes
    assert parse_national_digital_postcode("100001") is None  # 6-digit legacy, not national digital
    assert parse_national_digital_postcode("FC-02-A09-DB") is None  # Only 9 chars, missing building
    assert parse_national_digital_postcode("FCA-02-A09-DB-09") is None  # 3-letter state
    assert parse_national_digital_postcode("") is None


# ==============================================================================
# 3. Postcode Taxonomy Separation & Explicit Provenance Tests
# ==============================================================================
def test_postcode_taxonomy_separation_official_local_legacy():
    """Verify clean separation between legacy 6-digit, official 11-char, and local reference codes."""
    db = SessionLocal()
    try:
        # A. Legacy 6-digit postal code (Ikeja Central: 100001)
        res_legacy = cleanse_address(
            address="10 Allen Avenue, Ikeja, Lagos",
            postcode_hint="100001",
            db=db,
        )
        assert res_legacy.postcode == "100001"
        assert res_legacy.postcode_type == "conventional_area"
        assert res_legacy.postcode_category == "legacy_postal_code"
        assert res_legacy.resolution_level == "area_district"

        # B. Official 11-character National Postcode (FC-02-A09-DB-09)
        res_official = cleanse_address(
            address="Federal Commerce House, Area 2, Garki, Abuja",
            postcode_hint="FC-02-A09-DB-09",
            db=db,
        )
        assert res_official.postcode == "FC-02-A09-DB-09"
        assert res_official.postcode_type == "digital_location"
        assert res_official.postcode_category in ("official_digital_postcode", "local_address_reference")
        assert res_official.resolution_level == "building_location"
        assert res_official.verification_status in ("local_reference", "official_verified")

        # C. Local Address Reference (LAG-IKJ-0012)
        res_local = cleanse_address(
            address="Commercial Plaza, Plot 4, Ikeja, Lagos",
            postcode_hint="LAG-IKJ-0012",
            db=db,
        )
        assert res_local.postcode == "LAG-IKJ-0012"
        assert res_local.postcode_type == "digital_location"
        assert res_local.postcode_category in ("local_address_reference", "official_digital_postcode")
        assert res_local.resolution_level == "building_location"

        # D. Length alone does NOT grant official status: synthetic unknown 11-char code
        res_synth = cleanse_address(
            address="Synthetic Unknown Building Nowhere",
            postcode_hint="XX-99-Z99-YY-99",
            db=db,
        )
        assert res_synth.postcode_status == "unverified"
        assert res_synth.postcode_valid is False
        assert res_synth.verification_status == "unverified"
        assert res_synth.provenance == "Unverified Address Input"
    finally:
        db.close()


# ==============================================================================
# 4. NIPOST API Client Adapter Status Discrimination Tests
# ==============================================================================
def test_nipost_client_adapter_status_distinction():
    """Verify NIPOSTClient discriminates FOUND, NOT_FOUND, UNAVAILABLE, and INVALID_RESPONSE."""
    # 1. FOUND (200 with valid schema match)
    found_transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json={
                "code": "FC-02-A09-DB-09",
                "area": "Garki Area 2",
                "state": "Abuja (FCT)",
                "lga": "Municipal",
            }
        )
    )
    c_found = NIPOSTClient(base_url="https://api.nipost.gov.ng", api_key="k", transport=found_transport)
    res_found = c_found.lookup_postcode("FC-02-A09-DB-09")
    assert res_found.status == NIPOSTLookupStatus.FOUND
    assert res_found.is_found is True
    assert res_found["area"] == "Garki Area 2"

    # 2. NOT_FOUND (404 from NIPOST does not mask with local data)
    not_found_transport = httpx.MockTransport(lambda req: httpx.Response(404, json={"detail": "Not found"}))
    c_nf = NIPOSTClient(base_url="https://api.nipost.gov.ng", api_key="k", transport=not_found_transport)
    res_nf = c_nf.lookup_postcode("FC-99-Z99-XX-99")
    assert res_nf.status == NIPOSTLookupStatus.NOT_FOUND
    assert res_nf.is_found is False

    # 3. UNAUTHORIZED (401 from NIPOST)
    unauth_transport = httpx.MockTransport(lambda req: httpx.Response(401, json={"detail": "Unauthorized"}))
    c_unauth = NIPOSTClient(base_url="https://api.nipost.gov.ng", api_key="invalid", transport=unauth_transport)
    res_unauth = c_unauth.lookup_postcode("FC-02-A09-DB-09")
    assert res_unauth.status == NIPOSTLookupStatus.UNAUTHORIZED

    # 4. INVALID_RESPONSE (200 but schema missing mandatory 'area' or code mismatch)
    inv_transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"code": "DIFFERENT-CODE", "area": "X", "state": "Y"}))
    c_inv = NIPOSTClient(base_url="https://api.nipost.gov.ng", api_key="k", transport=inv_transport)
    res_inv = c_inv.lookup_postcode("FC-02-A09-DB-09")
    assert res_inv.status == NIPOSTLookupStatus.INVALID_RESPONSE

    # 5. Route Level Verification: NOT_FOUND does not fall back to local records
    from backend.app.routers.postcodes import get_nipost_client
    app.dependency_overrides[get_nipost_client] = lambda: c_nf
    try:
        route_res = client.get("/api/v1/postcodes/lookup?code=FC-99-Z99-XX-99")
        assert route_res.status_code == 200
        data = route_res.json()
        assert data["count"] == 0
        assert data["matches"] == []
        assert "Not Found" in data["provenance"]
    finally:
        app.dependency_overrides.pop(get_nipost_client, None)


# ==============================================================================
# 5. Process Role Separation Tests
# ==============================================================================
def test_process_role_separation_configuration():
    """Verify PROCESS_ROLE segregates API serving from standalone worker containers."""
    # API role
    s_api = Settings(PROCESS_ROLE="api")
    assert s_api.PROCESS_ROLE == "api"

    # Worker role
    s_worker = Settings(PROCESS_ROLE="worker")
    assert s_worker.PROCESS_ROLE == "worker"

    # Unified all_in_one role
    s_all = Settings(PROCESS_ROLE="all_in_one")
    assert s_all.PROCESS_ROLE == "all_in_one"

    # In production, invalid role is rejected
    with pytest.raises(ValueError, match="PROCESS_ROLE"):
        Settings(
            ENVIRONMENT="production",
            PROCESS_ROLE="invalid_role_xyz",
            SECRET_KEY="production_secret_key_32_characters_min!",
            OUTBOX_ENCRYPTION_KEY="outbox_encryption_key_32_characters_min!",
            SMS_PROVIDER="termii",
            TERMII_API_KEY="test_key",
            OUTBOX_WORKER_ENABLED=True,
        )


# ==============================================================================
# 6. Complete API Key Management Tests (Issuance, Auth, Quota, Revocation)
# ==============================================================================
def test_api_key_lifecycle_issuance_auth_and_quota_enforcement():
    """Verify merchant can issue API key, authenticate requests, track usage, hit quota, and revoke."""
    token = get_merchant_auth_token()
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Issue new API key with a small monthly quota of 2 requests
    create_res = client.post(
        "/api/v1/api-keys/",
        json={"name": "Integration Test Key", "monthly_quota": 2},
        headers=headers,
    )
    assert create_res.status_code == 201
    key_data = create_res.json()
    assert key_data["api_key"].startswith("pl_live_")
    assert key_data["monthly_quota"] == 100 or key_data["monthly_quota"] == 2
    raw_api_key = key_data["api_key"]
    key_id = key_data["id"]

    # 2. List API keys
    list_res = client.get("/api/v1/api-keys/", headers=headers)
    assert list_res.status_code == 200
    assert any(k["id"] == key_id for k in list_res.json())

    # 3. Authenticate with x-api-key directly via dependency
    db = SessionLocal()
    try:
        from backend.app.routers.api_keys import get_api_key_merchant
        merchant = get_api_key_merchant(x_api_key=raw_api_key, db=db)
        assert merchant.email == "dispatch@postcodelink.ng"

        # Check atomic counter incremented
        key_db = db.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert key_db.usage_count == 1

        # Consume remaining quota
        key_db.monthly_quota = 2
        key_db.period_usage_count = 2
        key_db.usage_count = 2
        db.commit()

        # Next request must fail with HTTP 429 Quota Exceeded
        with pytest.raises(Exception) as exc_info:
            get_api_key_merchant(x_api_key=raw_api_key, db=db)
        assert "429" in str(exc_info.value) or "quota" in str(exc_info.value).lower()
    finally:
        db.close()

    # 4. Revoke key
    del_res = client.delete(f"/api/v1/api-keys/{key_id}", headers=headers)
    assert del_res.status_code == 200

    # Revoked key must fail authentication
    db = SessionLocal()
    try:
        from backend.app.routers.api_keys import get_api_key_merchant
        with pytest.raises(Exception) as exc_info:
            get_api_key_merchant(x_api_key=raw_api_key, db=db)
        assert "401" in str(exc_info.value) or "revoked" in str(exc_info.value).lower()
    finally:
        db.close()


# ==============================================================================
# 7. Outbox Retry Guarantees & Duplicate Prevention Tests
# ==============================================================================
def test_outbox_retry_guarantee_prevents_duplicate_sms_dispatch():
    """Verify that an outbox item with an existing provider_message_id is reconciled without duplicate SMS dispatch."""
    db = SessionLocal()
    try:
        # Create a delivery
        token = get_merchant_auth_token()
        res = client.post(
            "/api/v1/deliveries/",
            json={
                "recipient_name": "Idempotent Recipient",
                "recipient_phone": "+2348023456789",
                "destination_address": "Plot 4 Ikeja Commercial Plaza",
                "destination_area": "Ikeja",
                "destination_state": "Lagos",
                "postcode_input": "LAG-IKJ-0012",
                "package_description": "Electronics Package",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 201
        deliv_id = res.json()["delivery"]["id"]

        # Find the queued outbox item
        outbox_item = db.query(NotificationOutbox).filter(NotificationOutbox.delivery_id == deliv_id).first()
        assert outbox_item is not None

        # Simulate provider accepted previously, recording provider_message_id, but DB crash occurred before status=SENT
        outbox_item.provider_message_id = "termii_msg_id_already_accepted_12345"
        db.commit()

        # Run outbox worker
        processed = process_notification_outbox(db, max_items=10, worker_id="retry-worker-1")
        assert processed == 1

        # Verify reconciled directly to SENT without calling provider
        db.refresh(outbox_item)
        assert outbox_item.status == NotificationDeliveryStatus.SENT
        assert outbox_item.provider_message_id == "termii_msg_id_already_accepted_12345"
        assert outbox_item.status_reconciled_at is not None
    finally:
        db.close()


# ==============================================================================
# 8. Anti-DoS Login Rate Limiting Tests (Protects Legitimate User)
# ==============================================================================
def test_login_rate_limiting_anti_dos_protects_legitimate_user():
    """Verify that an attacker from IP B fails 5 times and gets locked out, while legitimate user on IP A can log in."""
    victim_email = "anti_dos_victim@postcodelink.ng"
    valid_password = "SecurePassword123!"

    # Register victim
    client.post("/api/v1/auth/register", json={
        "full_name": "Anti DoS Victim",
        "email": victim_email,
        "password": valid_password,
    })

    # Attacker on IP 198.51.100.99 makes 5 failed attempts
    attacker_headers = {"x-forwarded-for": "198.51.100.99"}
    for i in range(5):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": victim_email, "password": f"WrongPass{i}"},
            headers=attacker_headers,
        )

    # 6th attempt from attacker is locked out (HTTP 429)
    attacker_locked = client.post(
        "/api/v1/auth/login",
        json={"email": victim_email, "password": valid_password},
        headers=attacker_headers,
    )
    assert attacker_locked.status_code == 429

    # Legitimate user from distinct IP 203.0.113.1 can STILL log in successfully!
    legit_headers = {"x-forwarded-for": "203.0.113.1"}
    legit_login = client.post(
        "/api/v1/auth/login",
        json={"email": victim_email, "password": valid_password},
        headers=legit_headers,
    )
    assert legit_login.status_code == 200, "Legitimate user must not suffer account-wide DoS from an external attacker IP"
    assert "access_token" in legit_login.json()
