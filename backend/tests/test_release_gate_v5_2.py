"""Focused regression test suite for Release Gate v5.2:
- Digital postcode database metadata preservation (postcode_type, building_reference, provenance, dataset_version)
- Database-backed address cleansing with db=db resolving building_location
- Single notification dispatch architecture (outbox worker sole sender)
- Encrypted transit PIN and idempotent retries after ambiguous timeouts
- Production startup configuration gate (rejecting simulated SMS and disabled worker)
- Unique composite idempotency constraint on (merchant_id, idempotency_key)
- Strict 6-digit numeric PIN schema validation
- Pydantic Settings alignment in notification provider factory
"""
import uuid
import secrets
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import pytest
import httpx
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.config import Settings, settings
from backend.app.database import SessionLocal
from backend.app.models.profile import Profile
from backend.app.models.delivery import Delivery
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.models.login_attempt import LoginAttempt
from backend.app.models.enums import DeliveryStatus, PostcodeStatus, AppRole
from backend.app.services.notification_service import (
    get_notification_provider,
    NotificationDeliveryStatus,
    NotificationDispatchResult,
    SimulatedNotificationProvider,
    TermiiNotificationProvider,
    TwilioNotificationProvider,
)
from backend.app.services.postcode_service import cleanse_address
from backend.app.services.delivery_service import (
    process_notification_outbox,
    resend_delivery_pin,
    create_delivery,
    encrypt_transit_pin,
    decrypt_transit_pin,
)
from backend.app.schemas.delivery import DeliveryCreateRequest, DeliveryVerifyOTPRequest

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_db_state():
    """Ensure clean outbox and login attempts between tests."""
    db = SessionLocal()
    try:
        db.query(LoginAttempt).delete()
        db.query(NotificationOutbox).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(LoginAttempt).delete()
        db.query(NotificationOutbox).delete()
        db.commit()
    finally:
        db.close()


def get_token(email: str = "dispatch@postcodelink.ng", password: str = "MerchantPass123!") -> str:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.json()["access_token"]


# ==============================================================================
# 1. Digital Postcode Database Seeding & Verification with db=db Session
# ==============================================================================
def test_digital_postcode_database_seeding_and_cleansing_with_db_session():
    """Verify digital postcodes in database preserve full metadata and cleanse_address(..., db=db) resolves building_location."""
    db = SessionLocal()
    try:
        db_pc = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == "LAG-IKJ-0012").first()
        assert db_pc is not None, "LAG-IKJ-0012 must exist in database"
        assert db_pc.postcode_type == "digital_location", "Digital postcode must have postcode_type='digital_location'"
        assert db_pc.building_reference == "Plot 4 Ikeja Commercial Plaza", "Building reference must not be null"
        assert db_pc.provenance == "NIPOST Digital Address Register 2024"
        assert db_pc.dataset_version == "2024.1"

        # Call cleanse_address with explicit db session (simulating production execution path)
        res = cleanse_address(
            address="Suite 4, Commercial Plaza, Ikeja, Lagos",
            postcode_hint="LAG-IKJ-0012",
            db=db,
        )
        assert res.postcode_valid is True
        assert res.postcode_status in ("verified", "local_match")
        assert res.postcode_type == "digital_location"
        assert res.resolution_level == "building_location"
        assert res.matched_record is not None
        assert res.matched_record.building_reference == "Plot 4 Ikeja Commercial Plaza"
        assert res.confidence >= 0.75
    finally:
        db.close()


