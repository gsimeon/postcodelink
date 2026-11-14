"""Focused automated regression tests for Release Gate v5 enhancements:
- Strict Termii provider acknowledgement validation (code == 'ok' AND message_id)
- E.164 phone normalization and validation
- Database-first postcode cleansing and national directory synchronization
- 11-character digital postcode vs 6-digit conventional area separation
- Outbox worker leasing, exponential backoff, and error classification
- Secure PIN resend service and API endpoint
- Persistent, database-backed login rate limiting (LoginAttempt)
- Atomic bulk delivery creation with structured per-item reporting
"""
import uuid
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import pytest
import httpx
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.profile import Profile
from backend.app.models.delivery import Delivery
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.models.login_attempt import LoginAttempt
from backend.app.models.enums import DeliveryStatus, AppRole
from backend.app.services.notification_service import (
    TermiiNotificationProvider,
    TwilioNotificationProvider,
    NotificationDeliveryStatus,
    normalize_nigerian_phone,
)
from backend.app.services.postcode_service import cleanse_address, find_postcodes
from backend.app.services.delivery_service import (
    process_notification_outbox,
    resend_delivery_pin,
    create_delivery,
)
from backend.app.schemas.delivery import DeliveryCreateRequest

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_login_attempts():
    db = SessionLocal()
    try:
        db.query(LoginAttempt).delete()
        db.commit()
    finally:
        db.close()


def get_token(email: str = "dispatch@postcodelink.ng", password: str = "MerchantPass123!") -> str:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


# ==============================================================================
# 1. Termii Provider Strict Acknowledgement Matrix
# ==============================================================================
def test_termii_strict_acknowledgement_requires_both_code_and_message_id():
    provider = TermiiNotificationProvider(api_key="test-key", sender_id="PostcodeLnk")

    # Case A: Success - BOTH code == "ok" AND valid message_id -> SENT
    resp_ok = SimpleNamespace(
        status_code=200,
        json=lambda: {"code": "ok", "message_id": "msg-999888"},
        raise_for_status=lambda: None,
    )
    with patch("httpx.post", return_value=resp_ok):
        res_a = provider.send_delivery_pin("08012345678", "Amina", "PL-TEST", "123456")
    assert res_a.status == NotificationDeliveryStatus.SENT
    assert res_a.provider == "termii"

    # Case B: Incomplete - code == "ok" but MISSING message_id -> FAILED
    resp_no_id = SimpleNamespace(
        status_code=200,
        json=lambda: {"code": "ok"},  # No message_id!
        raise_for_status=lambda: None,
    )
    with patch("httpx.post", return_value=resp_no_id):
        res_b = provider.send_delivery_pin("08012345678", "Amina", "PL-TEST", "123456")
    assert res_b.status == NotificationDeliveryStatus.FAILED
    assert "omitted message id" in (res_b.error_details or "").lower() or "incomplete" in (res_b.error_details or "").lower()

    # Case C: Failed code with message_id -> FAILED
    resp_bad_code = SimpleNamespace(
        status_code=200,
        json=lambda: {"code": "102", "message_id": "msg-000", "message": "Invalid Destination"},
        raise_for_status=lambda: None,
    )
    with patch("httpx.post", return_value=resp_bad_code):
        res_c = provider.send_delivery_pin("08012345678", "Amina", "PL-TEST", "123456")
    assert res_c.status == NotificationDeliveryStatus.FAILED
    assert "Invalid Destination" in (res_c.error_details or "")

    # Case D: Unparseable/invalid JSON -> FAILED
    resp_invalid_json = SimpleNamespace(
        status_code=200,
        json=lambda: "plain text string, not json dict",
        raise_for_status=lambda: None,
    )
    with patch("httpx.post", return_value=resp_invalid_json):
        res_d = provider.send_delivery_pin("08012345678", "Amina", "PL-TEST", "123456")
    assert res_d.status == NotificationDeliveryStatus.FAILED
    assert "invalid" in (res_d.error_details or "").lower()

    # Case E: HTTP 500 server error -> FAILED
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.raise_for_status.side_effect = httpx.HTTPStatusError("500 Internal Error", request=MagicMock(), response=resp_500)
    with patch("httpx.post", return_value=resp_500):
        res_e = provider.send_delivery_pin("08012345678", "Amina", "PL-TEST", "123456")
    assert res_e.status == NotificationDeliveryStatus.FAILED

    # Case F: Timeout -> FAILED
    with patch("httpx.post", side_effect=httpx.TimeoutException("Read timeout")):
        res_f = provider.send_delivery_pin("08012345678", "Amina", "PL-TEST", "123456")
    assert res_f.status == NotificationDeliveryStatus.FAILED


