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


@pytest.mark.parametrize(
    "payload,expected_status",
    [
        ({"status": "NOT_FOUND"}, "NOT_FOUND"),
        ({"status": "INVALID"}, "INVALID_INPUT"),
        ({"status": "INVALID_FORMAT"}, "INVALID_INPUT"),
        ({"error_code": "VALIDATION_ERROR"}, "INVALID_INPUT"),
        ({"valid": False}, "NOT_FOUND"),
        ({"found": False}, "NOT_FOUND"),
        ({"matches": []}, "NOT_FOUND"),
    ],
)
def test_nipost_payload_negative_statuses_are_not_conflated(payload, expected_status):
    status, _, _ = NIPOSTClient._adapt_nipost_payload(payload, "100001")
    assert status.value == expected_status


@pytest.mark.parametrize(
    "body",
    [
        {"detail": "Not Found"},
        {"detail": "postcode route not found"},
        {"message": "postcode invalid"},
        {"status": "INVALID"},
        {"error": "postcode lookup failed"},
    ],
)
def test_generic_nipost_json_404_is_unavailable_not_postcode_not_found(body):
    client = NIPOSTClient(base_url="https://nipost.example.test", api_key="test-key")
    response = MagicMock()
    response.status_code = 404
    response.headers = {"content-type": "application/json"}
    response.json.return_value = body
    response.text = str(body)

    with patch("httpx.Client.get", return_value=response):
        result = client.lookup_postcode("100001")

    assert result.status.value == "UNAVAILABLE"
    assert result.http_status == 404


def test_explicit_nipost_postcode_not_found_404_is_not_found():
    client = NIPOSTClient(base_url="https://nipost.example.test", api_key="test-key")
    response = MagicMock()
    response.status_code = 404
    response.headers = {"content-type": "application/json"}
    response.json.return_value = {"status": "NOT_FOUND", "postcode": "100001"}
    response.text = '{"status":"NOT_FOUND","postcode":"100001"}'

    with patch("httpx.Client.get", return_value=response):
        result = client.lookup_postcode("100001")

    assert result.status.value == "NOT_FOUND"
    assert result.http_status == 404


def test_rate_limiter_health_endpoint_omits_redis_username_password_and_query(monkeypatch):
    monkeypatch.setattr(rate_limiter, "_get_redis_client", lambda: None)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(
        settings,
        "REDIS_URL",
        "rediss://operator:secret-password@cache.internal.example:6380/4?ssl=true",
    )

    status = get_rate_limiter_status()
    assert status["redis_endpoint"] == "rediss://cache.internal.example:6380"
    rendered = str(status)
    for secret in ("operator", "secret-password", "/4", "ssl=true"):
        assert secret not in rendered


def test_nipost_404_strict_machine_readable_discrimination_all_six_scenarios():
    """Verify all 6 release-blocking 404 scenarios specified in v6.0.5 review:
    1. Generic gateway 404 -> UNAVAILABLE
    2. HTML reverse-proxy 404 -> UNAVAILABLE
    3. Explicit documented postcode-not-found code -> NOT_FOUND
    4. Unrelated resource-not-found message -> UNAVAILABLE
    5. Malformed JSON -> UNAVAILABLE
    6. Response referring to a different postcode -> UNAVAILABLE
    """
    import httpx
    from backend.app.services.nipost_client import NIPOSTLookupStatus

    # 1. Generic gateway 404
    c1 = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"detail": "Not Found"})
    ))
    assert c1.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE

    # 2. HTML reverse-proxy 404
    c2 = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, text="<html><body>404 Not Found nginx/1.24.0</body></html>", headers={"content-type": "text/html"})
    ))
    assert c2.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE

    # 3. Explicit documented postcode-not-found code with matching postcode
    c3 = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"error_code": "POSTCODE_NOT_FOUND", "postcode": "100001"})
    ))
    res3 = c3.lookup_postcode("100001")
    assert res3.status == NIPOSTLookupStatus.NOT_FOUND
    assert res3.http_status == 404

    # 3b. Explicit documented status code
    c3b = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"status": "NOT_FOUND", "postcode": "100001"})
    ))
    assert c3b.lookup_postcode("100001").status == NIPOSTLookupStatus.NOT_FOUND

    # 4. Unrelated resource-not-found message
    c4 = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"detail": "User not found", "error": "Resource not found"})
    ))
    assert c4.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE

    # 5. Malformed JSON
    c5 = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, text="{malformed: json, unclosed", headers={"content-type": "application/json"})
    ))
    assert c5.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE

    # 6. Response referring to a different postcode
    c6 = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"error_code": "POSTCODE_NOT_FOUND", "postcode": "999999"})
    ))
    # Requested 100001, but response echoed 999999 -> rejected as UNAVAILABLE
    assert c6.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE


