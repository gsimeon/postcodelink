"""Regression coverage for the v6.0.7 secret and postcode integrity gate."""
import os
import secrets
from unittest.mock import patch

import pytest

from backend.app.config import Settings
from backend.app.services.nipost_client import NIPOSTClient, NIPOSTLookupStatus


def _production_env(**overrides):
    values = {
        "ENVIRONMENT": "production",
        "SMS_PROVIDER": "termii",
        "TERMII_API_KEY": "test-termii-key",
        "OUTBOX_WORKER_ENABLED": "true",
        "REDIS_URL": "redis://127.0.0.1:6379/0",
        "SECRET_KEY": secrets.token_urlsafe(32),
        "OUTBOX_ENCRYPTION_KEY": secrets.token_urlsafe(32),
    }
    values.update(overrides)
    if values["SECRET_KEY"] == values["OUTBOX_ENCRYPTION_KEY"]:
        values["OUTBOX_ENCRYPTION_KEY"] = secrets.token_urlsafe(32)
    return values


@pytest.mark.parametrize(
    "weak_value",
    [
        "a" * 64,
        "0123456789abcdef" * 3,
        "postcodelink_prod_" + "x" * 40,
        "REPLACE_WITH_GENERATED_SECRET_KEY_MIN_32_CHARS_DO_NOT_USE_EXAMPLE",
    ],
)
def test_production_rejects_low_diversity_or_template_jwt_secret(weak_value):
    env = _production_env(SECRET_KEY=weak_value)
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match="Fatal Security Error"):
            Settings()


def test_production_rejects_low_diversity_outbox_secret():
    env = _production_env(OUTBOX_ENCRYPTION_KEY="z" * 64)
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match="Fatal Security Error"):
            Settings()


def test_production_accepts_distinct_csprng_sized_secrets():
    env = _production_env()
    assert len(env["SECRET_KEY"]) >= 43
    assert len(env["OUTBOX_ENCRYPTION_KEY"]) >= 43
    with patch.dict(os.environ, env, clear=False):
        configured = Settings()
    assert configured.SECRET_KEY == env["SECRET_KEY"]
    assert configured.OUTBOX_ENCRYPTION_KEY == env["OUTBOX_ENCRYPTION_KEY"]


@pytest.mark.parametrize(
    "postcode",
    [
        "FC-02-A09-DB-09",
        "LA-01-B12-EF-34",
        "FC02A09DB09",
        "LA01B12EF34",
        "100001",
        "900001",
    ],
)
def test_postcode_validator_accepts_canonical_and_compact_formats(postcode):
    assert NIPOSTClient.is_well_formed_postcode(postcode)


@pytest.mark.parametrize(
    "postcode",
    [
        "FC-2-A09-DB-09",       # component 2 too short
        "FC-02-A9-DB-09",       # component 3 too short
        "FC-02-A09-DB9-09",     # component 4 too long
        "FC-02-A09-DB-9",       # component 5 too short
        "FC--A09-DB-09",        # empty component
        "FC/02/A09/DB/09",      # unsupported separators
        "FC-02 A09-DB-09",      # embedded whitespace
        "FC02-A09DB09",         # mixed separator placement
        "FC-02-A09-DB-099",     # wrong total component width
        "12345",
    ],
)
def test_postcode_validator_rejects_noncanonical_component_shapes(postcode):
    assert not NIPOSTClient.is_well_formed_postcode(postcode)


def test_malformed_digital_postcode_is_classified_as_invalid_input():
    status, _, _ = NIPOSTClient._adapt_nipost_payload(
        {"valid": False},
        "FC-2-A09-DB-09",
    )
    assert status == NIPOSTLookupStatus.INVALID_INPUT
