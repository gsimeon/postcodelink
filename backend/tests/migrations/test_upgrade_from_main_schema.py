"""Verify clean Alembic upgrade from the main branch schema baseline (d4f5a6b7c8e9) to head on SQLite & PostgreSQL."""
import os
import sqlite3
import uuid
from unittest.mock import patch

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.url import make_url

from backend.app.config import settings

MAIN_BASELINE_REVISION = "d4f5a6b7c8e9"


def test_upgrade_from_main_baseline_to_head_sqlite(tmp_path):
    db_path = tmp_path / "upgrade_from_main.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    with patch.object(settings, "DATABASE_URL", db_url):
        command.upgrade(cfg, MAIN_BASELINE_REVISION)

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO profiles (id, full_name, role, email, hashed_password, created_at, updated_at) "
                "VALUES ('m_main', 'Main Merchant', 'MERCHANT', 'main@test.ng', 'pw', '2026-11-14', '2026-11-14')"
            )
            conn.execute(
                "INSERT INTO api_keys (id, merchant_id, name, key_prefix, hashed_key, monthly_quota, usage_count, is_active, created_at) "
                "VALUES ('k_main_test', 'm_main', 'Main Test', 'pl_test_1111', 'hm1', 100, 2, 1, '2026-11-14')"
            )
            conn.execute(
                "INSERT INTO api_keys (id, merchant_id, name, key_prefix, hashed_key, monthly_quota, usage_count, is_active, created_at) "
                "VALUES ('k_main_legacy', 'm_main', 'Main Legacy', 'pkl_old_2222', 'hm2', 100, 0, 1, '2026-11-14')"
            )
            conn.commit()
        finally:
            conn.close()

        command.upgrade(cfg, "head")

        engine = create_engine(db_url)
        try:
            tables = set(inspect(engine).get_table_names())
            assert "verification_evidence" in tables
            assert "consumed_challenge_nonces" in tables
            with engine.connect() as c:
                rows = {r[0]: (r[1], r[2]) for r in c.execute(text("SELECT id, environment, is_active FROM api_keys"))}
                assert rows["k_main_test"] == ("test", 1)
                assert rows["k_main_legacy"] == ("unclassified", 0)
        finally:
            engine.dispose()


def test_upgrade_from_main_baseline_to_head_postgres():
    base_db_url = os.getenv("DATABASE_URL", "")
    if not base_db_url.startswith("postgresql"):
        pytest.skip("PostgreSQL DATABASE_URL not configured")

    parsed = make_url(base_db_url)
    admin_url = parsed.set(database="postgres")
    test_db_name = f"postcodelink_main_upg_{uuid.uuid4().hex[:8]}"
    test_db_url = parsed.set(database=test_db_name).render_as_string(hide_password=False)

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))

    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", test_db_url)
        with patch.object(settings, "DATABASE_URL", test_db_url):
            command.upgrade(cfg, MAIN_BASELINE_REVISION)

            eng = create_engine(test_db_url)
            try:
                with eng.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO profiles (id, full_name, role, email, hashed_password, created_at, updated_at) "
                            "VALUES ('m_main_pg', 'Main PG Merchant', 'MERCHANT', 'main-pg@test.ng', 'pw', NOW(), NOW())"
                        )
                    )
                    conn.execute(
                        text(
                            "INSERT INTO api_keys (id, merchant_id, name, key_prefix, hashed_key, monthly_quota, usage_count, is_active, created_at) "
                            "VALUES ('k_pg_test', 'm_main_pg', 'PG Test', 'pl_test_1111', 'hp1', 100, 0, TRUE, NOW())"
                        )
                    )
                    conn.execute(
                        text(
                            "INSERT INTO api_keys (id, merchant_id, name, key_prefix, hashed_key, monthly_quota, usage_count, is_active, created_at) "
                            "VALUES ('k_pg_legacy', 'm_main_pg', 'PG Legacy', 'pkl_old_2222', 'hp2', 100, 0, TRUE, NOW())"
                        )
                    )

                command.upgrade(cfg, "head")

                tables = set(inspect(eng).get_table_names())
                assert "verification_evidence" in tables
                assert "consumed_challenge_nonces" in tables
                with eng.connect() as conn:
                    rows = {
                        r[0]: (r[1], bool(r[2]))
                        for r in conn.execute(text("SELECT id, environment, is_active FROM api_keys"))
                    }
                    assert rows["k_pg_test"] == ("test", True)
                    assert rows["k_pg_legacy"] == ("unclassified", False)
            finally:
                eng.dispose()
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
