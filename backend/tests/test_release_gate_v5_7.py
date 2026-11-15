"""Release Gate v5.7: Operational Security, Distributed Reliability & Acceptance Tests."""
import uuid
import time
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import text
from alembic.config import Config
from alembic import command

from backend.app.main import app
from backend.app.database import SessionLocal, engine
from backend.app.models.profile import Profile
from backend.app.models.api_key import ApiKey
from backend.app.models.delivery import Delivery
from backend.app.models.delivery_event import DeliveryEvent
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.models.worker_heartbeat import WorkerHeartbeat
from backend.app.models.enums import AppRole, DeliveryStatus
from backend.app.services.notification_service import (
    NotificationDeliveryStatus,
    NotificationDispatchResult,
    get_notification_provider,
    mask_phone,
)
from backend.app.core.security import create_access_token, hash_otp
from backend.app.core.rate_limiter import (
    check_api_key_rate_limit,
    reset_api_key_rate_limits,
    get_rate_limiter_status,
)
from backend.app.services.delivery_service import (
    process_notification_outbox,
    record_worker_heartbeat,
)
from backend.app.services.nipost_client import NIPOSTClient, NIPOSTLookupStatus, NIPOSTLookupResult

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    reset_api_key_rate_limits()
    db = SessionLocal()
    try:
        db.query(NotificationOutbox).delete()
        db.query(WorkerHeartbeat).delete()
        db.commit()
    finally:
        db.close()


def get_token(role: AppRole = AppRole.MERCHANT, email: str = "v57_merchant@test.ng") -> str:
    db = SessionLocal()
    try:
        user = db.query(Profile).filter(Profile.email == email).first()
        if not user:
            user = Profile(
                id=str(uuid.uuid4()),
                email=email,
                role=role,
                full_name=f"Test {role.value}",
                hashed_password="hashed_test_password",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return create_access_token({"sub": user.id, "role": user.role.value})
    finally:
        db.close()


# ==============================================================================
# 1. Real Alembic Migration Execution Test (Preserves Verified Records)
# ==============================================================================
def test_alembic_migration_execution_preserves_verified_records():
    """Execute real Alembic upgrade/downgrade and verify exact fixture reclassification."""
    alembic_cfg = Config("alembic.ini")
    demo_code = "FC-02-A09-DB-09"
    verified_code = "900211-VERIFIED-TEST"
    local_code = "100001-LOCAL-REF"

    # 1. Downgrade to prior revision before e5f6a7b8c9d0
    command.downgrade(alembic_cfg, "d4f5a6b7c8e9")

    db = SessionLocal()
    try:
        db.query(PostcodeDirectory).filter(
            PostcodeDirectory.code.in_([demo_code, verified_code, local_code])
        ).delete()
        db.commit()

        # Seed demonstration fixture (mislabeled as official_verified prior to migration)
        demo_rec = PostcodeDirectory(
            code=demo_code,
            area="Garki 2 Area",
            state="Abuja FCT",
            provenance="PostcodeLink Demonstration Reference",
            verification_status="official_verified",
        )
        # Seed legitimate NIPOST verified record
        verified_rec = PostcodeDirectory(
            code=verified_code,
            area="Central Business District",
            state="Abuja FCT",
            provenance="NIPOST Official Directory 2026",
            verification_status="official_verified",
        )
        # Seed local reference record
        local_rec = PostcodeDirectory(
            code=local_code,
            area="Ikeja Local",
            state="Lagos",
            provenance="NIPOST Digital Address Register 2024",
            verification_status="local_reference",
        )
        db.add_all([demo_rec, verified_rec, local_rec])
        db.commit()

        # 2. Execute migration upgrade to head (runs e5f6a7b8c9d0 and f6a7b8c9d0e1)
        command.upgrade(alembic_cfg, "head")

        db.expire_all()
        reloaded_demo = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == demo_code).first()
        reloaded_verified = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == verified_code).first()
        reloaded_local = db.query(PostcodeDirectory).filter(PostcodeDirectory.code == local_code).first()

        # 1. Demo fixture must be reclassified to local_reference
        assert reloaded_demo.verification_status == "local_reference"
        # 2. Legitimate NIPOST verified record MUST be strictly preserved as official_verified
        assert reloaded_verified.verification_status == "official_verified"
        # 3. Local reference record remains local_reference
        assert reloaded_local.verification_status == "local_reference"

        # 3. Reversibility test: downgrade to prior migration and re-upgrade to head
        command.downgrade(alembic_cfg, "d4f5a6b7c8e9")
        command.upgrade(alembic_cfg, "head")
    finally:
        db.query(PostcodeDirectory).filter(
            PostcodeDirectory.code.in_([demo_code, verified_code, local_code])
        ).delete()
        db.commit()
        db.close()
        # Ensure database is left cleanly at head and restore seeded fixtures
        command.upgrade(alembic_cfg, "head")
        from backend.app.seed import seed_database
        seed_database()