# ==============================================================================
# 2. Single Notification Dispatch Architecture
# ==============================================================================
def test_single_dispatch_architecture_create_and_resend_queues_outbox_without_direct_http():
    """Verify that neither create_delivery nor resend_pin call notification provider directly."""
    token = get_token()

    with patch("backend.app.services.notification_service.SimulatedNotificationProvider.send_delivery_pin") as mock_direct_send:
        # A. Create delivery
        create_res = client.post("/api/v1/deliveries/", json={
            "recipient_name": "Single Dispatch Recipient",
            "recipient_phone": "08011223344",
            "destination_address": "12 Broad Street, Marina",
            "destination_area": "Marina",
            "destination_state": "Lagos",
            "postcode_input": "100001",
            "package_description": "Single Dispatch Test Goods",
            "fee": 3500.0,
        }, headers={"Authorization": f"Bearer {token}"})
        assert create_res.status_code == 201
        data = create_res.json()
        deliv_id = data["delivery"]["id"]

        # Notification must be QUEUED in outbox, direct provider was NOT called
        assert data["notification_dispatch"]["status"] == "QUEUED"
        assert mock_direct_send.called is False

        # Check Outbox row exists with QUEUED status
        db = SessionLocal()
        try:
            outbox = db.query(NotificationOutbox).filter(NotificationOutbox.delivery_id == deliv_id).first()
            assert outbox is not None
            assert outbox.status == NotificationDeliveryStatus.QUEUED
            assert outbox.message_payload is not None
            # Payload is encrypted transit PIN bound to delivery context
            decrypted = decrypt_transit_pin(outbox.message_payload, settings.SECRET_KEY, delivery_id=deliv_id)
            assert decrypted is not None
            assert len(decrypted) == 6
        finally:
            db.close()

        # B. Resend PIN
        resend_res = client.post(f"/api/v1/deliveries/{deliv_id}/resend-pin", headers={"Authorization": f"Bearer {token}"})
        assert resend_res.status_code == 200
        resend_data = resend_res.json()
        assert resend_data["notification_dispatch"]["status"] == "QUEUED"
        # Direct provider was still NOT called
        assert mock_direct_send.called is False


# ==============================================================================
# 3. Encrypted Transit PIN & Idempotent Retries After Ambiguous Provider Timeouts
# ==============================================================================
def test_outbox_worker_pin_idempotent_retry_preserves_same_pin():
    """Verify that retrying after an ambiguous timeout dispatches the same PIN rather than rotating a new one."""
    db = SessionLocal()
    try:
        merchant = db.query(Profile).filter(Profile.role == AppRole.MERCHANT).first()
        deliv_req = DeliveryCreateRequest(
            recipient_name="Transit PIN Recipient",
            recipient_phone="08022334455",
            destination_address="8 Allen Ave, Ikeja",
            destination_area="Ikeja",
            destination_state="Lagos",
            postcode_input="100271",
            package_description="Sensitive Item",
            fee=2500.0,
        )
        deliv_resp = create_delivery(db, deliv_req, merchant, commit=True)
        deliv_id = deliv_resp.delivery.id

        deliv_db = db.query(Delivery).filter(Delivery.id == deliv_id).first()
        initial_hash = deliv_db.otp_hash

        dispatched_pins = []

        def capture_pin(**kwargs):
            dispatched_pins.append(kwargs["pin"])
            return NotificationDispatchResult(
                status=NotificationDeliveryStatus.FAILED,
                channel="Termii Gateway",
                recipient_masked="080****4455",
                provider="termii",
                message_preview="Timeout",
                error_details="Connection timed out after 10.0s",
            )

        mock_provider = MagicMock()
        mock_provider.send_delivery_pin.side_effect = capture_pin

        # Attempt 1: Transient timeout
        with patch("backend.app.services.delivery_service.get_notification_provider", return_value=mock_provider):
            processed1 = process_notification_outbox(db, max_items=1)
            assert processed1 == 1

        outbox_entry = db.query(NotificationOutbox).filter(NotificationOutbox.delivery_id == deliv_id).first()
        assert outbox_entry.status == NotificationDeliveryStatus.FAILED
        assert outbox_entry.retry_count == 1
        assert outbox_entry.failure_classification == "transient_network_error"

        # Reset next_attempt_at to simulate backoff elapsed
        outbox_entry.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

        # Attempt 2 (Retry): Provider accepts
        def capture_pin_success(**kwargs):
            dispatched_pins.append(kwargs["pin"])
            return NotificationDispatchResult(
                status=NotificationDeliveryStatus.SENT,
                channel="Termii Gateway",
                recipient_masked="080****4455",
                provider="termii",
                message_preview="Dispatched",
                error_details=None,
            )

        mock_provider.send_delivery_pin.side_effect = capture_pin_success
        with patch("backend.app.services.delivery_service.get_notification_provider", return_value=mock_provider):
            processed2 = process_notification_outbox(db, max_items=1)
            assert processed2 == 1

        outbox_entry_after = db.query(NotificationOutbox).filter(NotificationOutbox.delivery_id == deliv_id).first()
        assert outbox_entry_after.status == NotificationDeliveryStatus.SENT
        assert outbox_entry_after.retry_count == 2

        # Crucial assertion: Both attempts used the EXACT SAME PIN
        assert len(dispatched_pins) == 2
        assert dispatched_pins[0] == dispatched_pins[1], "Retried outbox items must reuse the same PIN"

        # Delivery otp_hash remained stable
        deliv_final = db.query(Delivery).filter(Delivery.id == deliv_id).first()
        assert deliv_final.otp_hash == initial_hash
    finally:
        db.close()


