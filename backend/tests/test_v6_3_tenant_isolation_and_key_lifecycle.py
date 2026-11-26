"""v6.3 comprehensive negative-access, tenant isolation, public tracking privacy, and API-key lifecycle tests."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.core.security import create_access_token, hash_otp
from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models.api_key import ApiKey
from backend.app.models.delivery import Delivery
from backend.app.models.enums import AppRole, DeliveryStatus
from backend.app.models.operator import Operator
from backend.app.models.profile import Profile


def _seed_actor(db, role: AppRole, tag: str) -> Profile:
    uid = str(uuid.uuid4())
    p = Profile(
        id=uid,
        full_name=f"{role.value.title()} {tag}",
        phone=f"+23480{str(uuid.UUID(uid).int)[:8]}",
        email=f"{role.value}-{tag}-{uid[:6]}@test.ng",
        hashed_password="pw",
        role=role,
    )
    db.add(p)
    db.flush()
    return p


def _jwt_headers(profile: Profile) -> dict:
    token = create_access_token({"sub": profile.id, "role": profile.role.value})
    return {"Authorization": f"Bearer {token}"}


def test_cross_tenant_delivery_and_unassigned_operator_negative_access():
    client = TestClient(app)
    db = SessionLocal()
    try:
        m_a = _seed_actor(db, AppRole.MERCHANT, "A")
        m_b = _seed_actor(db, AppRole.MERCHANT, "B")
        op_profile = _seed_actor(db, AppRole.OPERATOR, "unassigned")
        op = Operator(
            id=str(uuid.uuid4()),
            profile_id=op_profile.id,
            business_name="Unassigned Fleet",
            phone=op_profile.phone,
            service_areas=["Lagos"],
            is_available=True,
        )
        db.add(op)
        d = Delivery(
            id=f"PL-2026-{uuid.uuid4().hex[:6].upper()}",
            tracking_token=secrets.token_urlsafe(24),
            merchant_id=m_a.id,
            operator_id=None,
            recipient_name="Amina Bello",
            recipient_phone="+2348039876543",
            destination_address="22 Bourdillon Road, Ikoyi, Lagos",
            destination_area="Ikoyi",
            destination_state="Lagos",
            postcode_input="101245",
            package_description="Confidential Docs",
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("123456"),
            otp_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            version=1,
        )
        db.add(d)
        db.commit()

        # Merchant B negative access checks
        assert client.get(f"/api/v1/deliveries/{d.id}", headers=_jwt_headers(m_b)).status_code == 403
        assert client.post(
            f"/api/v1/deliveries/{d.id}/status",
            json={"new_status": "cancelled"},
            headers=_jwt_headers(m_b),
        ).status_code == 403
        assert client.post(
            f"/api/v1/deliveries/{d.id}/assign",
            json={"operator_id": op.id},
            headers=_jwt_headers(m_b),
        ).status_code == 403
        assert client.delete(f"/api/v1/deliveries/{d.id}", headers=_jwt_headers(m_b)).status_code == 403

        # Unassigned Operator negative access checks
        assert client.get(f"/api/v1/deliveries/{d.id}", headers=_jwt_headers(op_profile)).status_code == 403
        assert client.post(
            f"/api/v1/deliveries/{d.id}/status",
            json={"new_status": "picked_up"},
            headers=_jwt_headers(op_profile),
        ).status_code == 403

        # Unauthenticated access rejected
        assert client.get(f"/api/v1/deliveries/{d.id}").status_code == 401

        # Public tracking privacy: masks recipient and hides street/coords/OTP
        track = client.get(f"/api/v1/deliveries/track/{d.tracking_token}")
        assert track.status_code == 200
        tb = track.json()
        assert tb.get("recipient_name_masked") != "Amina Bello"
        assert "22 Bourdillon" not in str(tb)
        assert "otp_hash" not in tb
        assert "lat" not in tb and "lng" not in tb

        # Predictable delivery reference rejected on public tracking
        assert client.get(f"/api/v1/deliveries/track/{d.id}").status_code in (400, 404)
    finally:
        db.close()


def test_api_key_ownership_revocation_quota_rotation_and_live_auth_expiry():
    client = TestClient(app)
    db = SessionLocal()
    try:
        m_a = _seed_actor(db, AppRole.MERCHANT, "keyA")
        m_b = _seed_actor(db, AppRole.MERCHANT, "keyB")
        d_a = Delivery(
            id=f"PL-2026-{uuid.uuid4().hex[:6].upper()}",
            tracking_token=f"trk_{uuid.uuid4().hex}",
            merchant_id=m_a.id,
            recipient_name="Chidi Nwosu",
            recipient_phone="+2348021112233",
            destination_address="15 Allen Avenue, Ikeja, Lagos",
            destination_area="Ikeja",
            destination_state="Lagos",
            postcode_input="100281",
            package_description="Electronics",
            status=DeliveryStatus.PENDING,
            otp_hash=hash_otp("654321"),
            otp_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            version=1,
        )
        db.add(d_a)

        now_period = datetime.now(timezone.utc).strftime("%Y-%m")
        raw_b = f"pl_test_{uuid.uuid4().hex}"
        key_b = ApiKey(
            merchant_id=m_b.id,
            name="Merchant B Test Key",
            environment="test",
            key_prefix=raw_b[:12],
            hashed_key=hashlib.sha256(raw_b.encode()).hexdigest(),
            monthly_quota=100,
            current_period=now_period,
            period_usage_count=7,
            usage_count=7,
            is_active=True,
            is_revoked=False,
        )
        raw_live_a = f"pl_live_{uuid.uuid4().hex}"
        key_live_a = ApiKey(
            merchant_id=m_a.id,
            name="Merchant A Live Key",
            environment="live",
            key_prefix=raw_live_a[:12],
            hashed_key=hashlib.sha256(raw_live_a.encode()).hexdigest(),
            monthly_quota=100,
            current_period=now_period,
            period_usage_count=0,
            usage_count=0,
            is_active=True,
            is_revoked=False,
        )
        db.add_all([key_b, key_live_a])
        db.commit()
        db.refresh(key_b)

        # 1. Merchant A cannot rotate or revoke Merchant B's key
        assert client.post(f"/api/v1/api-keys/{key_b.id}/rotate", headers=_jwt_headers(m_a)).status_code == 404
        assert client.delete(f"/api/v1/api-keys/{key_b.id}", headers=_jwt_headers(m_a)).status_code == 404

        # 2. Merchant B's API key cannot access Merchant A's delivery
        assert client.get(f"/api/v1/deliveries/{d_a.id}", headers={"x-api-key": raw_b}).status_code == 403

        # 3. Rotating key_b preserves period_usage_count (7 -> 8 after auth above) and revokes old raw_b
        rot = client.post(f"/api/v1/api-keys/{key_b.id}/rotate", headers=_jwt_headers(m_b))
        assert rot.status_code == 201
        rot_json = rot.json()
        assert rot_json["period_usage_count"] == 8
        assert rot_json["usage_count"] == 8
        assert client.get("/api/v1/postcodes/commercial/lookup?state=Lagos", headers={"x-api-key": raw_b}).status_code == 401

        # 4. Immediate revocation of rotated key blocks all endpoints
        new_raw_b = rot_json["api_key"]
        new_id_b = rot_json["id"]
        assert client.delete(f"/api/v1/api-keys/{new_id_b}", headers=_jwt_headers(m_b)).status_code == 200
        assert client.get("/api/v1/postcodes/commercial/lookup?state=Lagos", headers={"x-api-key": new_raw_b}).status_code == 401
        assert client.post(
            "/api/v1/deliveries/",
            json={
                "recipient_name": "Test",
                "recipient_phone": "+2348011111111",
                "destination_address": "1 Test Rd",
                "destination_area": "Ikeja",
                "destination_state": "Lagos",
                "postcode_input": "100001",
                "package_description": "Box",
            },
            headers={"x-api-key": new_raw_b},
        ).status_code == 401

        # 5. Live key blocked when NIPOST commercial authorization is revoked or expired
        with patch.object(settings, "NIPOST_AUTHORIZATION_REVOKED", True):
            r_rev = client.get("/api/v1/postcodes/commercial/lookup?code=100001", headers={"x-api-key": raw_live_a})
            assert r_rev.status_code == 403
            r_cleanse_rev = client.post(
                "/api/v1/postcodes/commercial/cleanse",
                json={"address": "10 Awolowo Way, Ikeja, Lagos", "postcode": "100001"},
                headers={"x-api-key": raw_live_a},
            )
            assert r_cleanse_rev.status_code == 403

        with (
            patch.object(settings, "NIPOST_AUTHORIZATION_REVOKED", False),
            patch.object(settings, "NIPOST_PRODUCTION_AUTHORIZED", True),
            patch.object(settings, "NIPOST_AUTHORIZATION_EXPIRES_AT", "2020-01-01T00:00:00Z"),
        ):
            r_exp = client.get("/api/v1/postcodes/commercial/lookup?code=100001", headers={"x-api-key": raw_live_a})
            assert r_exp.status_code == 403
    finally:
        db.close()