# ==============================================================================
# 2. Phone Number Normalization & Validation Matrix
# ==============================================================================
def test_phone_number_normalization_e164_and_validation():
    # 11-digit local format
    e164_1, msisdn_1 = normalize_nigerian_phone("08031234567")
    assert e164_1 == "+2348031234567"
    assert msisdn_1 == "2348031234567"

    # +234 prefixed format
    e164_2, msisdn_2 = normalize_nigerian_phone("+2348031234567")
    assert e164_2 == "+2348031234567"
    assert msisdn_2 == "2348031234567"

    # 234 standalone format
    e164_3, msisdn_3 = normalize_nigerian_phone("2348031234567")
    assert e164_3 == "+2348031234567"
    assert msisdn_3 == "2348031234567"

    # Spaced / dashed format
    e164_4, msisdn_4 = normalize_nigerian_phone("080-3123-4567")
    assert e164_4 == "+2348031234567"

    # Invalid formats raise ValueError
    with pytest.raises(ValueError):
        normalize_nigerian_phone("12345")

    with pytest.raises(ValueError):
        normalize_nigerian_phone("not-a-number")

    with pytest.raises(ValueError):
        normalize_nigerian_phone("")

    # Provider rejects invalid phone upfront
    provider = TermiiNotificationProvider(api_key="test-key")
    res = provider.send_delivery_pin("invalid_phone_99", "Recipient", "PL-TEST", "123456")
    assert res.status == NotificationDeliveryStatus.FAILED
    assert "invalid" in (res.error_details or "").lower()


# ==============================================================================
# 3. Database-First Postcode Cleansing & National Directory Synchronization
# ==============================================================================
def test_database_first_postcode_cleansing_and_consistency():
    db = SessionLocal()
    try:
        # Insert a dynamic test postcode directly into the PostgreSQL/SQLite directory
        dynamic_code = "105999"
        dynamic_area = "Epe Modern Pilot Estate"
        existing = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == dynamic_code).first()
        if not existing:
            new_record = PostcodeDirectory(
                code=dynamic_code,
                area=dynamic_area,
                state="Lagos",
                lga="Epe",
                lat=6.5841,
                lng=3.9834,
                is_active=True,
                provenance="NIPOST Pilot Directory v2024.2",
                dataset_version="2024.2"
            )
            db.add(new_record)
            db.commit()

        # Cleansing with db=db MUST match the record from the database
        cleanse_res = cleanse_address(
            address=f"Plot 12 Marina Road, {dynamic_area}, Lagos",
            postcode_hint=dynamic_code,
            db=db,
        )

        assert cleanse_res.postcode_status == "verified"
        assert cleanse_res.postcode == dynamic_code
        assert cleanse_res.area == dynamic_area
        assert cleanse_res.source == "postgresql_postcode_directory"
        assert cleanse_res.matched_record is not None
        assert cleanse_res.matched_record.area == dynamic_area

        # Postcode lookup also returns the same database record
        lookup_matches = find_postcodes(db=db, code=dynamic_code)
        assert len(lookup_matches) >= 1
        assert lookup_matches[0].code == dynamic_code
        assert lookup_matches[0].area == dynamic_area
    finally:
        db.close()


# ==============================================================================
# 4. 11-Character Digital Postcode vs 6-Digit Conventional Postcode Support
# ==============================================================================
def test_digital_postcode_eleven_char_recognition():
    # 1. 11-character alphanumeric digital postcode (building/location level)
    digital_code = "LAG-IKJ-0012"  # 11 alphanumeric characters
    res_digital = cleanse_address(
        address="Suite 4, Ikeja Business Center, Lagos",
        postcode_hint=digital_code,
    )
    assert res_digital.postcode_type == "digital_location"
    assert res_digital.resolution_level == "building_location"

    # 2. Conventional 6-digit postcode (postal area level)
    conventional_code = "101241"
    res_conventional = cleanse_address(
        address="14 Admiralty Way, Lekki Phase 1, Lagos",
        postcode_hint=conventional_code,
    )
    assert res_conventional.postcode_type == "conventional_area"
    assert res_conventional.resolution_level == "area_district"