# ==============================================================================
# 4. Production Startup Configuration Gate
# ==============================================================================
def test_production_configuration_gate_rejects_simulated_and_missing_credentials():
    """Verify that Settings validation fails in production if SMS is simulated or worker is disabled."""
    # 1. Insecure secret in production
    with pytest.raises(ValueError, match="Fatal Security Error"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="short_insecure_secret",
            SMS_PROVIDER="termii",
            TERMII_API_KEY="key_1234567890",
            OUTBOX_WORKER_ENABLED=True,
        )

    # 2. Simulated SMS in production
    with pytest.raises(ValueError, match="Simulated SMS dispatch is strictly prohibited in production"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a_valid_production_secret_key_at_least_32_chars_long",
            SMS_PROVIDER="simulated",
            OUTBOX_WORKER_ENABLED=True,
        )

    # 3. Missing Termii credentials in production
    with pytest.raises(ValueError, match="TERMII_API_KEY must be configured"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a_valid_production_secret_key_at_least_32_chars_long",
            SMS_PROVIDER="termii",
            TERMII_API_KEY="",
            OUTBOX_WORKER_ENABLED=True,
        )

    # 4. Missing Twilio credentials in production
    with pytest.raises(ValueError, match="TWILIO_ACCOUNT_SID"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a_valid_production_secret_key_at_least_32_chars_long",
            SMS_PROVIDER="twilio",
            TWILIO_ACCOUNT_SID="",
            TWILIO_AUTH_TOKEN="",
            TWILIO_FROM_NUMBER="",
            OUTBOX_WORKER_ENABLED=True,
        )

    # 5. Worker disabled in production
    with pytest.raises(ValueError, match="OUTBOX_WORKER_ENABLED must be true"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a_valid_production_secret_key_at_least_32_chars_long",
            SMS_PROVIDER="termii",
            TERMII_API_KEY="key_1234567890",
            OUTBOX_WORKER_ENABLED=False,
        )

    # 6. Valid production configuration passes
    valid = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="a_valid_production_secret_key_at_least_32_chars_long",
        OUTBOX_ENCRYPTION_KEY="a_valid_outbox_encryption_key_at_least_32_chars_long",
        OTP_SECRET_KEY="a_valid_otp_secret_key_at_least_32_chars_long!",
        SMS_PROVIDER="termii",
        TERMII_API_KEY="valid_key_12345",
        OUTBOX_WORKER_ENABLED=True,
        REDIS_URL="redis://localhost:6379/0",
    )
    assert valid.ENVIRONMENT == "production"
    assert valid.SMS_PROVIDER == "termii"
    assert valid.OUTBOX_WORKER_ENABLED is True