def test_nipost_404_echoed_postcode_matching_missing_and_mismatched():
    """Verify exact behavior for matching, missing, and mismatched echoed postcodes in 404 responses."""
    import httpx
    from backend.app.services.nipost_client import NIPOSTLookupStatus

    # Case A: Matching echoed postcode -> NOT_FOUND
    c_match = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"status": "NOT_FOUND", "postcode": "100001"})
    ))
    assert c_match.lookup_postcode("100001").status == NIPOSTLookupStatus.NOT_FOUND

    # Case B: Missing echoed postcode -> UNAVAILABLE (cannot verify negative result is for queried postcode)
    c_missing = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"status": "NOT_FOUND"})
    ))
    assert c_missing.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE

    # Case C: Mismatched echoed postcode -> UNAVAILABLE
    c_mismatch = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"status": "NOT_FOUND", "postcode": "999999"})
    ))
    assert c_mismatch.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE


def test_nipost_valid_false_distinguishes_malformed_from_absent_input():
    """Verify decision sequence: malformed input returning valid:false is INVALID_INPUT; well-formed input returning valid:false is NOT_FOUND."""
    from backend.app.services.nipost_client import NIPOSTLookupStatus

    # 1. Malformed input (syntax invalid) returning 200 {"valid": False}
    # Must NOT be classified as NOT_FOUND
    malformed_inputs = ["12-ABC", "INVALID_LEN_999999999", "12345", "xyz!@#", "1234567"]
    for bad_code in malformed_inputs:
        status, _, _ = NIPOSTClient._adapt_nipost_payload({"valid": False}, bad_code)
        assert status == NIPOSTLookupStatus.INVALID_INPUT, f"Expected INVALID_INPUT for bad code {bad_code}, got {status}"

    # 2. Well-formed input returning 200 {"valid": False} -> NOT_FOUND
    well_formed_codes = ["100001", "900001", "FC-02-A09-DB-09", "LA-01-B12-EF-34"]
    for good_code in well_formed_codes:
        status, _, _ = NIPOSTClient._adapt_nipost_payload({"valid": False}, good_code)
        assert status == NIPOSTLookupStatus.NOT_FOUND, f"Expected NOT_FOUND for well-formed absent code {good_code}, got {status}"

    # 3. Ambiguous non-dict or unrecognised payload -> INVALID_RESPONSE
    status_str, _, _ = NIPOSTClient._adapt_nipost_payload("not_a_dict", "100001")
    assert status_str == NIPOSTLookupStatus.INVALID_RESPONSE

    status_empty, _, _ = NIPOSTClient._adapt_nipost_payload({"unknown_schema": True}, "100001")
    assert status_empty == NIPOSTLookupStatus.INVALID_RESPONSE