# ==============================================================================
# 5. Outbox Worker Leasing, Retries & Error Classification
# ==============================================================================
def test_outbox_leasing_and_exponential_backoff():
    db = SessionLocal()
    try:
        # Create a mock delivery order
        merchant = db.query(Profile).filter(Profile.role == AppRole.MERCHANT).first()
        assert merchant is not None

        deliv = Delivery(
            id=f"PL-2026-OUTBOX-{uuid.uuid4().hex[:6].upper()}",
            merchant_id=merchant.id,
            recipient_name="Outbox Worker Recipient",
            recipient_phone="08012349999",
            destination_address="10 Test Street",
            destination_area="Ikeja",
            destination_state="Lagos",
            postcode_input="100001",
            package_description="Outbox Test Package",
            fee=2500.0,
            status=DeliveryStatus.PENDING,
            otp_hash="HASHED_PIN",
        )
        db.add(deliv)
        db.commit()

        # Create failed outbox record with transient error
        outbox_entry = NotificationOutbox(
            delivery_id=deliv.id,
            channel="SMS",
            recipient_phone="08012349999",
            provider="termii",
            status=NotificationDeliveryStatus.FAILED,
            error_details="Connection timed out after 10.0s",
            retry_count=0,
            max_retries=3,
        )
        db.add(outbox_entry)
        db.commit()
        db.refresh(outbox_entry)

        # Process outbox with worker lease
        worker_id = "test-worker-alpha"
        processed = process_notification_outbox(db, max_items=10, worker_id=worker_id)
        assert processed >= 1

        db.refresh(outbox_entry)
        assert outbox_entry.retry_count == 1
        assert outbox_entry.failure_classification == "transient_network_error"
        assert outbox_entry.next_attempt_at is not None
        # Lease was released
        assert outbox_entry.locked_at is None
        assert outbox_entry.locked_by is None

        # Simulate reaching max retries on next attempt
        outbox_entry.retry_count = 2
        outbox_entry.next_attempt_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

        process_notification_outbox(db, max_items=10, worker_id=worker_id)
        db.refresh(outbox_entry)
        assert outbox_entry.status == NotificationDeliveryStatus.FAILED
        assert outbox_entry.failure_classification == "max_retries_exceeded"
    finally:
        db.close()


# ==============================================================================
# 6. Secure PIN Resend Endpoint
# ==============================================================================
def test_secure_pin_resend_endpoint():
    token = get_token("dispatch@postcodelink.ng", "MerchantPass123!")

    # 1. Create a delivery
    create_res = client.post("/api/v1/deliveries/", json={
        "recipient_name": "PIN Resend Target",
        "recipient_phone": "08055551234",
        "destination_address": "8 Marina Road",
        "destination_area": "Marina",
        "destination_state": "Lagos",
        "postcode": "100001",
        "package_description": "Electronics Resend Test",
        "fee": 3000.0
    }, headers={"Authorization": f"Bearer {token}"})
    assert create_res.status_code == 201
    deliv_id = create_res.json()["delivery"]["id"]

    db = SessionLocal()
    try:
        deliv_before = db.query(Delivery).filter(Delivery.id == deliv_id).first()
        assert deliv_before is not None
        old_hash = deliv_before.otp_hash
    finally:
        db.close()

    # 2. Resend PIN via endpoint
    resend_res = client.post(f"/api/v1/deliveries/{deliv_id}/resend-pin", headers={"Authorization": f"Bearer {token}"})
    assert resend_res.status_code == 200
    resend_data = resend_res.json()
    assert resend_data["notification_dispatch"]["recipient_phone"] == "08055551234"
    assert resend_data["notification_dispatch"]["status"] in ["SENT", "SIMULATED"]

    # 3. Verify in database: PIN hash was rotated securely and attempts reset
    db = SessionLocal()
    try:
        deliv_after = db.query(Delivery).filter(Delivery.id == deliv_id).first()
        assert deliv_after is not None
        assert deliv_after.otp_hash != old_hash
        assert deliv_after.otp_attempts == 0
        assert deliv_after.otp_locked_until is None

        # Outbox has record of otp_resend
        outbox_resend = db.query(NotificationOutbox).filter(
            NotificationOutbox.delivery_id == deliv_id,
            NotificationOutbox.notification_type == "otp_resend"
        ).first()
        assert outbox_resend is not None
    finally:
        db.close()

    # 4. Forbidden for another merchant
    other_email = f"merchant_diff_{uuid.uuid4().hex[:6]}@postcodelink.ng"
    client.post("/api/v1/auth/register", json={
        "full_name": "Different Merchant",
        "email": other_email,
        "password": "MerchantPass123!",
        "business_name": "Diff Hub"
    })
    other_token = get_token(other_email, "MerchantPass123!")
    resend_forbidden = client.post(f"/api/v1/deliveries/{deliv_id}/resend-pin", headers={"Authorization": f"Bearer {other_token}"})
    assert resend_forbidden.status_code == 403