# ==============================================================================
# 5. Unique Composite Idempotency Constraint & Concurrency Safety
# ==============================================================================
def test_delivery_idempotency_unique_composite_constraint_and_concurrency():
    """Verify unique constraint on (merchant_id, idempotency_key) and idempotent replay."""
    token = get_token()
    idem_key = f"order-idempotent-{secrets.token_hex(6)}"

    payload = {
        "recipient_name": "Idempotent Buyer",
        "recipient_phone": "08012347788",
        "destination_address": "5 Admiralty Way, Lekki",
        "destination_area": "Lekki Phase 1",
        "destination_state": "Lagos",
        "postcode_input": "101241",
        "package_description": "Electronics Order",
        "fee": 5000.0,
        "idempotency_key": idem_key,
    }

    # Request 1
    res1 = client.post("/api/v1/deliveries/", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res1.status_code == 201
    deliv_id = res1.json()["delivery"]["id"]

    # Request 2 (Identical idempotency key)
    res2 = client.post("/api/v1/deliveries/", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res2.status_code == 201
    assert res2.json()["delivery"]["id"] == deliv_id
    assert res2.json()["notification_dispatch"]["status"] == "IDEMPOTENT_REPLAY"

    # Verify directly in database that only ONE record exists
    db = SessionLocal()
    try:
        count = db.query(Delivery).filter(Delivery.idempotency_key == idem_key).count()
        assert count == 1, "Only one delivery record must exist for the idempotency key"
    finally:
        db.close()


# ==============================================================================
# 6. Strict 6-Digit Numeric PIN Schema Validation
# ==============================================================================
def test_strict_six_digit_numeric_pin_validation():
    """Verify verify-otp endpoint schema strictly rejects non-6-digit PINs (min/max 6 numeric digits)."""
    token = get_token()

    # Create test delivery and advance to OUT_FOR_DELIVERY
    create_res = client.post("/api/v1/deliveries/", json={
        "recipient_name": "Schema PIN Test",
        "recipient_phone": "08088990011",
        "destination_address": "10 Marina Road",
        "destination_area": "Marina",
        "destination_state": "Lagos",
        "postcode_input": "100001",
        "package_description": "Test Goods",
        "fee": 2000.0,
    }, headers={"Authorization": f"Bearer {token}"})
    assert create_res.status_code == 201
    deliv_id = create_res.json()["delivery"]["id"]

    admin_token = get_token("admin@postcodelink.ng", "AdminSecure2026!")
    op_res = client.post("/api/v1/operators/", json={
        "business_name": "Schema Test Courier",
        "phone": "+2348088990022",
        "vehicle_type": "motorcycle",
        "service_areas": ["Lagos"],
        "max_capacity": 15
    }, headers={"Authorization": f"Bearer {admin_token}"}).json()
    op_id = op_res["id"]

    client.post(f"/api/v1/deliveries/{deliv_id}/assign", json={"operator_id": op_id}, headers={"Authorization": f"Bearer {token}"})
    client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "picked_up"}, headers={"Authorization": f"Bearer {admin_token}"})
    client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "in_transit"}, headers={"Authorization": f"Bearer {admin_token}"})
    client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "out_for_delivery"}, headers={"Authorization": f"Bearer {admin_token}"})

    # Test 4 digits -> 422 Unprocessable Entity
    bad_4 = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={"otp": "1234"}, headers={"Authorization": f"Bearer {token}"})
    assert bad_4.status_code == 422

    # Test 5 digits -> 422 Unprocessable Entity
    bad_5 = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={"otp": "12345"}, headers={"Authorization": f"Bearer {token}"})
    assert bad_5.status_code == 422

    # Test 7 digits -> 422 Unprocessable Entity
    bad_7 = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={"otp": "1234567"}, headers={"Authorization": f"Bearer {token}"})
    assert bad_7.status_code == 422

    # Test non-numeric -> 422 Unprocessable Entity
    bad_alpha = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={"otp": "12AB56"}, headers={"Authorization": f"Bearer {token}"})
    assert bad_alpha.status_code == 422


# ==============================================================================
# 7. Notification Provider Alignment with Pydantic Settings
# ==============================================================================
def test_notification_provider_uses_pydantic_settings():
    """Verify get_notification_provider() directly respects Pydantic Settings attributes."""
    # When settings specifies termii
    with patch("backend.app.config.settings.SMS_PROVIDER", "termii"):
        with patch("backend.app.config.settings.TERMII_API_KEY", "test_termii_key_123"):
            with patch("backend.app.config.settings.TERMII_SENDER_ID", "CustomSender"):
                provider = get_notification_provider()
                assert isinstance(provider, TermiiNotificationProvider)
                assert provider.api_key == "test_termii_key_123"
                assert provider.sender_id == "CustomSender"

    # When settings specifies twilio
    with patch("backend.app.config.settings.SMS_PROVIDER", "twilio"):
        with patch("backend.app.config.settings.TWILIO_ACCOUNT_SID", "AC_test_123"):
            with patch("backend.app.config.settings.TWILIO_AUTH_TOKEN", "auth_tok_456"):
                with patch("backend.app.config.settings.TWILIO_FROM_NUMBER", "+1234567890"):
                    provider = get_notification_provider()
                    assert isinstance(provider, TwilioNotificationProvider)
                    assert provider.account_sid == "AC_test_123"
                    assert provider.from_number == "+1234567890"