def test_production_config_rejects_example_and_template_secrets():
    """Verify that Settings validator strictly rejects example and template secrets in production mode."""
    from backend.app.config import Settings
    import os
    import secrets

    valid_rand_secret = secrets.token_urlsafe(32)
    valid_rand_outbox = secrets.token_urlsafe(32)
    valid_rand_otp = secrets.token_urlsafe(32)

    base_prod_env = {
        "ENVIRONMENT": "production",
        "SMS_PROVIDER": "termii",
        "TERMII_API_KEY": "test_termii_key_123",
        "OUTBOX_WORKER_ENABLED": "true",
        "REDIS_URL": "redis://127.0.0.1:6379/0",
        "OTP_SECRET_KEY": valid_rand_otp,
    }

    # 1. Example secret from .env.example must be rejected
    with patch.dict(os.environ, {
        **base_prod_env,
        "SECRET_KEY": "postcodelink_production_secret_key_minimum_32_chars_super_secure!",
        "OUTBOX_ENCRYPTION_KEY": valid_rand_outbox,
    }):
        with pytest.raises(ValueError, match="Fatal Security Error"):
            Settings()

    # 2. Example outbox key from .env.example must be rejected
    with patch.dict(os.environ, {
        **base_prod_env,
        "SECRET_KEY": valid_rand_secret,
        "OUTBOX_ENCRYPTION_KEY": "postcodelink_prod_outbox_key_minimum_32_chars_super_secure!",
    }):
        with pytest.raises(ValueError, match="Fatal Security Error"):
            Settings()

    # 3. Placeholder values must be rejected
    with patch.dict(os.environ, {
        **base_prod_env,
        "SECRET_KEY": "REPLACE_WITH_GENERATED_SECRET_KEY_MIN_32_CHARS_DO_NOT_USE_EXAMPLE",
        "OUTBOX_ENCRYPTION_KEY": valid_rand_outbox,
    }):
        with pytest.raises(ValueError, match="Fatal Security Error"):
            Settings()

    # 4. Valid authentic random secrets are accepted
    with patch.dict(os.environ, {
        **base_prod_env,
        "SECRET_KEY": valid_rand_secret,
        "OUTBOX_ENCRYPTION_KEY": valid_rand_outbox,
    }):
        prod_settings = Settings()
        assert prod_settings.SECRET_KEY == valid_rand_secret


def test_production_config_rejects_weak_entropy_and_repetitive_secrets():
    """Verify that production config strictly rejects low entropy, character stuffing, and simple sequences."""
    from backend.app.config import Settings
    import os
    import secrets

    valid_outbox = secrets.token_urlsafe(32)
    valid_otp = secrets.token_urlsafe(32)
    base_prod_env = {
        "ENVIRONMENT": "production",
        "SMS_PROVIDER": "termii",
        "TERMII_API_KEY": "test_termii_key_123",
        "OUTBOX_WORKER_ENABLED": "true",
        "REDIS_URL": "redis://127.0.0.1:6379/0",
        "OUTBOX_ENCRYPTION_KEY": valid_outbox,
        "OTP_SECRET_KEY": valid_otp,
    }

    # Case A: Repetitive character stuffing ('a' * 32 + suffix)
    with patch.dict(os.environ, {**base_prod_env, "SECRET_KEY": "a" * 32 + "x1y2z3_valid_prod_key"}):
        with pytest.raises(ValueError, match="insufficient character variety|repetitive character runs"):
            Settings()

    # Case B: Predictable numeric sequence
    with patch.dict(os.environ, {**base_prod_env, "SECRET_KEY": "12345678901234567890123456789012"}):
        with pytest.raises(ValueError, match="predictable sequential character sequences|insufficient character diversity"):
            Settings()

    # Case C: Predictable alphabetical sequence
    with patch.dict(os.environ, {**base_prod_env, "SECRET_KEY": "abcdefghijklmnopqrstuvwxyz012345"}):
        with pytest.raises(ValueError, match="predictable sequential character sequences"):
            Settings()

    # Case D: Repeated word stuffing
    with patch.dict(os.environ, {**base_prod_env, "SECRET_KEY": "wordwordwordwordwordwordwordword"}):
        with pytest.raises(ValueError, match="insufficient character diversity|insufficient character variety"):
            Settings()

    # Case E: Identical keys (cryptographic domain separation failure)
    valid_key = secrets.token_urlsafe(32)
    with patch.dict(os.environ, {**base_prod_env, "SECRET_KEY": valid_key, "OUTBOX_ENCRYPTION_KEY": valid_key}):
        with pytest.raises(ValueError, match="OUTBOX_ENCRYPTION_KEY must be distinct from SECRET_KEY"):
            Settings()

    # Case F: Cryptographically strong token_hex and token_urlsafe pass
    sec_hex = secrets.token_hex(32)
    out_url = secrets.token_urlsafe(32)
    with patch.dict(os.environ, {**base_prod_env, "SECRET_KEY": sec_hex, "OUTBOX_ENCRYPTION_KEY": out_url}):
        s = Settings()
        assert s.SECRET_KEY == sec_hex
        assert s.OUTBOX_ENCRYPTION_KEY == out_url