# ==============================================================================
# 7. Database-Backed Login Rate Limiting (LoginAttempt Persistence)
# ==============================================================================
def test_database_backed_login_rate_limiting_persistence():
    target_email = "db_rate_victim@postcodelink.ng"
    client.post("/api/v1/auth/register", json={
        "full_name": "DB Rate Target",
        "email": target_email,
        "password": "SecurePassword123!"
    })

    # Attempts 1-4: Invalid password -> 401 Unauthorized
    for i in range(4):
        resp = client.post("/api/v1/auth/login", json={
            "email": target_email,
            "password": f"WrongPass{i}"
        })
        assert resp.status_code == 401
        assert "attempt(s) remaining" in resp.json()["detail"]

    # Verify rows written to database
    db = SessionLocal()
    try:
        attempts = db.query(LoginAttempt).filter(LoginAttempt.email == target_email).all()
        assert len(attempts) == 4
        assert all(att.is_successful is False for att in attempts)
    finally:
        db.close()

    # Attempt 5: triggers 429 lockout
    resp5 = client.post("/api/v1/auth/login", json={
        "email": target_email,
        "password": "WrongPass5"
    })
    assert resp5.status_code == 429
    assert "locked" in resp5.json()["detail"].lower()

    # Attempt 6 with correct password still locked with 429
    resp6 = client.post("/api/v1/auth/login", json={
        "email": target_email,
        "password": "SecurePassword123!"
    })
    assert resp6.status_code == 429


# ==============================================================================
# 8. Atomic Bulk Delivery Creation with Structured Per-Item Reporting
# ==============================================================================
def test_bulk_delivery_creation_with_per_item_reporting():
    token = get_token("dispatch@postcodelink.ng", "MerchantPass123!")

    bulk_items = [
        {
            "recipient_name": "Bulk Recipient 1",
            "recipient_phone": "08011112222",
            "destination_address": "12 Broad Street",
            "destination_area": "Marina",
            "destination_state": "Lagos",
            "postcode": "100001",
            "package_description": "Bulk Item 1",
            "fee": 2500.0
        },
        {
            "recipient_name": "Bulk Recipient 2",
            "recipient_phone": "08033334444",
            "destination_address": "45 Awolowo Road",
            "destination_area": "Ikoyi",
            "destination_state": "Lagos",
            "postcode": "101233",
            "package_description": "Bulk Item 2",
            "fee": 2500.0
        },
    ]

    bulk_res = client.post(
        "/api/v1/deliveries/bulk?batch_id=test-batch-001",
        json=bulk_items,
        headers={"Authorization": f"Bearer {token}"}
    )
    assert bulk_res.status_code == 201
    data = bulk_res.json()

    assert data["batch_id"] == "test-batch-001"
    assert data["total_items"] == 2
    assert data["successful_count"] == 2
    assert data["failed_count"] == 0
    assert len(data["results"]) == 2
    assert data["results"][0]["success"] is True
    assert data["results"][0]["reference"] is not None
    assert data["results"][1]["success"] is True
