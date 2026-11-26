"""Dedicated regression tests for API-key environment migration & auth ordering."""
from datetime import datetime, timezone
import hashlib
import os
import sqlite3
import uuid
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

from backend.app.config import settings
from backend.app.core.security import create_access_token
from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models.api_key import ApiKey
from backend.app.models.enums import AppRole
from backend.app.models.profile import Profile


def _upgrade_to_d4e5f6a7b8c9(db_path):
    db_url = f"sqlite:///{db_path.as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    with patch.object(settings, "DATABASE_URL", db_url):
        command.upgrade(cfg, "c3d4e5f6a7b8")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO profiles (id, full_name, role, email, hashed_password, created_at, updated_at) "
                "VALUES ('m_mig', 'Migration Merchant', 'MERCHANT', 'mig@test.ng', 'pw', '2026-01-01', '2026-01-01')"
            )
            cases = [
                ("k_test", "pl_test_abc123", "h_test"),
                ("k_live", "pl_live_abc123", "h_live"),
                ("k_other", "pl_other_abc123", "h_other"),
                ("k_xtest", "plXtest_abc123", "h_xtest"),
                ("k_xlive", "plXlive_abc123", "h_xlive"),
                ("k_unknown", "unknown_abc123", "h_unknown"),
                ("k_empty", "", "h_empty"),
            ]
            for key_id, prefix, hashed in cases:
                conn.execute(
                    "INSERT INTO api_keys "
                    "(id, merchant_id, name, key_prefix, hashed_key, monthly_quota, current_period, "
                    "period_usage_count, usage_count, rate_limit_per_minute, is_active, is_revoked, created_at) "
                    "VALUES (?, 'm_mig', ?, ?, ?, 100, '2026-11', 0, 0, 60, 1, 0, '2026-01-01')",
                    (key_id, f"Key {key_id}", prefix, hashed),
                )
            conn.commit()
        finally:
            conn.close()

        command.upgrade(cfg, "d4e5f6a7b8c9")
    return cfg, db_url


def test_api_key_environment_migration_exact_prefixes_and_idempotency(tmp_path):
    """Verify exact SUBSTR prefix classification, quarantine, and idempotency on re-upgrade."""
    db_path = tmp_path / "api_key_env_mig.db"
    cfg, db_url = _upgrade_to_d4e5f6a7b8c9(db_path)

    conn = sqlite3.connect(db_path)
    try:
        rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, environment, is_active FROM api_keys")}
    finally:
        conn.close()

    assert rows["k_test"] == ("test", 1)
    assert rows["k_live"] == ("live", 1)
    assert rows["k_other"] == ("unclassified", 0)
    assert rows["k_xtest"] == ("unclassified", 0)
    assert rows["k_xlive"] == ("unclassified", 0)
    assert rows["k_unknown"] == ("unclassified", 0)
    assert rows["k_empty"] == ("unclassified", 0)

    # Re-running upgrade to head must remain idempotent and not reclassify keys
    with patch.object(settings, "DATABASE_URL", db_url):
        command.upgrade(cfg, "head")

    conn = sqlite3.connect(db_path)
    try:
        rows_after = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, environment, is_active FROM api_keys")}
    finally:
        conn.close()

    assert rows_after == rows


def test_api_key_environment_migration_exact_prefixes_postgres():
    """Verify exact SUBSTR prefix classification, quarantine, and idempotency on PostgreSQL when configured."""
    base_db_url = os.getenv("DATABASE_URL", "")
    if not base_db_url.startswith("postgresql"):
        pytest.skip("PostgreSQL DATABASE_URL not configured")

    parsed = make_url(base_db_url)
    admin_url = parsed.set(database="postgres")
    test_db_name = f"postcodelink_key_mig_{uuid.uuid4().hex[:8]}"
    test_db_url = parsed.set(database=test_db_name).render_as_string(hide_password=False)

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))

    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", test_db_url)
        with patch.object(settings, "DATABASE_URL", test_db_url):
            command.upgrade(cfg, "c3d4e5f6a7b8")

            test_engine = create_engine(test_db_url)
            try:
                with test_engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO profiles (id, full_name, role, email, hashed_password, created_at, updated_at) "
                            "VALUES ('m_mig_pg', 'PG Migration Merchant', 'MERCHANT', 'mig-pg@test.ng', 'pw', NOW(), NOW())"
                        )
                    )
                    cases = [
                        ("k_test", "pl_test_abc123", "h_test"),
                        ("k_live", "pl_live_abc123", "h_live"),
                        ("k_other", "pl_other_abc123", "h_other"),
                        ("k_xtest", "plXtest_abc123", "h_xtest"),
                        ("k_xlive", "plXlive_abc123", "h_xlive"),
                        ("k_unknown", "unknown_abc123", "h_unknown"),
                        ("k_empty", "", "h_empty"),
                    ]
                    for key_id, prefix, hashed in cases:
                        conn.execute(
                            text(
                                "INSERT INTO api_keys "
                                "(id, merchant_id, name, key_prefix, hashed_key, monthly_quota, current_period, "
                                "period_usage_count, usage_count, rate_limit_per_minute, is_active, is_revoked, created_at) "
                                "VALUES (:id, 'm_mig_pg', :name, :prefix, :hashed, 100, '2026-11', 0, 0, 60, TRUE, FALSE, NOW())"
                            ),
                            {"id": key_id, "name": f"Key {key_id}", "prefix": prefix, "hashed": hashed},
                        )

                command.upgrade(cfg, "d4e5f6a7b8c9")

                with test_engine.connect() as conn:
                    rows = {
                        r[0]: (r[1], bool(r[2]))
                        for r in conn.execute(text("SELECT id, environment, is_active FROM api_keys"))
                    }

                assert rows["k_test"] == ("test", True)
                assert rows["k_live"] == ("live", True)
                assert rows["k_other"] == ("unclassified", False)
                assert rows["k_xtest"] == ("unclassified", False)
                assert rows["k_xlive"] == ("unclassified", False)
                assert rows["k_unknown"] == ("unclassified", False)
                assert rows["k_empty"] == ("unclassified", False)

                command.upgrade(cfg, "head")
                with test_engine.connect() as conn:
                    rows_after = {
                        r[0]: (r[1], bool(r[2]))
                        for r in conn.execute(text("SELECT id, environment, is_active FROM api_keys"))
                    }
                assert rows_after == rows
            finally:
                test_engine.dispose()
    finally:
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": test_db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db_name}"'))
        admin_engine.dispose()


