"""v6.3.1 regression tests for OTP expiry, 3-attempt lockout, and strict evidence persistence fail-closed behavior."""
from datetime import datetime, timedelta, timezone
import secrets
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.app.core.security import hash_otp
from backend.app.database import SessionLocal
from backend.app.models.delivery import Delivery
from backend.app.models.enums import AppRole, DeliveryStatus
from backend.app.models.operator import Operator
from backend.app.models.profile import Profile
from backend.app.schemas.delivery import DeliveryVerifyOTPRequest
from backend.app.services.delivery_service import verify_delivery_otp
from backend.app.services.nipost_client import NIPOSTLookupStatus
from backend.app.services.postcode_service import cleanse_address
from backend.app.services.postcodes.evidence import record_verification_evidence


def _seed_otp_delivery(
    db,
    *,
    otp_code: str = "123456",
    otp_expires_at: datetime,
):
    uid = str(uuid.uuid4())
    merchant = Profile(
        id=uid,
        full_name="OTP Test Merchant",
        phone=f"+23480{str(uuid.UUID(uid).int)[:8]}",
        email=f"otp-merchant-{uid[:6]}@test.ng",
        hashed_password="pw",
        role=AppRole.MERCHANT,
    )
    op_uid = str(uuid.uuid4())
    op_profile = Profile(
        id=op_uid,
        full_name="OTP Test Operator",
        phone=f"+23480{str(uuid.UUID(op_uid).int)[:8]}",
        email=f"otp-op-{op_uid[:6]}@test.ng",
        hashed_password="pw",
        role=AppRole.OPERATOR,
    )
    db.add_all([merchant, op_profile])
    db.flush()

    op = Operator(
        id=str(uuid.uuid4()),
        profile_id=op_profile.id,
        business_name="OTP Fleet",
        phone=op_profile.phone,
        service_areas=["Lagos"],
        is_available=True,
    )
    db.add(op)
    db.flush()

    delivery = Delivery(
        id=f"PL-2026-{uuid.uuid4().hex[:6].upper()}",
        tracking_token=secrets.token_urlsafe(24),
        merchant_id=merchant.id,
        operator_id=op.id,
        recipient_name="Tunde Bakare",
        recipient_phone="+2348031112222",
        destination_address="15 Adeola Odeku, Victoria Island, Lagos",
        destination_area="Victoria Island",
        destination_state="Lagos",
        postcode_input="101241",
        package_description="OTP Regression Parcel",
        status=DeliveryStatus.OUT_FOR_DELIVERY,
        otp_hash=hash_otp(otp_code),
        otp_expires_at=otp_expires_at,
        otp_attempts=0,
        otp_max_attempts=3,
        pod_verified=False,
        version=1,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return op_profile, delivery


def test_verify_delivery_otp_rejects_expired_otp():
    db = SessionLocal()
    try:
        op_profile, delivery = _seed_otp_delivery(
            db,
            otp_code="123456",
            otp_expires_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )

        with pytest.raises(HTTPException) as exc_info:
            verify_delivery_otp(
                db=db,
                delivery_id=delivery.id,
                request=DeliveryVerifyOTPRequest(otp="123456"),
                current_user=op_profile,
            )

        assert exc_info.value.status_code == 400
        db.refresh(delivery)
        assert delivery.pod_verified is False
    finally:
        db.close()


def test_verify_delivery_otp_3_attempt_lockout_blocks_even_valid_otp():
    db = SessionLocal()
    try:
        op_profile, delivery = _seed_otp_delivery(
            db,
            otp_code="123456",
            otp_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )

        # Attempts 1 and 2 with wrong OTP
        for expected_attempts in (1, 2):
            with pytest.raises(HTTPException) as exc_info:
                verify_delivery_otp(
                    db=db,
                    delivery_id=delivery.id,
                    request=DeliveryVerifyOTPRequest(otp="000000"),
                    current_user=op_profile,
                )
            assert exc_info.value.status_code in (400, 401)
            db.refresh(delivery)
            assert delivery.otp_attempts == expected_attempts
            assert delivery.otp_locked_until is None

        # Attempt 3 with wrong OTP triggers lockout
        with pytest.raises(HTTPException) as exc_info:
            verify_delivery_otp(
                db=db,
                delivery_id=delivery.id,
                request=DeliveryVerifyOTPRequest(otp="000000"),
                current_user=op_profile,
            )
        assert exc_info.value.status_code in (401, 429)
        db.refresh(delivery)
        assert delivery.otp_attempts == 3
        assert delivery.otp_locked_until is not None

        # Subsequent attempt even with the CORRECT OTP must be rejected with 429 while locked
        with pytest.raises(HTTPException) as locked_exc:
            verify_delivery_otp(
                db=db,
                delivery_id=delivery.id,
                request=DeliveryVerifyOTPRequest(otp="123456"),
                current_user=op_profile,
            )
        assert locked_exc.value.status_code == 429
        db.refresh(delivery)
        assert delivery.pod_verified is False
    finally:
        db.close()


def test_record_verification_evidence_rolls_back_on_commit_failure():
    mock_db = MagicMock()
    mock_db.commit.side_effect = RuntimeError("Simulated DB commit failure")

    persisted, ev_id, valid_until = record_verification_evidence(
        db=mock_db,
        code="101245",
        live_res={"code": "101245", "area": "Ikoyi", "state": "Lagos"},
        ver_method="nipost_live_api",
        upstream_version="2026.1",
        is_validator=False,
        is_sandbox=False,
    )

    assert persisted is False
    assert ev_id is None
    assert valid_until is None
    mock_db.rollback.assert_called_once()


def test_cleanse_address_strict_fails_closed_when_evidence_persistence_fails():
    db = SessionLocal()
    try:
        mock_client = MagicMock()
        mock_client.is_configured = True
        mock_client.configuration_complete = True
        mock_client.is_sandbox = False
        mock_client.is_validator_mode = False
        mock_client.auth_scheme = "bearer"
        mock_client.api_key = "nipost_live_test_secret"
        mock_client.orchestrated_verify.return_value = (
            NIPOSTLookupStatus.FOUND,
            {
                "code": "101245",
                "area": "Ikoyi",
                "state": "Lagos",
                "lga": "Eti-Osa",
                "dataset_version": "2026.1",
            },
            None,
            "nipost_live_api",
        )

        with patch(
            "backend.app.services.postcode_service.record_verification_evidence",
            return_value=(False, None, None),
        ):
            # Strict mode must fail closed with 503
            with pytest.raises(HTTPException) as exc_info:
                cleanse_address(
                    address="22 Bourdillon Road, Ikoyi, Lagos",
                    postcode_hint="101245",
                    db=db,
                    client=mock_client,
                    strict=True,
                    verification_mode="nipost_strict",
                )
            assert exc_info.value.status_code == 503

            # Non-strict mode must downgrade to local_reference and NEVER claim official_verified
            res = cleanse_address(
                address="22 Bourdillon Road, Ikoyi, Lagos",
                postcode_hint="101245",
                db=db,
                client=mock_client,
                strict=False,
                verification_mode="nipost_validate",
            )
            assert res.matched_record is not None
            assert res.matched_record.verification_status == "local_reference"
    finally:
        db.close()
