"""v6.3.2 regression tests for API-key quota concurrency, NIPOST commercial gates, and health diagnostics."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import uuid
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.app.config import settings
from backend.app.core.security import create_access_token
from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models.api_key import ApiKey
from backend.app.models.enums import AppRole
from backend.app.models.profile import Profile
from backend.app.routers.api_keys import get_api_key_merchant


def _seed_merchant_and_key(db, *, prefix: str = "pl_test_", monthly_quota: int = 3):
    uid = str(uuid.uuid4())
    merchant = Profile(
        id=uid,
        full_name="Quota Test Merchant",
        phone=f"+23480{str(uuid.UUID(uid).int)[:8]}",
        email=f"quota-{uid[:6]}@test.ng",
        hashed_password="pw",
        role=AppRole.MERCHANT,
    )
    db.add(merchant)
    db.flush()

    raw_key = f"{prefix}{uuid.uuid4().hex}"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    now_period = datetime.now(timezone.utc).strftime("%Y-%m")
    key_obj = ApiKey(
        id=str(uuid.uuid4()),
        merchant_id=merchant.id,
        name="Quota Test Key",
        key_prefix=raw_key[:12],
        hashed_key=key_hash,
        environment="test" if prefix == "pl_test_" else "live",
        monthly_quota=monthly_quota,
        current_period=now_period,
        period_usage_count=0,
        usage_count=0,
        is_active=True,
        is_revoked=False,
    )
    db.add(key_obj)
    db.commit()
    return merchant.id, key_obj.id, raw_key


def test_api_key_quota_concurrency_enforces_limit():
    db = SessionLocal()
    try:
        dialect = getattr(db.get_bind().dialect, "name", "")
        _, key_id, raw_key = _seed_merchant_and_key(db, prefix="pl_test_", monthly_quota=3)
    finally:
        db.close()

    def _consume():
        worker_db = SessionLocal()
        try:
            get_api_key_merchant(x_api_key=raw_key, request=None, db=worker_db)
            return ("ok", 200)
        except HTTPException as exc:
            worker_db.rollback()
            return ("http_error", exc.status_code)
        except OperationalError:
            worker_db.rollback()
            return ("db_locked", None)
        finally:
            worker_db.close()

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: _consume(), range(5)))

    ok_count = sum(1 for status, _ in results if status == "ok")
    assert 1 <= ok_count <= 3
    if dialect == "postgresql":
        assert ok_count == 3
        rate_limited = [code for status, code in results if status == "http_error"]
        assert rate_limited == [429, 429]

    check_db = SessionLocal()
    try:
        refreshed = check_db.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert refreshed.period_usage_count == ok_count
        assert refreshed.usage_count == ok_count
    finally:
        check_db.close()


def test_live_commercial_key_blocked_when_nipost_production_unauthorized():
    client = TestClient(app)
    db = SessionLocal()
    try:
        _, _, live_raw_key = _seed_merchant_and_key(db, prefix="pl_live_", monthly_quota=100)
        _, _, test_raw_key = _seed_merchant_and_key(db, prefix="pl_test_", monthly_quota=100)
    finally:
        db.close()

    with patch.object(settings, "NIPOST_PRODUCTION_AUTHORIZED", False):
        live_res = client.post(
            "/api/v1/postcodes/commercial/cleanse",
            headers={"X-API-Key": live_raw_key},
            json={"address": "22 Bourdillon Road, Ikoyi, Lagos", "postcode_hint": "101245", "strict": True},
        )
        assert live_res.status_code == 403
        assert "NIPOST_PRODUCTION_AUTHORIZED" in live_res.json()["detail"]

        # Sandbox pl_test_ key stays isolated and never hits live NIPOST
        test_res = client.post(
            "/api/v1/postcodes/commercial/cleanse",
            headers={"X-API-Key": test_raw_key},
            json={"address": "22 Bourdillon Road, Ikoyi, Lagos", "postcode_hint": "101245", "strict": False},
        )
        assert test_res.status_code == 200
        body = test_res.json()
        assert body["is_live_nipost"] is False
        assert "Sandbox" in body["provenance"]


def test_admin_nipost_health_check_exposes_6_stage_diagnostics_without_secrets():
    client = TestClient(app)
    db = SessionLocal()
    try:
        uid = str(uuid.uuid4())
        admin = Profile(
            id=uid,
            full_name="Diag Admin",
            phone=f"+23480{str(uuid.UUID(uid).int)[:8]}",
            email=f"diag-admin-{uid[:6]}@test.ng",
            hashed_password="pw",
            role=AppRole.ADMIN,
        )
        db.add(admin)
        db.commit()
        token = create_access_token({"sub": admin.id, "role": admin.role.value})
    finally:
        db.close()

    res = client.post(
        "/api/v1/postcodes/integration/health-check",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    payload = res.json()
    for field in (
        "healthy",
        "connectivity_healthy",
        "authentication_verified",
        "contract_verified",
        "production_authorized",
        "upstream_environment",
    ):
        assert field in payload
    serialized = str(payload).lower()
    assert "nipost_live_" not in serialized
    assert "api_key" not in serialized