# ==============================================================================
# 2. SMS Crash Recovery Without Persisted Provider Message ID
# ==============================================================================
def test_sms_crash_recovery_without_saved_message_id_routes_to_reconciliation():
    """Verify outbox recovery when worker crashed before saving provider message ID.
    
    If the provider cannot confirm dispatch via phone inquiry, worker routes to
    RECONCILIATION_REQUIRED and never blindly re-dispatches.
    """
    db = SessionLocal()
    try:
        # Create delivery and an ambiguous outbox item simulating crash during HTTP dispatch
        delivery = Delivery(
            id="PL-CRASH-TEST-99",
            recipient_phone="+2348011223344",
            recipient_name="Crash Recovery Test",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="10 Test St",
            package_description="Crash Recovery Package",
            postcode_input="100271",
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("123456"),
            tracking_token="token_crash_test_12345678901234567890",
        )
        db.add(delivery)
        db.commit()

        outbox_item = NotificationOutbox(
            delivery_id=delivery.id,
            notification_type="otp_delivery_pin",
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            provider="termii",  # Termii does not confirm dispatch without message ID
            status=NotificationDeliveryStatus.DISPATCHING,
            idempotency_key="outbox_crash_key_999",
            provider_message_id=None,  # Lost in simulated crash before commit
            retry_count=2,  # Prior attempt recorded
            delivery_version=1,
            max_retries=3,
        )
        db.add(outbox_item)
        db.commit()

        # Run outbox worker tick
        processed = process_notification_outbox(db, max_items=10, worker_id="recovery-worker-1")
        assert processed == 1

        db.refresh(outbox_item)
        # Because provider_message_id was lost and provider returned None, item transitions to RECONCILIATION_REQUIRED
        assert outbox_item.status == NotificationDeliveryStatus.RECONCILIATION_REQUIRED
        assert outbox_item.failure_classification == "unconfirmed_crash_window"
    finally:
        db.query(NotificationOutbox).filter(NotificationOutbox.delivery_id == "PL-CRASH-TEST-99").delete()
        db.query(Delivery).filter(Delivery.id == "PL-CRASH-TEST-99").delete()
        db.commit()
        db.close()


