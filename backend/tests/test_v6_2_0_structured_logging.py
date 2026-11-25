"""Regression tests for structured JSON logging, X-Request-ID correlation, and service modularization."""
import json
import logging

from fastapi.testclient import TestClient

from backend.app.core.logging_config import (
    JsonStructuredFormatter,
    get_request_id,
    reset_request_id,
    set_request_id,
)
from backend.app.main import app
from backend.app.services import delivery_service, postcode_service
from backend.app.services.deliveries import adjust_operator_workload_count
from backend.app.services.postcodes import (
    classify_verification_evidence,
    normalize_digital_postcode,
)


def test_request_id_header_generated_and_propagated():
    client = TestClient(app)

    r_gen = client.get("/health/live")
    assert r_gen.status_code == 200
    assert r_gen.headers.get("X-Request-ID")
    assert len(r_gen.headers["X-Request-ID"]) >= 8

    r_prop = client.get("/health/live", headers={"X-Request-ID": "corr-e2e-12345"})
    assert r_prop.status_code == 200
    assert r_prop.headers.get("X-Request-ID") == "corr-e2e-12345"


def test_json_structured_formatter_includes_request_id_and_redacts_secrets():
    formatter = JsonStructuredFormatter()
    token = set_request_id("req-corr-999")
    try:
        assert get_request_id() == "req-corr-999"
        rec = logging.LogRecord(
            name="postcodelink.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Auth failed for pl_live_secret12345 and Bearer eyJhbGciOi.payload.sig",
            args=(),
            exc_info=None,
        )
        parsed = json.loads(formatter.format(rec))
        assert parsed["request_id"] == "req-corr-999"
        assert parsed["level"] == "INFO"
        assert "pl_live_secret12345" not in parsed["message"]
        assert "eyJhbGciOi" not in parsed["message"]
        assert "[REDACTED]" in parsed["message"]
    finally:
        reset_request_id(token)


def test_modularized_service_reexports_preserve_identity():
    assert postcode_service.normalize_digital_postcode is normalize_digital_postcode
    assert postcode_service.classify_verification_evidence is classify_verification_evidence
    assert delivery_service.adjust_operator_workload_count is adjust_operator_workload_count
