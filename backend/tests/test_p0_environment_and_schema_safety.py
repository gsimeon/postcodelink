"""Regression tests for P0 schema governance, staging demo-seeding safety, and normalized TRUSTED_PROXIES."""
import asyncio
import os
from unittest.mock import patch

import pytest

from backend.app.config import Settings, settings
from backend.app.main import app, lifespan


def _prod_base_kwargs(**overrides):
    base = {
        "_env_file": None,
        "ENVIRONMENT": "production",
        "SECRET_KEY": "xK9#mP2$vL5!qR8@nW3&zY6^tB4*jH7%",
        "OTP_SECRET_KEY": "mN4@pQ7#rS1$tU9!vW2&xY5^zA8*bC3%",
        "OUTBOX_ENCRYPTION_KEY": "qW8!eR5#tY2$uI9@oP4&aS7^dF1*gH6%",
        "SMS_PROVIDER": "termii",
        "TERMII_API_KEY": "termii_live_key_1234567890",
        "CORS_ORIGINS": ["https://app.postcodelink.ng"],
        "REDIS_URL": "redis://localhost:6379/0",
        "OUTBOX_WORKER_ENABLED": True,
    }
    base.update(overrides)
    return base


def test_staging_defaults_disable_demo_seeding_and_empty_trusted_proxies():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SEED_DEMO_DATA", None)
        os.environ.pop("TRUSTED_PROXIES", None)
        s = Settings(_env_file=None, ENVIRONMENT=" Staging ")
        assert s.ENVIRONMENT == "staging"
        assert s.SEED_DEMO_DATA is False
        assert s.TRUSTED_PROXIES == []


def test_staging_rejects_explicit_demo_seeding():
    with pytest.raises(ValueError, match="SEED_DEMO_DATA cannot be enabled in staging"):
        Settings(_env_file=None, ENVIRONMENT="staging", SEED_DEMO_DATA=True)

    with pytest.raises(ValueError, match="SEED_DEMO_ACCOUNTS cannot be enabled in staging"):
        Settings(_env_file=None, ENVIRONMENT="staging", SEED_DEMO_ACCOUNTS=True)


def test_mixed_case_whitespace_production_derives_empty_trusted_proxies():
    with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
        os.environ.pop("TRUSTED_PROXIES", None)
        s = Settings(**_prod_base_kwargs(ENVIRONMENT=" Production "))
        assert s.ENVIRONMENT == "production"
        assert s.SEED_DEMO_DATA is False
        assert s.TRUSTED_PROXIES == []


def test_development_and_test_environment_defaults():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SEED_DEMO_DATA", None)
        os.environ.pop("TRUSTED_PROXIES", None)
        dev_s = Settings(_env_file=None, ENVIRONMENT="development")
        assert dev_s.SEED_DEMO_DATA is True
        assert dev_s.TRUSTED_PROXIES == ["127.0.0.1", "::1", "localhost", "testclient"]

        test_s = Settings(_env_file=None, ENVIRONMENT="test")
        assert test_s.SEED_DEMO_DATA is False
        assert test_s.TRUSTED_PROXIES == ["127.0.0.1", "::1", "localhost", "testclient"]


def test_lifespan_skips_create_all_in_staging_and_production():
    async def _run_lifespan():
        async with lifespan(app):
            pass

    for env_name in ("staging", "production"):
        with (
            patch.object(settings, "ENVIRONMENT", env_name),
            patch.object(settings, "SEED_DEMO_DATA", False),
            patch.object(settings, "SEED_DEMO_ACCOUNTS", False),
            patch.object(settings, "OUTBOX_WORKER_ENABLED", False),
            patch("backend.app.main.Base.metadata.create_all") as mock_create_all,
        ):
            asyncio.run(_run_lifespan())
            mock_create_all.assert_not_called()

    with (
        patch.object(settings, "ENVIRONMENT", "development"),
        patch.object(settings, "SEED_DEMO_DATA", False),
        patch.object(settings, "OUTBOX_WORKER_ENABLED", False),
        patch("backend.app.main.Base.metadata.create_all") as mock_create_all,
    ):
        asyncio.run(_run_lifespan())
        mock_create_all.assert_called_once()