def test_digital_postcode_five_component_structure_validation():
    """Verify validation of 5 canonical components in Nigerian National Digital Postcodes: SS-LL-DDD-AA-BB."""
    # 1. Canonical separated format: SS-LL-DDD-AA-BB
    valid_canonical = [
        "FC-02-A09-DB-09",
        "LA-01-B12-EF-34",
        "KN-10-C01-01-99",
        "OG-05-D88-XY-12",
        "RV-03-E45-AB-67",
    ]
    for code in valid_canonical:
        components = NIPOSTClient.parse_digital_postcode_components(code)
        assert components is not None, f"Expected {code} to parse successfully"
        assert len(components["state"]) == 2 and components["state"].isalpha()
        assert len(components["lga"]) == 2
        assert len(components["district"]) == 3
        assert len(components["area"]) == 2
        assert len(components["building"]) == 2
        assert NIPOSTClient.is_well_formed_postcode(code) is True

    # 2. Normalized unseparated format: SSLLDDDAABB (11 chars)
    valid_normalized = [
        "FC02A09DB09",
        "LA01B12EF34",
        "KN10C010199",
    ]
    for code in valid_normalized:
        components = NIPOSTClient.parse_digital_postcode_components(code)
        assert components is not None, f"Expected {code} to parse successfully"
        assert NIPOSTClient.is_well_formed_postcode(code) is True

    # 3. Malformed separator placements & component errors must be rejected
    malformed_digital_codes = [
        "FC-02-A09DB09",        # Missing last two separators
        "FC--02-A09-DB-09",      # Double hyphen
        "FC-02-A09-DB-09-",      # Trailing hyphen
        "-FC-02-A09-DB-09",      # Leading hyphen
        "LA-012-B1-EF-34",       # Component lengths swapped (3 for LGA, 2 for District)
        "01-02-A09-DB-09",       # Numeric state code (must be 2 letters)
        "FC-02-A09-DB-009",      # Building component too long (3 chars)
        "FC-2-A09-DB-09",        # LGA component too short (1 char)
        "12-ABC",                # Generic malformed
        "INVALID_LEN_999999999", # Too long
    ]
    for bad_code in malformed_digital_codes:
        assert NIPOSTClient.parse_digital_postcode_components(bad_code) is None, f"Expected {bad_code} to fail parsing"
        # Note: legacy codes are numeric 6 digits; bad_code should not be well-formed unless 6 digits
        assert NIPOSTClient.is_well_formed_postcode(bad_code) is False, f"Expected {bad_code} to be rejected"


