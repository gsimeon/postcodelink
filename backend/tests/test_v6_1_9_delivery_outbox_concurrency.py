"""v6.1.9 regression tests for delivery tenant isolation, assignment/workload concurrency,
outbox worker leasing & crash recovery, OTP replay protection, and VerificationEvidence immutability.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import uuid
from unittest.mock import patch

from fastapi import HTTPException
import pytest

from backend.app.core.security import hash_otp
from backend.app.database import SessionLocal
from backend.app.models.delivery import Delivery
from backend.app.models.enums import AppRole, DeliveryStatus
from backend.app.models.notification_outbox import NotificationDeliveryStatus, NotificationOutbox
from backend.app.models.operator import Operator
from backend.app.models.profile import Profile
from backend.app.models.verification_evidence import VerificationEvidence
from backend.app.schemas.delivery import (
    DeliveryAssignRequest,
    DeliveryStatusUpdateRequest,
    DeliveryVerifyOTPRequest,
)
from backend.app.services.delivery_service import (
    assign_operator,
    process_notification_outbox,
    update_delivery_status,
    verify_delivery_otp,
)


def _make_merchant(db, tag: str) -> Profile:
    uid = str(uuid.uuid4())
    p = Profile(
        id=uid,
        full_name=f"Merchant {tag}",
        phone=f"+23480{str(uuid.UUID(uid).int)[:8]}",
        email=f"m-{tag}-{uid[:6]}@test.ng",
        hashed_password="pw",
        role=AppRole.MERCHANT,
    )
    db.add(p)
    return p


def _make_operator(db, tag: str, max_active: int = 15) -> Operator:
    uid = str(uuid.uuid4())
    prof = Profile(
        id=uid,
        full_name=f"Operator {tag}",
        phone=f"+23481{str(uuid.UUID(uid).int)[:8]}",
        email=f"op-{tag}-{uid[:6]}@test.ng",
        hashed_password="pw",
        role=AppRole.OPERATOR,
    )
    db.add(prof)
    db.flush()
    op = Operator(
        id=str(uuid.uuid4()),
        profile_id=prof.id,
        business_name=f"Fleet {tag}",
        phone=prof.phone,
        service_areas=["Lagos", "Ikeja"],
        is_available=True,
        max_active_deliveries=max_active,
        active_deliveries_count=0,
        completed_deliveries=0,
    )
    db.add(op)
    return op


def _make_delivery(
    db,
    merchant_id: str,
    status: DeliveryStatus = DeliveryStatus.PENDING,
    operator_id: str | None = None,
    raw_otp: str = "123456",
) -> Delivery:
    d = Delivery(
        id=f"PL-2026-{uuid.uuid4().hex[:6].upper()}",
        tracking_token=f"trk_{uuid.uuid4().hex}",
        merchant_id=merchant_id,
        operator_id=operator_id,
        recipient_name="Test Recipient",
        recipient_phone="+2348099999999",
        destination_address="10 Obafemi Awolowo Way, Ikeja",
        destination_area="Ikeja",
        destination_state="Lagos",
        postcode_input="100001",
        package_description="Test package",
        status=status,
        otp_hash=hash_otp(raw_otp),
        otp_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        otp_attempts=0,
        pod_verified=False,
        version=1,
    )
    db.add(d)
    return d


def test_cross_merchant_delivery_update_and_assignment_blocked():
    db = SessionLocal()
    try:
        m1 = _make_merchant(db, "one")
        m2 = _make_merchant(db, "two")
        op = _make_operator(db, "iso")
        d = _make_delivery(db, m1.id)
        db.commit()

        with pytest.raises(HTTPException) as exc1:
            assign_operator(db, d.id, DeliveryAssignRequest(operator_id=op.id), m2)
        assert exc1.value.status_code == 403

        with pytest.raises(HTTPException) as exc2:
            update_delivery_status(
                db,
                d.id,
                DeliveryStatusUpdateRequest(new_status=DeliveryStatus.CANCELLED),
                m2,
            )
        assert exc2.value.status_code == 403
    finally:
        db.close()


def test_assignment_idempotency_capacity_and_workload_consistency():
    """Verify idempotent same-operator assignment, capacity=1 contention, reassignment, cancellation, and failure counters."""
    db = SessionLocal()
    try:
        m = _make_merchant(db, "cap")
        op_a = _make_operator(db, "A", max_active=1)
        op_b = _make_operator(db, "B", max_active=5)
        d1 = _make_delivery(db, m.id)
        d2 = _make_delivery(db, m.id)
        db.commit()

        # Assign d1 -> op_a (count becomes 1)
        assign_operator(db, d1.id, DeliveryAssignRequest(operator_id=op_a.id), m)
        # Idempotent repeat -> count stays 1
        assign_operator(db, d1.id, DeliveryAssignRequest(operator_id=op_a.id), m)
        db.refresh(op_a)
        assert op_a.active_deliveries_count == 1

        # Concurrent/second delivery d2 -> op_a hits capacity=1
        with pytest.raises(HTTPException) as exc_cap:
            assign_operator(db, d2.id, DeliveryAssignRequest(operator_id=op_a.id), m)
        assert exc_cap.value.status_code == 400

        # Reassign d1 -> op_b: op_a decrements to 0, op_b increments to 1
        assign_operator(db, d1.id, DeliveryAssignRequest(operator_id=op_b.id), m)
        db.refresh(op_a)
        db.refresh(op_b)
        assert op_a.active_deliveries_count == 0
        assert op_b.active_deliveries_count == 1

        # Cancel d1 -> op_b decrements to 0
        update_delivery_status(db, d1.id, DeliveryStatusUpdateRequest(new_status=DeliveryStatus.CANCELLED), m)
        db.refresh(op_b)
        assert op_b.active_deliveries_count == 0

        # Assign d2 -> op_b, move to PICKED_UP -> IN_TRANSIT -> FAILED -> op_b decrements to 0
        op_b_profile = db.query(Profile).filter(Profile.id == op_b.profile_id).first()
        assign_operator(db, d2.id, DeliveryAssignRequest(operator_id=op_b.id), m)
        update_delivery_status(db, d2.id, DeliveryStatusUpdateRequest(new_status=DeliveryStatus.PICKED_UP), op_b_profile)
        update_delivery_status(db, d2.id, DeliveryStatusUpdateRequest(new_status=DeliveryStatus.IN_TRANSIT), op_b_profile)
        update_delivery_status(db, d2.id, DeliveryStatusUpdateRequest(new_status=DeliveryStatus.FAILED), op_b_profile)
        db.refresh(op_b)
        assert op_b.active_deliveries_count == 0
    finally:
        db.close()


def test_competing_outbox_workers_and_crash_after_send_idempotency():
    """Verify:
    1. A second worker skips an item while an active lease is held by worker-1.
    2. An item with provider_message_id already recorded (crash after send) reconciles to SENT without duplicate dispatch.
    """
    db = SessionLocal()
    try:
        m = _make_merchant(db, "outbox")
        d = _make_delivery(db, m.id)
        db.flush()

        now = datetime.now(timezone.utc)
        leased_item = NotificationOutbox(
            id=str(uuid.uuid4()),
            delivery_id=d.id,
            delivery_version=1,
            recipient_phone=d.recipient_phone,
            message_payload="Leased item",
            provider="simulated",
            status=NotificationDeliveryStatus.QUEUED,
            retry_count=1,
            max_retries=5,
            locked_at=now,
            locked_by="worker-1",
        )
        crashed_sent_item = NotificationOutbox(
            id=str(uuid.uuid4()),
            delivery_id=d.id,
            delivery_version=2,
            recipient_phone=d.recipient_phone,
            message_payload="Crash after send item",
            provider="simulated",
            status=NotificationDeliveryStatus.DISPATCHING,
            provider_message_id="sim-msg-already-accepted-999",
            retry_count=1,
            max_retries=5,
            locked_at=None,
            locked_by=None,
        )
        db.add_all([leased_item, crashed_sent_item])
        db.commit()

        send_calls = []

        class SpyProvider:
            def send_sms(self, *args, **kwargs):
                send_calls.append((args, kwargs))
                return {"success": True, "message_id": "should-not-be-called"}

        with patch("backend.app.services.delivery_service.get_notification_provider", return_value=SpyProvider()):
            processed = process_notification_outbox(db, max_items=10, worker_id="worker-2")

        # worker-2 only processes crashed_sent_item (reconciling it to SENT), skipping leased_item
        assert processed == 1
        assert len(send_calls) == 0

        db.refresh(leased_item)
        db.refresh(crashed_sent_item)
        assert leased_item.locked_by == "worker-1"
        assert leased_item.status == NotificationDeliveryStatus.QUEUED
        assert crashed_sent_item.status == NotificationDeliveryStatus.SENT
        assert crashed_sent_item.locked_by is None
    finally:
        db.close()


def test_otp_replay_and_single_use_revocation():
    """Verify OTP cannot be replayed after successful delivery confirmation."""
    db = SessionLocal()
    try:
        m = _make_merchant(db, "otp")
        op = _make_operator(db, "otp")
        d = _make_delivery(db, m.id, status=DeliveryStatus.OUT_FOR_DELIVERY, operator_id=op.id, raw_otp="654321")
        op.active_deliveries_count = 1
        db.commit()

        res = verify_delivery_otp(db, d.id, DeliveryVerifyOTPRequest(otp="654321"), m)
        assert res.status == DeliveryStatus.DELIVERED
        assert res.pod_verified is True
        assert res.otp_hash == "REVOKED_AND_VERIFIED"

        with pytest.raises(HTTPException) as replay_exc:
            verify_delivery_otp(db, d.id, DeliveryVerifyOTPRequest(otp="654321"), m)
        assert replay_exc.value.status_code == 400
    finally:
        db.close()


def test_verification_evidence_immutability_and_append_only_supersession():
    """Verify VerificationEvidence blocks UPDATE/DELETE and supports append-only supersession."""
    db = SessionLocal()
    try:
        pc = f"100{uuid.uuid4().hex[:3]}"
        now = datetime.now(timezone.utc)
        old_ev = VerificationEvidence(
            id=str(uuid.uuid4()),
            postcode=pc,
            provider="NIPOST",
            provider_reference_id="ref-old",
            verified_at=now - timedelta(days=40),
            valid_until=now - timedelta(days=10),
            response_hash=hashlib.sha256(b"old").hexdigest(),
            status="verified",
            address_metadata_source="nipost_autofill",
            is_active=True,
        )
        db.add(old_ev)
        db.commit()

        # Mutating committed evidence must raise ValueError at ORM boundary
        old_ev.status = "rejected"
        with pytest.raises(ValueError, match="immutable"):
            db.commit()
        db.rollback()

        # Deleting committed evidence must raise ValueError at ORM boundary
        db.delete(old_ev)
        with pytest.raises(ValueError, match="immutable"):
            db.commit()
        db.rollback()

        # Append-only supersession: insert new evidence record while preserving historical row
        new_ev = VerificationEvidence(
            id=str(uuid.uuid4()),
            postcode=pc,
            provider="NIPOST",
            provider_reference_id="ref-new",
            verified_at=now,
            valid_until=now + timedelta(days=30),
            response_hash=hashlib.sha256(b"new").hexdigest(),
            status="verified",
            address_metadata_source="nipost_autofill",
            is_active=True,
        )
        db.add(new_ev)
        db.commit()

        history = (
            db.query(VerificationEvidence)
            .filter(VerificationEvidence.postcode == pc)
            .order_by(VerificationEvidence.verified_at.desc())
            .all()
        )
        assert len(history) == 2
        assert history[0].id == new_ev.id
        assert history[0].is_expired is False
        assert history[1].id == old_ev.id
        assert history[1].is_expired is True
    finally:
        db.close()
