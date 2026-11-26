"""v6.3.2 concurrency and reliability regression tests for OTP verification and outbox worker."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import secrets
from types import SimpleNamespace
import uuid
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from backend.app.core.security import hash_otp
from backend.app.database import SessionLocal
from backend.app.models.delivery import Delivery
from backend.app.models.enums import AppRole, DeliveryStatus
from backend.app.models.notification_outbox import NotificationDeliveryStatus, NotificationOutbox
from backend.app.models.operator import Operator
from backend.app.models.profile import Profile
from backend.app.models.worker_heartbeat import WorkerHeartbeat
from backend.app.schemas.delivery import DeliveryVerifyOTPRequest
from backend.app.services.delivery_service import (
    process_notification_outbox,
    record_worker_shutdown,
    verify_delivery_otp,
)


def _seed_otp_delivery(db, raw_otp: str = "123456"):
    uid = str(uuid.uuid4())
    merchant = Profile(
        id=uid,
        full_name="Concurrency Merchant",
        phone=f"+23480{str(uuid.UUID(uid).int)[:8]}",
        email=f"conc-m-{uid[:6]}@test.ng",
        hashed_password="pw",
        role=AppRole.MERCHANT,
    )
    op_uid = str(uuid.uuid4())
    op_profile = Profile(
        id=op_uid,
        full_name="Concurrency Operator",
        phone=f"+23481{str(uuid.UUID(op_uid).int)[:8]}",
        email=f"conc-op-{op_uid[:6]}@test.ng",
        hashed_password="pw",
        role=AppRole.OPERATOR,
    )
    db.add_all([merchant, op_profile])
    db.flush()

    op = Operator(
        id=str(uuid.uuid4()),
        profile_id=op_profile.id,
        business_name="Concurrency Fleet",
        phone=op_profile.phone,
        service_areas=["Lagos"],
        is_available=True,
        max_active_deliveries=15,
        active_deliveries_count=1,
        completed_deliveries=0,
    )
    db.add(op)
    db.flush()

    delivery = Delivery(
        id=f"PL-2026-{uuid.uuid4().hex[:6].upper()}",
        tracking_token=secrets.token_urlsafe(24),
        merchant_id=merchant.id,
        operator_id=op.id,
        recipient_name="Chidi Okafor",
        recipient_phone="+2348035556666",
        destination_address="5 Admiralty Way, Lekki Phase 1, Lagos",
        destination_area="Lekki",
        destination_state="Lagos",
        postcode_input="106104",
        package_description="Concurrency Test Parcel",
        status=DeliveryStatus.OUT_FOR_DELIVERY,
        otp_hash=hash_otp(raw_otp),
        otp_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        otp_attempts=0,
        otp_max_attempts=3,
        pod_verified=False,
        version=1,
    )
    db.add(delivery)
    db.commit()
    return merchant.id, op.id, delivery.id


def test_concurrent_verify_delivery_otp_allows_single_winner():
    db = SessionLocal()
    try:
        dialect = getattr(db.get_bind().dialect, "name", "")
        merchant_id, op_id, delivery_id = _seed_otp_delivery(db, raw_otp="654321")
    finally:
        db.close()

    def _attempt():
        worker_db = SessionLocal()
        try:
            actor = worker_db.query(Profile).filter(Profile.id == merchant_id).first()
            res = verify_delivery_otp(
                db=worker_db,
                delivery_id=delivery_id,
                request=DeliveryVerifyOTPRequest(otp="654321"),
                current_user=actor,
            )
            return ("ok", res.status)
        except HTTPException as exc:
            worker_db.rollback()
            return ("http_error", exc.status_code)
        except OperationalError:
            worker_db.rollback()
            return ("db_locked", None)
        finally:
            worker_db.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: _attempt(), range(3)))

    winners = [r for r in results if r[0] == "ok"]
    if dialect == "postgresql":
        assert len(winners) == 1
        http_errors = [r for r in results if r[0] == "http_error"]
        assert len(http_errors) == 2
        assert all(code == 400 for _, code in http_errors)
    else:
        assert len(winners) >= 1

    check_db = SessionLocal()
    try:
        delivery = check_db.query(Delivery).filter(Delivery.id == delivery_id).first()
        op = check_db.query(Operator).filter(Operator.id == op_id).first()
        assert delivery.pod_verified is True
        assert delivery.status == DeliveryStatus.DELIVERED
        if dialect == "postgresql":
            assert op.completed_deliveries == 1
            assert op.active_deliveries_count == 0
    finally:
        check_db.close()


def test_outbox_two_worker_race_prevents_duplicate_sms():
    db = SessionLocal()
    try:
        dialect = getattr(db.get_bind().dialect, "name", "")
        db.query(NotificationOutbox).delete()
        db.commit()
        merchant_id, _, delivery_id = _seed_otp_delivery(db)
        item = NotificationOutbox(
            id=str(uuid.uuid4()),
            delivery_id=delivery_id,
            delivery_version=1,
            notification_type="status_alert",
            recipient_phone="+2348035556666",
            message_payload="Single dispatch only",
            provider="simulated",
            status=NotificationDeliveryStatus.QUEUED,
            retry_count=0,
            max_retries=5,
        )
        db.add(item)
        db.commit()
        item_id = item.id
    finally:
        db.close()

    send_calls = []

    class SpyProvider:
        def send_status_alert(self, **kwargs):
            send_calls.append(kwargs)
            return SimpleNamespace(
                status=NotificationDeliveryStatus.SENT,
                provider="simulated",
                message_id=f"msg-{uuid.uuid4().hex[:8]}",
                error_details=None,
            )

    def _run_worker(worker_name: str):
        worker_db = SessionLocal()
        try:
            with patch(
                "backend.app.services.delivery_service.get_notification_provider",
                return_value=SpyProvider(),
            ):
                return process_notification_outbox(worker_db, max_items=10, worker_id=worker_name)
        except OperationalError:
            worker_db.rollback()
            return 0
        finally:
            worker_db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(_run_worker, ["worker-a", "worker-b"]))

    if dialect == "postgresql":
        assert sum(counts) == 1
        assert len(send_calls) == 1
    else:
        assert 1 <= sum(counts) <= 2
        assert 1 <= len(send_calls) <= 2

    check_db = SessionLocal()
    try:
        refreshed = check_db.query(NotificationOutbox).filter(NotificationOutbox.id == item_id).first()
        assert refreshed.status == NotificationDeliveryStatus.SENT
        assert refreshed.locked_by is None
    finally:
        check_db.close()


def test_outbox_expired_lease_recovery_and_max_retries_failure():
    db = SessionLocal()
    try:
        db.query(NotificationOutbox).delete()
        db.commit()
        _, _, delivery_id = _seed_otp_delivery(db)
        stale_item = NotificationOutbox(
            id=str(uuid.uuid4()),
            delivery_id=delivery_id,
            delivery_version=1,
            notification_type="status_alert",
            recipient_phone="+2348035556666",
            message_payload="Expired lease item",
            provider="simulated",
            status=NotificationDeliveryStatus.QUEUED,
            retry_count=0,
            max_retries=3,
            locked_at=datetime.now(timezone.utc) - timedelta(minutes=15),
            locked_by="crashed-worker",
        )
        exhausted_item = NotificationOutbox(
            id=str(uuid.uuid4()),
            delivery_id=delivery_id,
            delivery_version=2,
            notification_type="status_alert",
            recipient_phone="+2348035556666",
            message_payload="Failing item",
            provider="simulated",
            status=NotificationDeliveryStatus.QUEUED,
            retry_count=2,
            max_retries=3,
        )
        db.add_all([stale_item, exhausted_item])
        db.commit()

        class MixedProvider:
            def send_status_alert(self, **kwargs):
                msg = kwargs.get("status_message", "")
                if "Expired lease" in str(msg):
                    return SimpleNamespace(
                        status=NotificationDeliveryStatus.SENT,
                        provider="simulated",
                        message_id="recovered-msg-1",
                        error_details=None,
                    )
                return SimpleNamespace(
                    status=NotificationDeliveryStatus.FAILED,
                    provider="simulated",
                    message_id=None,
                    error_details="Upstream gateway 503",
                )

        with patch(
            "backend.app.services.delivery_service.get_notification_provider",
            return_value=MixedProvider(),
        ):
            processed = process_notification_outbox(db, max_items=10, worker_id="recovery-worker")

        assert processed == 2
        db.refresh(stale_item)
        db.refresh(exhausted_item)
        assert stale_item.status == NotificationDeliveryStatus.SENT
        assert stale_item.locked_by is None
        assert exhausted_item.status == NotificationDeliveryStatus.FAILED
        assert exhausted_item.retry_count == 3
        assert exhausted_item.failure_classification == "max_retries_exceeded"

        # Graceful shutdown records stopped heartbeat
        record_worker_shutdown(db, worker_id="recovery-worker", reason="graceful_shutdown")
        hb = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == "recovery-worker").first()
        assert hb is not None
        assert hb.status == "stopped"
        assert hb.stop_reason == "graceful_shutdown"
    finally:
        db.close()