# ==============================================================================
# 3. Privacy & RBAC Enforcement on Reconciliation Endpoints
# ==============================================================================
def test_reconciliation_endpoints_rbac_and_privacy_masking():
    """Verify operators are forbidden from reconciliation and recipient phone numbers are masked."""
    op_token = get_token(AppRole.OPERATOR, "courier_v57@test.ng")
    op_headers = {"Authorization": f"Bearer {op_token}"}
    admin_token = get_token(AppRole.ADMIN, "compliance_admin@test.ng")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    db = SessionLocal()
    try:
        # Seed parent Delivery record to satisfy PostgreSQL foreign key constraint
        delivery = Delivery(
            id="PL-RECON-RBAC-01",
            recipient_phone="+2348039876543",
            recipient_name="Privacy Recipient",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="10 Test St",
            package_description="Privacy Test Package",
            postcode_input="100271",
            status=DeliveryStatus.OUT_FOR_DELIVERY,
            otp_hash=hash_otp("123456"),
            tracking_token="token_privacy_rbac_12345678901234567890",
        )
        db.add(delivery)
        db.commit()

        # Seed an item in RECONCILIATION_REQUIRED
        item = NotificationOutbox(
            delivery_id=delivery.id,
            notification_type="otp_delivery_pin",
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            status=NotificationDeliveryStatus.RECONCILIATION_REQUIRED,
            idempotency_key="recon_key_rbac_01",
            retry_count=2,
            delivery_version=1,
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        # 1. Courier Operator is strictly forbidden (HTTP 403)
        res_op_list = client.get("/api/v1/deliveries/outbox/reconciliation", headers=op_headers)
        assert res_op_list.status_code == 403, "Operator must be denied access to reconciliation listing"

        res_op_resolve = client.post(
            f"/api/v1/deliveries/outbox/{item.id}/reconcile",
            json={"resolution": "requeue", "reason": "Courier trying to reconcile manually."},
            headers=op_headers,
        )
        assert res_op_resolve.status_code == 403, "Operator must be denied access to resolve reconciliation"

        # 2. Admin access succeeds with masked phone numbers
        res_admin_list = client.get("/api/v1/deliveries/outbox/reconciliation", headers=admin_headers)
        assert res_admin_list.status_code == 200
        items = res_admin_list.json()
        target = next(it for it in items if it["id"] == item.id)

        # Verify raw phone number is NOT exposed
        assert "recipient_phone" not in target or target.get("recipient_phone") is None
        assert "recipient_phone_masked" in target
        assert target["recipient_phone_masked"] == mask_phone("+2348039876543")
        assert "***" in target["recipient_phone_masked"]
    finally:
        db.query(NotificationOutbox).filter(NotificationOutbox.delivery_id == "PL-RECON-RBAC-01").delete()
        db.query(Delivery).filter(Delivery.id == "PL-RECON-RBAC-01").delete()
        db.commit()
        db.close()


# ==============================================================================
# 4. Mandatory Audit Reason & Evidence for Manual Reconciliation
# ==============================================================================
def test_manual_reconciliation_requires_evidence_and_records_audit_event():
    """Verify manual resolution requires structured reason/evidence and creates immutable audit event."""
    admin_token = get_token(AppRole.ADMIN, "audit_admin@test.ng")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    db = SessionLocal()
    try:
        delivery = Delivery(
            id="PL-AUDIT-TEST-01",
            recipient_phone="+2348011223344",
            recipient_name="Audit Delivery",
            destination_state="Lagos",
            destination_area="Ikeja",
            destination_address="10 Test St",
            package_description="Audit Test Package",
            postcode_input="100271",
            status=DeliveryStatus.OUT_FOR_DELIVERY,
            otp_hash=hash_otp("123456"),
            tracking_token="token_audit_test_12345678901234567890",
        )
        db.add(delivery)
        db.commit()

        item = NotificationOutbox(
            delivery_id=delivery.id,
            notification_type="otp_delivery_pin",
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            status=NotificationDeliveryStatus.RECONCILIATION_REQUIRED,
            idempotency_key="recon_audit_key_01",
            retry_count=2,
            delivery_version=1,
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        # 1. Missing reason or short reason rejected (< 10 chars)
        res_short_reason = client.post(
            f"/api/v1/deliveries/outbox/{item.id}/reconcile",
            json={"resolution": "mark_sent", "reason": "too short"},
            headers=admin_headers,
        )
        assert res_short_reason.status_code == 422

        # 2. mark_sent without provider_message_id or evidence_reference rejected
        res_no_evidence = client.post(
            f"/api/v1/deliveries/outbox/{item.id}/reconcile",
            json={"resolution": "mark_sent", "reason": "Verified delivery personally with carrier."},
            headers=admin_headers,
        )
        assert res_no_evidence.status_code == 422
        assert "requires explicit evidence" in res_no_evidence.json()["detail"]

        # 3. Successful resolution with evidence creates DeliveryEvent audit log
        res_valid = client.post(
            f"/api/v1/deliveries/outbox/{item.id}/reconcile",
            json={
                "resolution": "mark_sent",
                "reason": "Verified carrier dispatch log confirms SMS delivered.",
                "evidence_reference": "CARRIER-TICKET-88910",
                "provider_message_id": "TELCO_MSG_445566",
            },
            headers=admin_headers,
        )
        assert res_valid.status_code == 200
        db.refresh(item)
        assert item.status == NotificationDeliveryStatus.SENT
        assert item.provider_message_id == "TELCO_MSG_445566"

        # Check DeliveryEvent audit record
        event = db.query(DeliveryEvent).filter(DeliveryEvent.delivery_id == delivery.id).first()
        assert event is not None
        assert "Outbox manual reconciliation" in event.note
        assert "Verified carrier dispatch log" in event.note
        assert event.actor_role == "admin"
    finally:
        db.query(NotificationOutbox).filter(NotificationOutbox.delivery_id == "PL-AUDIT-TEST-01").delete()
        db.query(Delivery).filter(Delivery.id == "PL-AUDIT-TEST-01").delete()
        db.query(DeliveryEvent).filter(DeliveryEvent.delivery_id == "PL-AUDIT-TEST-01").delete()
        db.commit()
        db.close()


# ==============================================================================
# 5. Strict NIPOST Lookup Requires 'code' & Never Falls Back
# ==============================================================================
def test_strict_nipost_lookup_requires_code_and_blocks_area_fallback():
    """Verify GET /api/v1/postcodes/lookup?strict=true rejects requests missing 'code' with HTTP 422."""
    # 1. Missing code with strict=True raises HTTP 422
    res_no_code = client.get("/api/v1/postcodes/lookup?state=Lagos&area=Ikeja&strict=true")
    assert res_no_code.status_code == 422
    assert "requires an authoritative 'code' parameter" in res_no_code.json()["detail"]

    # 2. Strict=False with area search succeeds and returns local reference
    res_fallback = client.get("/api/v1/postcodes/lookup?state=Lagos&area=Ikeja&strict=false")
    assert res_fallback.status_code == 200
    assert res_fallback.json()["count"] > 0
    assert res_fallback.json()["matches"][0]["verification_status"] == "local_reference"

    # 3. Strict=True with code when NIPOST is unauthorized returns HTTP 502
    class MockUnauthorizedClient:
        is_configured = True
        def lookup_postcode(self, code):
            return NIPOSTLookupResult(status=NIPOSTLookupStatus.UNAUTHORIZED, error_message="Invalid API Key")

    from backend.app.routers.postcodes import get_nipost_client
    app.dependency_overrides[get_nipost_client] = lambda: MockUnauthorizedClient()
    try:
        res_unauth = client.get("/api/v1/postcodes/lookup?code=100001&strict=true")
        assert res_unauth.status_code == 502
    finally:
        app.dependency_overrides.pop(get_nipost_client, None)


# ==============================================================================
# 6. Concurrent API Key Rotation Protection
# ==============================================================================
def test_concurrent_api_key_rotation_allows_only_one_replacement():
    """Verify atomic update prevents concurrent requests from creating duplicate replacements."""
    token = get_token(AppRole.MERCHANT, "concurrent_merchant@test.ng")
    headers = {"Authorization": f"Bearer {token}"}

    key_name = f"Race Key {uuid.uuid4().hex[:6]}"
    create_res = client.post("/api/v1/api-keys/", json={"name": key_name, "monthly_quota": 500}, headers=headers)
    assert create_res.status_code == 201
    key_id = create_res.json()["id"]

    # First rotation request succeeds
    rot1 = client.post(f"/api/v1/api-keys/{key_id}/rotate", headers=headers)
    assert rot1.status_code in [200, 201]

    # Second concurrent/subsequent rotation attempt on the same key MUST fail with HTTP 409 Conflict
    rot2 = client.post(f"/api/v1/api-keys/{key_id}/rotate", headers=headers)
    assert rot2.status_code == 409
    assert "already been rotated or revoked" in rot2.json()["detail"]

    db = SessionLocal()
    try:
        # Verify exactly one replacement key with rotated name exists
        replacements = db.query(ApiKey).filter(ApiKey.name == f"{key_name} (Rotated)").all()
        assert len(replacements) == 1
    finally:
        db.close()


# ==============================================================================
# 7. Persistent Cross-Process Worker Heartbeat
# ==============================================================================
def test_persistent_worker_heartbeat_cross_process_monitoring():
    """Verify worker heartbeats are persisted in the database and monitored via /health/worker."""
    db = SessionLocal()
    # Delete any prior heartbeats so test is fully isolated
    db.query(WorkerHeartbeat).delete()
    db.commit()

    worker_id = "standalone-worker-v57"
    try:
        # Simulate standalone worker process recording heartbeat
        record_worker_heartbeat(db, worker_id=worker_id, status="active", processed_count=5)

        # Query health endpoint
        res = client.get("/health/worker")
        assert res.status_code == 200
        data = res.json()

        assert data["active_worker_id"] == worker_id
        assert data["status"] == "operational"
        assert data["seconds_since_last_heartbeat"] is not None
        assert data["seconds_since_last_heartbeat"] <= 10

        # Simulate stale worker heartbeat (> 120s ago)
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=300)
        hb = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
        hb.last_heartbeat_at = stale_time
        db.commit()

        res_stale = client.get("/health/worker")
        assert res_stale.status_code == 200
        data_stale = res_stale.json()
        assert data_stale["status"] == "degraded"
        assert data_stale["seconds_since_last_heartbeat"] >= 300
    finally:
        db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).delete()
        db.commit()
        db.close()