def test_nipost_404_comprehensive_contract_scenarios():
    """Verify all 7 rigorous contract scenarios for HTTP 404 responses from upstream NIPOST gateway."""
    import httpx
    from backend.app.services.nipost_client import NIPOSTLookupStatus

    # Scenario 1: Postcode returned with different case -> Normalize and compare -> NOT_FOUND
    c1 = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"error_code": "POSTCODE_NOT_FOUND", "postcode": "la-01-b12-ef-34"})
    ))
    assert c1.lookup_postcode("LA-01-B12-EF-34").status == NIPOSTLookupStatus.NOT_FOUND

    # Scenario 2: Postcode returned with standard separators vs unseparated query -> Normalize and compare -> NOT_FOUND
    c2 = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"error_code": "POSTCODE_NOT_FOUND", "postcode": "LA-01-B12-EF-34"})
    ))
    assert c2.lookup_postcode("LA01B12EF34").status == NIPOSTLookupStatus.NOT_FOUND

    # Scenario 3: Multiple postcode fields disagree -> UNAVAILABLE
    c3 = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={
            "error_code": "POSTCODE_NOT_FOUND",
            "postcode": "100001",
            "code": "999999",  # Conflicting codes!
        })
    ))
    assert c3.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE

    # Scenario 4: Echoed postcode is null -> UNAVAILABLE
    c4 = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"error_code": "POSTCODE_NOT_FOUND", "postcode": None})
    ))
    assert c4.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE

    # Scenario 5: Echoed postcode has wrong type (int or list) -> UNAVAILABLE
    c5a = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"error_code": "POSTCODE_NOT_FOUND", "postcode": 100001})
    ))
    assert c5a.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE

    c5b = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"error_code": "POSTCODE_NOT_FOUND", "postcode": ["100001"]})
    ))
    assert c5b.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE

    # Scenario 6: Error code is unknown -> UNAVAILABLE
    c6 = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"error_code": "UNKNOWN_CUSTOM_ERROR", "postcode": "100001"})
    ))
    assert c6.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE

    # Scenario 7: Response contains nested error object (undocumented schema) -> UNAVAILABLE
    c7 = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"error": {"code": "POSTCODE_NOT_FOUND", "postcode": "100001"}})
    ))
    assert c7.lookup_postcode("100001").status == NIPOSTLookupStatus.UNAVAILABLE


def test_nipost_separate_validator_and_autofill_adapters():
    """Verify separate contract adapters for NIPOST Validator (existence) and Autofill (address retrieval)."""
    import httpx
    from backend.app.services.nipost_client import NIPOSTLookupStatus

    # 1. Validator Contract: positive existence
    val_status, val_data, _ = NIPOSTClient._adapt_validator_payload({"valid": True}, "100001")
    assert val_status == NIPOSTLookupStatus.FOUND
    assert val_data["valid"] is True
    assert val_data["service"] == "validator"

    # 2. Validator Contract: absent postcode on well-formed code -> NOT_FOUND
    val_nf_status, _, _ = NIPOSTClient._adapt_validator_payload({"valid": False}, "100001")
    assert val_nf_status == NIPOSTLookupStatus.NOT_FOUND

    # 3. Validator Contract: malformed code -> INVALID_INPUT
    val_inv_status, _, _ = NIPOSTClient._adapt_validator_payload({"valid": False}, "12-ABC")
    assert val_inv_status == NIPOSTLookupStatus.INVALID_INPUT

    # 4. Autofill Contract: positive address retrieval
    autofill_payload = {
        "code": "100001",
        "area": "Lagos Island",
        "state": "Lagos",
        "lga": "Lagos Island",
        "lat": 6.45,
        "lng": 3.40,
    }
    af_status, af_data, _ = NIPOSTClient._adapt_autofill_payload(autofill_payload, "100001")
    assert af_status == NIPOSTLookupStatus.FOUND
    assert af_data["area"] == "Lagos Island"
    assert af_data["state"] == "Lagos"

    # 5. Autofill Contract: absent record via empty matches list -> NOT_FOUND
    af_empty_status, _, _ = NIPOSTClient._adapt_autofill_payload({"matches": []}, "100001")
    assert af_empty_status == NIPOSTLookupStatus.NOT_FOUND

    # 6. Test client validate_postcode() method
    c_val = NIPOSTClient(base_url="https://api.test", transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"valid": True, "code": "100001"})
    ))
    res = c_val.validate_postcode("100001")
    assert res.status == NIPOSTLookupStatus.FOUND
    assert res.data["valid"] is True



