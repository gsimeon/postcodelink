"""Regression tests for the v6.0.3 operational hardening release."""
import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.app.config import settings
import backend.app.core.rate_limiter as rate_limiter
from backend.app.core.rate_limiter import (
    _safe_redis_endpoint,
    check_client_ip_rate_limit,
    get_rate_limiter_status,
)
from backend.app.services.nipost_client import NIPOSTClient


def test_redis_endpoint_logging_label_never_contains_credentials():
    endpoint = _safe_redis_endpoint(
        "rediss://operator:super-secret-password@cache.internal.example:6380/4?ssl=true"
    )
    assert endpoint == "rediss://cache.internal.example:6380"
    assert "operator" not in endpoint
    assert "super-secret-password" not in endpoint
    assert "/4" not in endpoint
    assert "ssl=true" not in endpoint


def test_redis_endpoint_malformed_url_is_not_echoed():
    assert _safe_redis_endpoint("redis://user:secret@[broken") == "configured"


def test_redis_connection_logs_do_not_expose_url_or_exception(monkeypatch, caplog):
    secret_url = "redis://operator:redis-password@cache.internal.example:6379/0"
    monkeypatch.setattr(settings, "REDIS_URL", secret_url)
    monkeypatch.setattr(rate_limiter, "_REDIS_CLIENT", None)
    monkeypatch.setattr(rate_limiter, "_LAST_CONNECT_ATTEMPT", 0.0)

    fake_redis = MagicMock()
    fake_redis.ping.side_effect = RuntimeError("AUTH failed for redis-password")
    fake_module = MagicMock()
    fake_module.from_url.return_value = fake_redis

    with patch.dict("sys.modules", {"redis": fake_module}):
        with caplog.at_level(logging.INFO):
            with patch.object(
                logging.getLogger("rate_limiter"),
                "warning",
                wraps=logging.getLogger("rate_limiter").warning,
            ) as spy_warn:
                assert rate_limiter._get_redis_client() is None

    spy_warn.assert_called()
    warn_args = spy_warn.call_args[0]
    warn_rendered = warn_args[0] % warn_args[1:] if len(warn_args) > 1 else str(warn_args[0])
    rendered = f"{caplog.text}\n{warn_rendered}"
    assert "cache.internal.example" not in rendered
    assert "operator" not in rendered
    assert "redis-password" not in rendered
    assert "AUTH failed" not in rendered
    assert "RuntimeError" in rendered


def test_public_ip_fallback_evicts_expired_ip_buckets(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(rate_limiter.time, "time", lambda: now)
    monkeypatch.setattr(rate_limiter, "_get_redis_client", lambda: None)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(rate_limiter, "_LAST_CLEANUP_TIME", now - 121.0)

    with rate_limiter._LOCK:
        rate_limiter._KEY_REQUEST_WINDOWS.clear()
        rate_limiter._KEY_REQUEST_WINDOWS["ip_198.51.100.10"] = [now - 400.0]
        rate_limiter._KEY_REQUEST_WINDOWS["ip_198.51.100.11"] = [now - 10.0]

    check_client_ip_rate_limit("198.51.100.12", limit_per_minute=10)

    with rate_limiter._LOCK:
        assert "ip_198.51.100.10" not in rate_limiter._KEY_REQUEST_WINDOWS
        assert "ip_198.51.100.11" in rate_limiter._KEY_REQUEST_WINDOWS
        assert "ip_198.51.100.12" in rate_limiter._KEY_REQUEST_WINDOWS


def test_rate_limiter_status_distinguishes_fail_closed_from_memory_fallback(monkeypatch):
    monkeypatch.setattr(rate_limiter, "_get_redis_client", lambda: None)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "RATE_LIMIT_REDIS_FAIL_CLOSED", True)
    monkeypatch.setattr(settings, "ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", False)

    status = get_rate_limiter_status()
    assert status["backend"] == "unavailable_fail_closed"
    assert status["available"] is False
    assert status["alert_fail_closed_unavailable"] is True
    assert status["alert_in_memory_fallback"] is False

    monkeypatch.setattr(settings, "ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", True)
    fallback_status = get_rate_limiter_status()
    assert fallback_status["backend"] == "in_memory_fallback"
    assert fallback_status["available"] is True
    assert fallback_status["alert_in_memory_fallback"] is True
    assert fallback_status["alert_fail_closed_unavailable"] is False


@pytest.mark.parametrize(
    "status_code,response_body",
    [
        (502, "private upstream response with sensitive payload"),
        (503, "internal service hostname and diagnostic details"),
    ],
)
def test_nipost_lookup_http_failure_logs_are_sanitized(caplog, status_code, response_body):
    client = NIPOSTClient(
        base_url="https://nipost.example.test",
        api_key="nipost-test-key",
    )
    response = MagicMock()
    response.status_code = status_code
    response.text = response_body

    with patch("httpx.Client.get", return_value=response):
        with caplog.at_level(logging.WARNING):
            with patch.object(
                logging.getLogger("nipost_client"),
                "warning",
                wraps=logging.getLogger("nipost_client").warning,
            ) as spy_warn:
                result = client.lookup_postcode("100001")

    assert result.status.value == "UNAVAILABLE"
    warn_calls = " ".join([
        call[0][0] % call[0][1:] if len(call[0]) > 1 else str(call[0][0])
        for call in spy_warn.call_args_list
    ])
    rendered = f"{caplog.text}\n{warn_calls}"
    assert response_body not in rendered
    assert "100001" not in rendered
    assert "nipost-test-key" not in rendered


def test_nipost_lookup_exception_logs_only_error_category(caplog):
    client = NIPOSTClient(
        base_url="https://nipost.example.test",
        api_key="nipost-test-key",
    )
    secret_detail = "connection to private-host.internal failed using token secret-value"

    with patch("httpx.Client.get", side_effect=RuntimeError(secret_detail)):
        with caplog.at_level(logging.WARNING):
            with patch.object(
                logging.getLogger("nipost_client"),
                "warning",
                wraps=logging.getLogger("nipost_client").warning,
            ) as spy_warn:
                result = client.lookup_postcode("100001")

    assert result.status.value == "UNAVAILABLE"
    spy_warn.assert_called()
    warn_calls = " ".join([
        call[0][0] % call[0][1:] if len(call[0]) > 1 else str(call[0][0])
        for call in spy_warn.call_args_list
    ])
    rendered = f"{caplog.text}\n{warn_calls}"
    assert secret_detail not in rendered
    assert "private-host.internal" not in rendered
    assert "secret-value" not in rendered
    assert "RuntimeError" in rendered
