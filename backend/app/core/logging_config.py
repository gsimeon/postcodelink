"""Structured JSON logging and per-request correlation ID helpers."""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import re

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_SENSITIVE_PATTERN = re.compile(
    r"(pl_(?:test|live)_[A-Za-z0-9_-]+|Bearer\s+[A-Za-z0-9._-]+|postcodelink_session=[^;\s]+)",
    re.IGNORECASE,
)


def get_request_id() -> str:
    return _request_id_ctx.get()


def set_request_id(request_id: str) -> object:
    return _request_id_ctx.set(request_id)


def reset_request_id(token: object) -> None:
    _request_id_ctx.reset(token)


class JsonStructuredFormatter(logging.Formatter):
    """Formats log records as single-line JSON with correlation ID and secret scrubbing."""

    def format(self, record: logging.LogRecord) -> str:
        msg = _SENSITIVE_PATTERN.sub("[REDACTED]", record.getMessage())
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", None) or get_request_id(),
            "message": msg,
        }
        return json.dumps(payload, default=str)


def configure_structured_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonStructuredFormatter())
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.setFormatter(JsonStructuredFormatter())