def test_quarantined_and_unclassified_keys_auth_quota_and_rotation():
    """Verify:
    1. Quarantined (inactive) unclassified keys fail with 401.
    2. Active unclassified keys fail with 403 BEFORE consuming monthly quota.
    3. Test and live keys remain separated.
    4. Rotating an active unclassified key issues a pl_test_ key, never pl_live_.
    """
    client = TestClient(app)
    db = SessionLocal()
    try:
        m_id = str(uuid.uuid4())
        merchant = Profile(
            id=m_id,
            full_name="Migration Auth Merchant",
            phone=f"+23480{str(uuid.UUID(m_id).int)[:8]}",
            email=f"mig-auth-{m_id[:8]}@example.com",
            hashed_password="pw",
            role=AppRole.MERCHANT,
        )
        db.add(merchant)

        now_period = datetime.now(timezone.utc).strftime("%Y-%m")
        raw_quarantined = f"plXlive_{uuid.uuid4().hex}"
        raw_active_unclass = f"unknown_{uuid.uuid4().hex}"
        raw_test = f"pl_test_{uuid.uuid4().hex}"
        raw_live = f"pl_live_{uuid.uuid4().hex}"

        quarantined_key = ApiKey(
            merchant_id=m_id,
            name="Quarantined Key",
            environment="unclassified",
            key_prefix=raw_quarantined[:12],
            hashed_key=hashlib.sha256(raw_quarantined.encode()).hexdigest(),
            monthly_quota=100,
            current_period=now_period,
            period_usage_count=0,
            usage_count=0,
            is_active=False,
            is_revoked=False,
        )
        active_unclass_key = ApiKey(
            merchant_id=m_id,
            name="Active Unclassified Key",
            environment="unclassified",
            key_prefix=raw_active_unclass[:12],
            hashed_key=hashlib.sha256(raw_active_unclass.encode()).hexdigest(),
            monthly_quota=100,
            current_period=now_period,
            period_usage_count=0,
            usage_count=0,
            is_active=True,
            is_revoked=False,
        )
        test_key = ApiKey(
            merchant_id=m_id,
            name="Test Key",
            environment="test",
            key_prefix=raw_test[:12],
            hashed_key=hashlib.sha256(raw_test.encode()).hexdigest(),
            monthly_quota=100,
            current_period=now_period,
            period_usage_count=0,
            usage_count=0,
            is_active=True,
            is_revoked=False,
        )
        live_key = ApiKey(
            merchant_id=m_id,
            name="Live Key",
            environment="live",
            key_prefix=raw_live[:12],
            hashed_key=hashlib.sha256(raw_live.encode()).hexdigest(),
            monthly_quota=100,
            current_period=now_period,
            period_usage_count=0,
            usage_count=0,
            is_active=True,
            is_revoked=False,
        )
        db.add_all([quarantined_key, active_unclass_key, test_key, live_key])
        db.commit()
        db.refresh(active_unclass_key)

        # 1. Quarantined key cannot authenticate
        res_q = client.get(
            "/api/v1/postcodes/commercial/lookup?state=Lagos",
            headers={"x-api-key": raw_quarantined},
        )
        assert res_q.status_code == 401

        # 2. Active unclassified key fails 403 and NEVER consumes quota
        res_u = client.get(
            "/api/v1/postcodes/commercial/lookup?state=Lagos",
            headers={"x-api-key": raw_active_unclass},
        )
        assert res_u.status_code == 403
        db.expire_all()
        refreshed_u = db.query(ApiKey).filter(ApiKey.id == active_unclass_key.id).first()
        assert refreshed_u.period_usage_count == 0
        assert refreshed_u.usage_count == 0
        assert refreshed_u.last_used_at is None

        # 3. Test/live separation
        res_test = client.get(
            "/api/v1/postcodes/commercial/lookup?state=Lagos",
            headers={"x-api-key": raw_test},
        )
        assert res_test.status_code == 200
        assert res_test.json()["is_live_nipost"] is False
        assert res_test.json()["upstream_contacted"] is False

        # 4. Rotating an active unclassified key never converts it to live
        token = create_access_token(data={"sub": m_id, "role": AppRole.MERCHANT.value})
        res_rot = client.post(
            f"/api/v1/api-keys/{active_unclass_key.id}/rotate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_rot.status_code == 201
        rot_data = res_rot.json()
        assert rot_data["environment"] == "test"
        assert rot_data["key_prefix"].startswith("pl_test_")
        assert rot_data["api_key"].startswith("pl_test_")
    finally:
        db.close()