# ==============================================================================
# 8. Sanitized Integration Health Checks
# ==============================================================================
def test_sanitized_integration_health_checks():
    """Verify /health/integrations reports connectivity statuses and omits all sensitive endpoints."""
    res = client.get("/health/integrations")
    assert res.status_code == 200
    data = res.json()

    assert "nipost" in data
    assert "sms_gateway" in data

    nipost = data["nipost"]
    assert "configured" in nipost
    assert "reachable" in nipost
    assert "authenticated" in nipost
    assert "last_successful_check" in nipost
    assert "last_error_category" in nipost

    # Strict privacy: NO base_url or endpoints exposed
    assert "base_url" not in nipost
    assert "url" not in nipost
    assert "api_key" not in nipost

    sms = data["sms_gateway"]
    assert "provider" in sms
    assert "configured" in sms
    assert "reachable" in sms
    assert "authenticated" in sms


# ==============================================================================
# 9. Rate Limiter Invalid Limit Rejection & Status
# ==============================================================================
def test_rate_limiter_rejects_invalid_configuration():
    """Verify non-positive rate limits are rejected with HTTP 400."""
    with pytest.raises(Exception) as exc_info:
        check_api_key_rate_limit(key_id="test_key_0", limit_per_minute=0)
    assert exc_info.value.status_code == 400

    with pytest.raises(Exception) as exc_info_neg:
        check_api_key_rate_limit(key_id="test_key_neg", limit_per_minute=-10)
    assert exc_info_neg.value.status_code == 400

    status = get_rate_limiter_status()
    assert "backend" in status
    assert status["backend"] in ["redis", "in_memory_fallback"]
